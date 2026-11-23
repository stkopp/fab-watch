import json
import logging
import os
import subprocess
import sys
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from authors import own_message
import notifications
import repairs
import issue_reports
from notification_policy import policies, popout_layout
import engine_releases
from collector import collect, source_attempt
from storage import Store, encode, exclusive, identity, write_file
from transport import NETWORK_MESSAGE, connection_problem, now

VERSION = "1.4.1"
ROOT = Path(os.environ["LOCALAPPDATA"]) / "FabWatch"
CHECK_TASK = "FabWatch-Check"
REVIEW_TASK = "FabWatch-Reviews"
TEST_REVIEW_TASK = "FabWatch-TestReviews"
ENGINE_TASK = "FabWatch-Engine"
ENGINE_REMINDER_TASK = "FabWatch-EngineReminders"
HERE = Path(__file__).resolve().parent
SCHEDULER = Path(os.environ["SystemRoot"]) / "System32" / "schtasks.exe"
INTERVALS = (5, 10, 15, 30, 60, 120, 240, 720, 1440)


def settings():
    path = ROOT / "settings.json"
    if not path.exists():
        return {"interval": 60, "auto_check_after_launch": True}
    try:
        config = json.loads(path.read_bytes())
        if not isinstance(config, dict):
            raise ValueError("Expected an object")
        config.setdefault("interval", 60)
        config.setdefault("auto_check_after_launch", True)
        policies(config)
        popout_layout(config)
        if config.get("github_cli") is not None and not isinstance(config["github_cli"], str):
            raise ValueError("Invalid GitHub CLI setting")
        if type(config["auto_check_after_launch"]) is not bool:
            raise ValueError("Invalid auto-check setting")
        if type(config["interval"]) is not int or config["interval"] not in INTERVALS:
            raise ValueError("Invalid check interval")
        seller = config.get("seller")
        if seller is not None and (not isinstance(seller, dict) or
                not all(isinstance(seller.get(k), str) and seller[k] for k in ("id", "name", "url"))):
            raise ValueError("Invalid seller profile")
        if config.get("schedule_anchor"):
            if datetime.fromisoformat(config["schedule_anchor"]).tzinfo is None:
                raise ValueError("Schedule time must include a timezone")
        return config
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Fab Watch settings could not be read: {path}\n"
                         "Your saved data has not been changed. Restore settings from a backup "
                         "or use Start fresh in setup.") from exc


def save_settings(value):
    ROOT.mkdir(parents=True, exist_ok=True)
    write_file(ROOT / "settings.json", encode(value))


def profile(seller):
    return ROOT / "profiles" / identity(seller["id"])


def initialize(seller, started=None):
    folder = profile(seller)
    folder.mkdir(parents=True, exist_ok=True)
    with exclusive(folder):
        with closing(Store(folder / "monitor.sqlite", create=True).db) as conn:
            with conn:
                conn.execute("INSERT OR IGNORE INTO meta VALUES (?,?)", ("tracking_started_at", encode(started or now())))
    return folder


def scheduler(*args, check=True):
    proc = subprocess.run([str(SCHEDULER), *args], capture_output=True, timeout=20,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode and check:
        raise RuntimeError("Windows Task Scheduler could not apply the change. " +
                           proc.stderr.decode("oem", errors="replace").strip()[:240])
    return proc


def register_task(name, mode, interval, start, *, on_login=True):
    # InteractiveToken uses the current user's Windows session for notifications.
    who = Path(os.environ["SystemRoot"]) / "System32" / "whoami.exe"
    user = subprocess.check_output([str(who), "/user", "/fo", "csv", "/nh"],
                                   creationflags=subprocess.CREATE_NO_WINDOW, text=True).strip().split(",")[-1].strip('"')
    task = Element("Task", {"version": "1.2", "xmlns": "http://schemas.microsoft.com/windows/2004/02/mit/task"})
    triggers = SubElement(task, "Triggers")
    timer = SubElement(triggers, "TimeTrigger")
    repetition = SubElement(timer, "Repetition")
    SubElement(repetition, "Interval").text = f"PT{interval}M"
    SubElement(timer, "StartBoundary").text = start.astimezone().isoformat(timespec="seconds")
    if on_login:
        login = SubElement(triggers, "LogonTrigger")
        SubElement(login, "UserId").text = user
        SubElement(login, "Delay").text = "PT20S"
    principal = SubElement(SubElement(task, "Principals"), "Principal", {"id": "Owner"})
    SubElement(principal, "UserId").text = user
    SubElement(principal, "LogonType").text = "InteractiveToken"
    SubElement(principal, "RunLevel").text = "LeastPrivilege"
    options = SubElement(task, "Settings")
    for key, value in {
        "MultipleInstancesPolicy": "IgnoreNew", "DisallowStartIfOnBatteries": "false",
        "StopIfGoingOnBatteries": "false", "StartWhenAvailable": "true" if on_login else "false",
        "ExecutionTimeLimit": "PT25M" if mode == "--scheduled" else "PT0S",
    }.items():
        SubElement(options, key).text = value
    action = SubElement(SubElement(task, "Actions", {"Context": "Owner"}), "Exec")
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        arguments = mode
    else:
        executable = executable.with_name("pythonw.exe")
        arguments = f'"{HERE / "app.py"}" {mode}'
    SubElement(action, "Command").text = str(executable)
    SubElement(action, "Arguments").text = arguments
    SubElement(action, "WorkingDirectory").text = str(executable.parent)
    path = ROOT / (name + ".xml")
    path.write_bytes(tostring(task, encoding="utf-16", xml_declaration=True))
    try:
        scheduler("/Create", "/TN", name, "/XML", str(path), "/F")
    finally:
        path.unlink(missing_ok=True)


def configure_schedule(config, reset=False):
    start = datetime.now(timezone.utc) + timedelta(minutes=config["interval"])
    anchor = config.get("schedule_anchor")
    if anchor and not reset:
        start = datetime.fromisoformat(anchor)
    register_task(CHECK_TASK, "--scheduled", config["interval"], start,
                  on_login=config.get("auto_check_after_launch", True))
    register_task(REVIEW_TASK, "--reminder", 10, datetime.now(timezone.utc) + timedelta(minutes=10))
    config["schedule_anchor"] = start.isoformat(timespec="seconds")
    save_settings(config)


def next_check(config, clock=None):
    anchor = config.get("schedule_anchor")
    if not anchor:
        return None
    start = datetime.fromisoformat(anchor)
    clock = clock or datetime.now(timezone.utc)
    period = timedelta(minutes=config["interval"])
    if clock < start:
        return start
    return start + ((clock - start) // period + 1) * period


def live_activity_paths(config):
    if config.get("seller"):
        yield profile(config["seller"]) / "monitor.sqlite"
    yield ROOT / "engine" / "monitor.sqlite"


def engine_folder():
    folder = ROOT / "engine"
    folder.mkdir(parents=True, exist_ok=True)
    with closing(Store(folder / "monitor.sqlite", create=True).db):
        pass
    return folder


def notification_action(url):
    import re
    from urllib.parse import urlsplit, parse_qs
    from notification_policy import snooze
    parsed = urlsplit(url)
    if parsed.scheme != "fabwatch" or parsed.netloc not in ("snooze", "read") or parsed.path not in ("", "/"):
        raise ValueError("Invalid notification action")
    query = parse_qs(parsed.query, strict_parsing=True)
    if set(query) != {"scope", "event"} or any(len(v) != 1 for v in query.values()):
        raise ValueError("Invalid notification parameters")
    scope, event_id = query["scope"][0], query["event"][0]
    if scope in ("engine", "test-reviews"):
        folder = ROOT / scope
    elif re.fullmatch(r"[0-9a-f]{24}", scope):
        folder = ROOT / "profiles" / scope
    else:
        raise ValueError("Invalid notification scope")
    if not re.fullmatch(r"(?:[0-9a-f]{24}|test-review-[0-9a-f]{32})", event_id):
        raise ValueError("Invalid event ID")
    db = Store(folder / "monitor.sqlite")
    try:
        if not any(e["event_id"] == event_id and not own_message(e) for e in db.records(reminders=True)):
            return
        if parsed.netloc == "snooze":
            snooze(db, event_id, 30)
        else:
            db.confirm_review(event_id)
    finally:
        db.db.close()


def configure_engine(config):
    engine_folder()
    start = datetime.now(timezone.utc) + timedelta(minutes=5)
    register_task(ENGINE_TASK, "--engine-check", 5, start,
                  on_login=config.get("auto_check_after_launch", True))
    register_task(ENGINE_REMINDER_TASK, "--engine-reminder", 5, start)


def check_engine(config, force=False):
    folder = engine_folder()
    with exclusive(folder):
        db = Store(folder / "monitor.sqlite")
        try:
            errors = []
            with source_attempt(errors, "engine", engine_releases.URL, db.meta("engine_last_success")):
                engine_releases.collect(db, config, force)
            if errors:
                with db.db:
                    db.set_meta("engine_error", NETWORK_MESSAGE if connection_problem(errors)
                                else errors[0]["message"])
                    db.set_meta("engine_last_attempt", now())
            # A scheduler tick with no due scan must not clear the last failure.
            if errors or not db.meta("engine_error"):
                notifications.update_health(db, errors)
            send_issue_reports(db, errors, config)
        except Exception:
            logging.exception("Could not check Unreal Engine announcements")
            with db.db:
                db.set_meta("engine_error", "Could not finish the check. See the local log.")
                db.set_meta("engine_last_attempt", now())
        finally:
            if any(db.records(reminders=True)):
                scheduler("/Run", "/TN", ENGINE_REMINDER_TASK, check=False)
            db.db.close()


def create_test_review(kind="new_review"):
    if kind not in ("new_review", "new_comment", "engine_release"):
        raise ValueError("Invalid test kind")
    from uuid import uuid4
    from review_reminder import awaiting_review
    folder = ROOT / "test-reviews"
    folder.mkdir(parents=True, exist_ok=True)
    with exclusive(folder):
        db = Store(folder / "monitor.sqlite", create=True)
        try:
            with db.db:
                if not any(e["kind"] == kind for e in awaiting_review(db)):
                    db.event("test-review-" + uuid4().hex, {
                        "kind": kind, "test": True, "product": "Demo product (TEST)",
                        "author": "Sample buyer", "created_at": now(),
                        "message": "A new version of Unreal Engine is available: 99.0 (TEST ONLY).",
                        "version": "99.0", "title": "Unreal Engine release — local test",
                        "content_html": "<p>This is a local test comment. Close this window to hide it; "
                                        "it will return in 10 minutes until you select Mark as read.</p>",
                        "review": {"authorDisplayName": "Sample buyer", "rating": 5,
                                   "createdAt": now(), "title": "Test review reminder",
                                   "content": "This is a local test, not a review posted on Fab. "
                                              "Close this window to test the next reminder in 10 minutes. "
                                              "Select Mark as read to stop it permanently."}})
                db.set_meta("last_review_notice", {})
        finally:
            db.db.close()
    register_task(TEST_REVIEW_TASK, "--test-reminder", 10,
                  datetime.now(timezone.utc) + timedelta(minutes=10))
    scheduler("/Run", "/TN", TEST_REVIEW_TASK)


def setup_logging():
    ROOT.mkdir(parents=True, exist_ok=True)
    # Each scheduled role uses its own log to avoid Windows rotation conflicts.
    mode = ("worker" if "--scheduled" in sys.argv else "test-reminders" if "--test-reminder" in sys.argv
            else "engine-check" if "--engine-check" in sys.argv else "engine-reminders" if "--engine-reminder" in sys.argv
            else "reminders" if "--reminder" in sys.argv else "app")
    handler = RotatingFileHandler(ROOT / f"{mode}.log", maxBytes=384000, backupCount=2, encoding="utf-8")
    logging.basicConfig(handlers=[handler], level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def send_issue_reports(db, errors, config):
    try:
        issue_reports.process(db, errors, config.get("github_cli"), VERSION)
    except Exception:
        logging.exception("Could not update the public report queue")


def check(config, scheduled=False, deliver=True):
    seller = config["seller"]
    folder = profile(seller)
    with exclusive(folder):
        db = Store(folder / "monitor.sqlite")
        try:
            if scheduled and not notifications.due(db.meta("last_started_at"), hours=(config["interval"] - 1) / 60):
                return db.meta("last_report")
            with db.db:
                db.set_meta("last_started_at", now())
                db.set_meta("checking", now())
            report = collect(db, seller)
            report["at"] = now()
            notifications.update_health(db, report["errors"])
            repairs.observe(db, report["errors"])
            if deliver:
                if any(not own_message(e) for e in db.records(reminders=True)):
                    scheduler("/Run", "/TN", REVIEW_TASK, check=False)
            with db.db:
                db.set_meta("last_report", report)
            if deliver:
                send_issue_reports(db, report["errors"], config)
            # Save reproducible incidents locally so connector fixes can ship with a new installer.
            for row in db.db.execute("SELECT id,value FROM incidents WHERE state='pending' AND active=1"):
                if not (folder / "incidents" / row["id"] / "incident.json").exists():
                    repairs.prepare(folder, row["id"], json.loads(row["value"]))
            if deliver and config.get("codex"):
                repairs.process(db, folder, config["codex"])
            logging.info("Refresh %s: %s products, %s discussions, %s errors", seller["name"],
                         report["products"], report["forums"], len(report["errors"]))
            return report
        finally:
            with db.db:
                db.set_meta("checking", None)
            db.db.close()
