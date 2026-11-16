"""Official announcement polling, with persistent per-type checkpoints."""
import re
from datetime import datetime, timedelta, timezone

from transport import fetch, now
from storage import identity
from notification_policy import policies

URL = "https://forums.unrealengine.com/c/general/announcements/49.json"
KINDS = ("engine_release", "engine_hotfix", "engine_preview")


def classify(title):
    title = title.strip().rstrip("!")
    hotfix = re.fullmatch(r"(?:Unreal Engine\s+)?(\d+)\.(\d+)\.(\d+)\s+Hotfix\s+(?:Released|is now available)", title, re.I)
    if hotfix:
        return "engine_hotfix", tuple(map(int, hotfix.groups()))
    preview = re.fullmatch(r"Unreal Engine\s+(\d+)\.(\d+)\s+(?:MegaJam\s+)?Preview(?:\s+(\d+))?(?:\s+(?:Released|is now available))?", title, re.I)
    if preview:
        return "engine_preview", tuple(int(v or 0) for v in preview.groups())
    release = re.fullmatch(r"Unreal Engine\s+(\d+)(?:\.(\d+))?(?:\.0)?\s+(?:Released|is now available)", title, re.I)
    if release:
        return "engine_release", tuple(int(v or 0) for v in release.groups())
    return None


def scan(cutoff):
    found, visited = [], set()
    previous = None
    for page in range(100):
        payload = fetch(f"{URL}?order=created&ascending=false&page={page}")
        listing = payload["topic_list"]
        topics = listing["topics"]
        if not isinstance(topics, list) or "more_topics_url" not in listing:
            raise ValueError("Engine announcement pagination changed")
        dates = []
        for topic in topics:
            uid = topic["id"]
            date = datetime.fromisoformat(topic["created_at"].replace("Z", "+00:00"))
            if type(uid) is not int or date.tzinfo is None:
                raise ValueError("Invalid engine announcement")
            if not topic.get("pinned"):
                if previous and date > previous:
                    raise ValueError("Engine announcements are not ordered by creation date")
                previous = date
                dates.append(date)
            if uid in visited:
                continue
            visited.add(uid)
            parsed = classify(topic["title"])
            if not parsed and re.search(r"^Unreal Engine\s+\d+(?:\.\d+).*\b(released|available|preview|hotfix)\b", topic["title"], re.I):
                raise ValueError("Unrecognized engine announcement title; checkpoint unchanged")
            if parsed:
                kind, version = parsed
                found.append({"kind": kind, "version_tuple": version,
                              "version": ".".join(map(str, version)).removesuffix(".0") if kind == "engine_preview" else ".".join(map(str, version)),
                              "topic_id": uid, "created_at": topic["created_at"],
                              "url": f"https://forums.unrealengine.com/t/{uid}", "title": topic["title"]})
        if not listing["more_topics_url"] or (dates and max(dates) < cutoff):
            return found
        if not topics:
            raise ValueError("Incomplete engine announcement page")
    raise ValueError("Engine announcement page limit reached; checkpoint unchanged")


def collect(db, config, force=False):
    clock = datetime.now(timezone.utc)
    prefs = policies(config)
    due = [k for k in KINDS if prefs[k]["check"] is not None and (
        force or not db.meta(k) or clock.timestamp() >= db.meta(k)["checked"] + prefs[k]["check"] * 60)]
    if not due:
        return
    # Full first-year baseline; subsequent scans overlap a day and cover downtime.
    cutoff = min(datetime.fromtimestamp(db.meta(k)["checked"], timezone.utc) - timedelta(days=1)
                 if db.meta(k) else clock - timedelta(days=365) for k in due)
    topics = scan(cutoff)
    snapshots = {}
    for kind in due:
        matching = [t for t in topics if t["kind"] == kind]
        old = db.meta(kind)
        if not matching and not old:
            raise ValueError(f"No {kind} announcement found; baseline unchanged")
        snapshots[kind] = (matching, old)
    with db.db:
        for kind, (matching, old) in snapshots.items():
            highest = tuple(old["highest"]) if old else ()
            for topic in sorted(matching, key=lambda t: t["version_tuple"]):
                version = topic["version_tuple"]
                if version > highest:
                    is_new = old is not None
                    event = {**topic, "product": f"Unreal Engine {topic['version']}", "silent": not is_new,
                             "message": f"A new version of Unreal Engine is available: {topic['version']} ({kind.removeprefix('engine_').title()})."}
                    db.event(identity("engine", kind, topic["version"]), event)
                    highest = version
            db.set_meta(kind, {"highest": highest, "checked": clock.timestamp()})
        db.set_meta("engine_last_success", now())
        db.set_meta("engine_error", None)
