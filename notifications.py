import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from authors import own_message

from storage import encode, identity
from transport import is_connection_error, now, validate_url


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def compact(value):
    return re.sub(r"[\x00-\x1f\x7f]", " ", " ".join(str(value or "").split()))


def summary(event, limit=220):
    review = event.get("review") or {}
    kind = event["kind"]
    if kind.startswith("engine_"):
        return event.get("message", event.get("title", "New Unreal Engine version"))[:limit]
    if kind == "monitor_error":
        return "Some sources could not be checked. Open Check details in Fab Watch."
    author = compact(event.get("author") or review.get("authorDisplayName"))
    if author and own_message(event):
        author += " (seller)"
    content = compact(review.get("content"))
    if kind == "new_comment":
        parser = PlainText()
        parser.feed(event.get("content_html") or "")
        content = compact(" ".join(parser.parts))
    if kind == "ratings_changed":
        before, after = event.get("before", {}), event.get("after", {})
        content = f'New ratings: {event.get("delta", after.get("total", 0) - before.get("total", 0))}'
    date = str(event.get("created_at") or review.get("createdAt") or "")[:10]
    bits = [compact(event.get("product")), author, date, compact(review.get("title")), content]
    return " · ".join(x for x in bits if x)[:limit]


def due(previous, hours=24):
    if not previous:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(previous)).total_seconds() >= hours * 3600


def update_health(db, errors):
    errors = [error for error in errors if not is_connection_error(error)]
    health = [e for e in db.records(pending=True) if e["kind"] == "monitor_error"]
    with db.db:
        if errors and not health and due(db.meta("last_error_acknowledged_at")):
            stamp = now()
            db.event(identity("health", stamp), {"kind": "monitor_error", "errors": errors, "detected_at": stamp})
        elif health:
            for e in health:
                if errors:
                    db.db.execute("UPDATE events SET value=? WHERE id=?", (encode({**e, "errors": errors}), e["event_id"]))
                else:
                    db.db.execute("UPDATE events SET resolved=? WHERE id=?", (now(), e["event_id"]))


def send(payload):
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = Path(__file__).with_name("toast.ps1")
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-File", str(script)],
                            input=encode(payload).encode(), capture_output=True, timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or b"accepted_by_os" not in result.stdout:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip()[:500] or "Toast not confirmed")


def deliver(db):
    import json
    pending = {}
    with db.db:
        for event in db.records(pending=True):
            key = event["event_id"]
            if own_message(event):
                # Also suppress owner messages that were already queued before this upgrade.
                db.db.execute("UPDATE events SET silent=1 WHERE id=?", (key,))
            elif event["kind"] not in ("new_review", "new_comment"):
                pending[key] = event
    batches = {}
    for row in db.db.execute("SELECT * FROM deliveries WHERE state IN ('pending','failed') ORDER BY rowid"):
        ids = [i for i in json.loads(row["value"]) if i in pending]
        if ids:
            batches[row["id"]] = [pending.pop(i) for i in ids]
        else:
            with db.db:
                db.db.execute("UPDATE deliveries SET state='resolved' WHERE id=?", (row["id"],))
    for is_health in (False, True):
        group = [e for e in pending.values() if (e["kind"] == "monitor_error") == is_health]
        if group:
            batches[identity("delivery", *(e["event_id"] for e in group))] = group
    count = failures = 0
    for key, group in batches.items():
        ids = [e["event_id"] for e in group]
        with db.db:
            db.db.execute("INSERT OR IGNORE INTO deliveries (id,value,state) VALUES (?,?,'pending')", (key, encode(ids)))
            db.db.execute("UPDATE deliveries SET attempts=attempts+1,last_attempt=? WHERE id=?", (now(), key))
        health = group[0]["kind"] == "monitor_error"
        title = "Fab Watch | Check issue" if health else f"Fab Watch | {len(group)} new events"
        try:
            send({"title": title, "body": "\n".join(summary(e, 125) for e in group[:3]),
                  "url": group[0].get("url"), "tag": key[:16]})
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            with db.db:
                db.db.execute("UPDATE deliveries SET state='failed',error=? WHERE id=?", (str(exc), key))
            logging.warning("Notification delivery %s failed: %s", key, exc)
            failures += 1
            continue
        accepted = now()
        with db.db:
            db.db.execute("UPDATE deliveries SET state='accepted_by_os',error=NULL WHERE id=?", (key,))
            db.db.executemany("UPDATE events SET accepted=? WHERE id=?", [(accepted, i) for i in ids])
            if health:
                db.set_meta("last_error_acknowledged_at", accepted)
        count += len(ids)
    return count, failures
