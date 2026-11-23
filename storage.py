import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from transport import connection_problem, now
from authors import own_message


def needs_confirmation(event, accepted, silent, resolved):
    if silent or resolved or event.get("confirmed_by_user_at") or own_message(event):
        return False
    if event["kind"] == "monitor_error" and connection_problem(event.get("errors", [])):
        return False
    return event["kind"] in ("new_comment", "engine_release", "engine_hotfix", "engine_preview") or (
        event["kind"] in ("new_review", "ratings_changed", "monitor_error") and not accepted)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources (product TEXT NOT NULL, stage TEXT NOT NULL,
    value TEXT NOT NULL, PRIMARY KEY(product, stage));
CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, value TEXT NOT NULL,
    created TEXT NOT NULL, accepted TEXT, silent INTEGER NOT NULL, resolved TEXT);
CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, value TEXT NOT NULL,
    state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, last_attempt TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, value TEXT NOT NULL,
    streak INTEGER NOT NULL, state TEXT NOT NULL, active INTEGER NOT NULL);
"""


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def identity(*parts):
    return hashlib.sha256(encode(parts).encode()).hexdigest()[:24]


def write_file(path, content):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


@contextmanager
def exclusive(root, name="run.lock"):
    import msvcrt
    with (root / name).open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError("A Fab Monitor command is already running") from exc
        yield


class Store:
    def __init__(self, path, create=False):
        if path.exists() and (path.stat().st_size < 100 or not path.is_file()):
            raise sqlite3.DatabaseError("Existing database is empty or damaged")
        if not create and not path.is_file():
            raise sqlite3.DatabaseError("Database missing; restore or import the previous state")
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0 and create:
                self.db.executescript(SCHEMA + "PRAGMA user_version=1;")
            elif version != 1:
                raise sqlite3.DatabaseError("Unsupported database schema")
            if self.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Database quick_check failed")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
        except BaseException:
            self.db.close()
            raise

    def meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, encode(value)))

    def products(self):
        return {row["id"]: json.loads(row["value"]) for row in self.db.execute("SELECT * FROM products")}

    def source(self, uid, stage):
        row = self.db.execute("SELECT value FROM sources WHERE product=? AND stage=?", (uid, stage)).fetchone()
        return json.loads(row[0]) if row else None

    def set_source(self, uid, stage, value):
        self.db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?)", (uid, stage, encode(value)))

    def commit_source_batch(self, scope, stage, checkpoint, events):
        """Commit normalized (stable ID, payload) pairs with a complete snapshot."""
        with self.db:
            for key, event in events:
                self.event(key, event)
            self.set_source(scope, stage, checkpoint)

    def event(self, event_id, payload):
        self.db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)",
                        (event_id, encode(payload), payload.get("detected_at") or now(),
                         payload.get("acknowledged_at"), bool(payload.get("silent")), payload.get("resolved_at")))

    def records(self, pending=False, limit=None, kind=None, reminders=False):
        sql = "SELECT * FROM events"
        filters, parameters = [], []
        if pending:
            filters.append("accepted IS NULL AND silent=0 AND resolved IS NULL")
        if reminders:
            filters.append("silent=0 AND resolved IS NULL AND json_extract(value,'$.confirmed_by_user_at') IS NULL "
                           "AND (json_extract(value,'$.kind') IN ('new_comment','engine_release','engine_hotfix','engine_preview') OR "
                           "(json_extract(value,'$.kind') IN ('new_review','ratings_changed','monitor_error') AND accepted IS NULL))")
        if kind is not None:
            filters.append("json_extract(value,'$.kind')=?")
            parameters.append(kind)
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY created " + ("ASC" if pending or reminders else "DESC")
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        for row in self.db.execute(sql, parameters):
            yield {**json.loads(row["value"]), "event_id": row["id"], "detected_at": row["created"],
                   "acknowledged_at": row["accepted"], "silent": bool(row["silent"]), "resolved_at": row["resolved"]}

    def confirm_review(self, event_id):
        timestamp = now()
        with self.db:
            result = self.db.execute(
                "UPDATE events SET accepted=coalesce(accepted,?),value=json_set(value,'$.confirmed_by_user_at',?) "
                "WHERE id=? AND (json_extract(value,'$.kind') IN ('new_comment','engine_release','engine_hotfix','engine_preview') OR "
                "(json_extract(value,'$.kind') IN ('new_review','ratings_changed','monitor_error') AND accepted IS NULL)) "
                "AND json_extract(value,'$.confirmed_by_user_at') IS NULL AND silent=0 AND resolved IS NULL",
                (timestamp, timestamp, event_id))
        return result.rowcount == 1

    def migrate(self, legacy_path):
        raw = legacy_path.read_bytes()
        legacy = json.loads(raw)
        if legacy["version"] != 1 or not legacy["products"] or not legacy.get("initialization_complete"):
            raise ValueError("Legacy monitor must have a complete baseline")
        checksum = hashlib.sha256(raw).hexdigest()
        previous = self.meta("legacy_sha256")
        if previous:
            if previous != checksum:
                raise ValueError("A different legacy snapshot is already imported")
            return
        with self.db:
            self.db.executemany("INSERT INTO products VALUES (?,?)",
                                [(uid, encode(p)) for uid, p in legacy["products"].items()])
            for uid, src in legacy["sources"].items():
                detail = {key: src[key] for key in ("ratings", "comment_status", "detail_checked_at") if key in src}
                if detail:
                    self.set_source(uid, "detail", detail)
                if "reviews" in src:
                    self.set_source(uid, "reviews", {
                        "known": src["reviews"], "current": src.get("current_review_ids", []),
                        "checked_at": src.get("reviews_checked_at"), "ratings": src.get("ratings")})
                if "forum" in src:
                    forum = src["forum"]
                    self.set_source(uid, f'forum:{forum["thread_id"]}', forum)
                    self.set_source(uid, "forum_link", {"id": forum["thread_id"]})
            for key, payload in legacy["events"].items():
                self.event(key, payload)
            for key in ("started_at", "catalog_checked_at", "active_product_ids", "last_run_at",
                        "last_error_acknowledged_at", "last_errors", "initialization_complete"):
                if key in legacy:
                    self.set_meta(key, legacy[key])
            self.set_meta("legacy_sha256", checksum)

    def backup(self, path):
        path = Path(path).resolve()
        if path.exists():
            raise FileExistsError("Backup destination already exists")
        with closing(sqlite3.connect(path)) as destination:
            self.db.backup(destination)

    def legacy_export(self, path):
        if path.exists():
            raise FileExistsError("Export destination already exists")
        data = {"version": 1, "products": self.products(), "sources": {},
                "events": {e["event_id"]: e for e in self.records()}}
        for key in ("started_at", "catalog_checked_at", "active_product_ids", "last_run_at",
                    "last_error_acknowledged_at", "last_errors", "initialization_complete"):
            data[key] = self.meta(key)
        for uid in data["products"]:
            item = self.source(uid, "detail") or {}
            rev = self.source(uid, "reviews")
            if rev:
                item.update(reviews=rev["known"], current_review_ids=rev["current"],
                            reviews_checked_at=rev["checked_at"])
                # Legacy monitor couples ratings and reviews in the same checkpoint.
                if rev["ratings"] is not None:
                    item["ratings"] = rev["ratings"]
            link = self.source(uid, "forum_link")
            if link:
                item["forum"] = self.source(uid, f'forum:{link["id"]}')
                item["forum_checked_at"] = item["forum"]["checked_at"]
            data["sources"][uid] = item
        write_file(path, encode(data))
