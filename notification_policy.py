"""Validated notification preferences; minutes are independent of collection."""
from copy import deepcopy

LABELS = {"new_comment": "Forum comment", "new_review": "Review",
          "engine_release": "Engine · Release", "engine_hotfix": "Engine · Hotfix",
          "engine_preview": "Engine · Preview", "ratings_changed": "Rating change",
          "monitor_error": "Source error"}
DEFAULTS = {
    "new_comment": {"mode": "popout", "repeat": 30},
    "new_review": {"mode": "popout", "repeat": 10},
    "engine_release": {"mode": "popout", "repeat": 720, "check": 720},
    "engine_hotfix": {"mode": "none", "repeat": 720, "check": None},
    "engine_preview": {"mode": "windows", "repeat": 720, "check": 720},
    "ratings_changed": {"mode": "windows", "repeat": None},
    "monitor_error": {"mode": "windows", "repeat": 1440},
}


def policies(config):
    supplied = config.get("notifications", {})
    if not isinstance(supplied, dict) or set(supplied) - set(DEFAULTS):
        raise ValueError("Invalid notification settings")
    result = deepcopy(DEFAULTS)
    for kind, override in supplied.items():
        if not isinstance(override, dict) or set(override) - set(result[kind]):
            raise ValueError("Invalid notification preference")
        result[kind].update(override)
    for policy in result.values():
        if policy["mode"] not in ("none", "windows", "popout"):
            raise ValueError("Invalid notification type")
        for key in ("repeat", "check"):
            value = policy.get(key)
            if value is not None and (type(value) is not int or not 5 <= value <= 10080):
                raise ValueError("Intervals must be 5–10080 minutes, or None")
    return result


def due(db, event, policy, clock):
    snoozed = db.meta("snooze:" + event["event_id"])
    if snoozed:
        return clock >= snoozed
    last = db.meta("notice:" + event["event_id"])
    if not last:
        legacy = db.meta("last_review_notice", {})
        if legacy.get("event_id") == event["event_id"]:
            last = {**legacy, "mode": "popout"}
    return not last or last.get("mode") != policy["mode"] or (
        policy["repeat"] is not None and clock >= last["shown_at"] + policy["repeat"] * 60)


def remember(db, event, policy, clock):
    with db.db:
        db.set_meta("notice:" + event["event_id"], {"mode": policy["mode"], "shown_at": clock})
        # A toast action can arrive while the sender waits for OS acceptance.
        # Do not erase a newer snooze set by that action.
        if (db.meta("snooze:" + event["event_id"], 0) or 0) <= clock:
            db.set_meta("snooze:" + event["event_id"], None)


def snooze(db, event_id, minutes, clock=None):
    import time
    if type(minutes) is not int or not 5 <= minutes <= 10080:
        raise ValueError("Snooze must be 5–10080 minutes")
    with db.db:
        db.set_meta("snooze:" + event_id, (time.time() if clock is None else clock) + minutes * 60)


def ask_snooze(parent, callback):
    import tkinter as tk
    from tkinter import ttk, messagebox
    window = tk.Toplevel(parent)
    window.title("Remind me later")
    window.transient(parent)
    frame = ttk.Frame(window, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Remind me in (minutes)").pack(anchor="w", pady=(0, 8))
    value = ttk.Combobox(frame, values=("10", "30", "60", "120", "720", "1440"), width=25)
    value.set("30")
    value.pack(fill="x", pady=(0, 12))
    def apply():
        try:
            minutes = int(value.get())
            if not 5 <= minutes <= 10080:
                raise ValueError("Choose 5–10080 minutes")
            callback(minutes)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Remind me later", str(exc), parent=window)
            return
        window.destroy()
    ttk.Button(frame, text="Remind me later", command=apply).pack(side="right")
    ttk.Button(frame, text="Cancel", command=window.destroy).pack(side="left")
    window.grab_set()
