import logging
import time
import tkinter as tk
import webbrowser
from logging.handlers import RotatingFileHandler
from tkinter import scrolledtext, ttk

from authors import own_message
from appearance import BG, TEXT, FONT
from storage import Store, exclusive
from transport import SourceError, validate_url
from notifications import PlainText, send, summary
from notification_policy import policies, due, remember, LABELS, snooze, ask_snooze

INTERVAL = 600


def awaiting_review(db):
    # Compatibility name: this queue now includes comments, even ones previously
    # accepted by Windows toasts. Only explicit user confirmation stops them.
    return [event for event in db.records(reminders=True) if not own_message(event)]


class ReviewWindow:
    def __init__(self, root, db, is_active, config_provider=lambda: {}):
        self.root, self.db, self.is_active = root, db, is_active
        self.config_provider = config_provider
        self.policy = {}
        self.active = None
        self.timer = None
        root.title("Fab Watch | New review")
        root.minsize(510, 300)
        root.geometry("600x385")
        root.protocol("WM_DELETE_WINDOW", self.keep_open)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        self.heading = ttk.Label(frame, font=(FONT, 15, "bold"), wraplength=520)
        self.heading.pack(anchor="w")
        self.details = ttk.Label(frame, wraplength=520)
        self.details.pack(anchor="w", pady=(4, 12))
        self.body = scrolledtext.ScrolledText(frame, font=(FONT, 11), height=6, wrap="word",
                                             bg=BG, fg=TEXT, relief="flat", padx=10, pady=8)
        self.body.pack(fill="both", expand=True)
        self.status = ttk.Label(frame, wraplength=520)
        self.status.pack(anchor="w", pady=(9, 9))
        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        self.open_button = ttk.Button(controls, text="Open on Fab", command=self.open_review)
        self.open_button.pack(side="left")
        ttk.Button(controls, text="Remind me later", command=self.remind_later).pack(side="left", padx=6)
        ttk.Button(controls, text="Mark as read", command=self.confirm,
                   style="Accent.TButton").pack(side="right")
        root.attributes("-topmost", True)

    def keep_open(self):
        # Closing hides this occurrence only. The database remains unread.
        self.root.withdraw()

    def remind_later(self):
        if not self.active:
            return
        event_id = self.active["event_id"]
        def apply(minutes):
            snooze(self.db, event_id, minutes)
            self.active = None
            self.root.withdraw()
        ask_snooze(self.root, apply)

    def open_review(self):
        if self.active:
            url = self.active.get("url", "")
            try:
                validate_url(url)
                webbrowser.open(url)
            except (SourceError, ValueError, OSError, RuntimeError) as exc:
                logging.warning("Could not open review: %s", exc)
                self.status.configure(text="Could not open the listing.")

    def confirm(self):
        if not self.active:
            return
        try:
            self.db.confirm_review(self.active["event_id"])
        except Exception:
            logging.exception("Could not save review confirmation")
            self.status.configure(text="Could not save. Select Mark as read to try again.")
            return
        self.active = None
        if self.timer is not None:
            self.root.after_cancel(self.timer)
        self.refresh()

    def refresh(self):
        try:
            if not self.is_active():
                self.root.destroy()
                return
            prefs = policies(self.config_provider())
            events = [e for e in awaiting_review(self.db) if prefs[e["kind"]]["mode"] != "none"]
            if not events:
                self.root.destroy()
                return
            clock = time.time()
            for event in events:
                policy = prefs[event["kind"]]
                if (policy["mode"] == "windows" and due(self.db, event, policy, clock)
                        and clock >= self.db.meta("notice_retry:" + event["event_id"], 0)):
                    try:
                        from pathlib import Path
                        from urllib.parse import urlencode
                        folder = Path(self.db.db.execute("PRAGMA database_list").fetchone()[2]).parent
                        scope = folder.name
                        query = urlencode({"scope": scope, "event": event["event_id"]})
                        send({"title": "Fab Watch | " + LABELS[event["kind"]],
                              "body": summary(event), "url": event.get("url"),
                              "snooze_url": "fabwatch://snooze?" + query,
                              "read_url": "fabwatch://read?" + query,
                              "tag": event["event_id"][:16]})
                        remember(self.db, event, policy, clock)
                    except Exception:
                        logging.exception("Windows notification failed; will retry")
                        with self.db.db:
                            self.db.set_meta("notice_retry:" + event["event_id"], clock + 300)
            popouts = [e for e in events if prefs[e["kind"]]["mode"] == "popout"]
            pending = [e for e in popouts if due(self.db, e, prefs[e["kind"]], clock)]
            if self.active and all(e["event_id"] != self.active["event_id"] for e in popouts):
                self.active = None
                self.root.withdraw()
            if self.active and (self.db.meta("snooze:" + self.active["event_id"], 0) or 0) > clock:
                self.active = None
                self.root.withdraw()
            if pending:
                self.active = pending[0]
                self.policy = prefs[self.active["kind"]]
                self.render(len(events))
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                self.root.lift()
                self.root.bell()
                remember(self.db, self.active, self.policy, clock)
                logging.info("Activity reminder displayed: %s", self.active["event_id"])
            elif self.active:
                self.policy = prefs[self.active["kind"]]
                self.render(len(events))
        except Exception:
            logging.exception("Review reminder could not read pending reviews")
        self.timer = self.root.after(5000, self.refresh)

    def render(self, count):
        test = bool(self.active.get("test"))
        comment = self.active["kind"] == "new_comment"
        kind = LABELS.get(self.active["kind"], "message")
        self.root.title(f"Fab Watch | {'Test' if test else 'New'} {kind}")
        self.open_button.configure(state="disabled" if test else "normal",
                                   text="Open discussion" if comment else "Open on Fab")
        review = self.active.get("review") or {}
        if comment:
            parser = PlainText()
            parser.feed(self.active.get("content_html") or "")
            review = {"authorDisplayName": self.active.get("author"),
                      "createdAt": self.active.get("created_at"), "content": " ".join(parser.parts)}
        if self.active["kind"] not in ("new_review", "new_comment"):
            review = {"title": self.active.get("title"), "content": summary(self.active, 2000),
                      "createdAt": self.active.get("created_at")}
            self.open_button.configure(text="Open announcement" if self.active["kind"].startswith("engine_") else "Open source")
        self.heading.configure(text=self.active.get("product") or LABELS.get(self.active["kind"], "New message"))
        bits = [review.get("authorDisplayName"), str(review.get("createdAt") or "")[:10]]
        if review.get("rating") is not None:
            bits.append(f'{review["rating"]}/5')
        self.details.configure(text=" · ".join(str(bit) for bit in bits if bit))
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        self.body.insert("1.0", "\n\n".join(
            str(part) for part in (review.get("title"), review.get("content")) if part))
        self.body.configure(state="disabled")
        self.status.configure(text=("TEST · " if test else "") +
                              f"Unread messages: {count}. " +
                              (f"Repeats every {self.policy.get('repeat', 10)} minutes. " if self.policy.get("repeat", 10) else "Shown once. ") +
                              "Closing hides this reminder; Mark as read stops it.")


def run(data, is_active, theme):
    import runtime as rt
    handler = RotatingFileHandler(data / "reminders.log", maxBytes=256000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    try:
        with exclusive(data, "reminders.lock"):
            db = Store(data / "monitor.sqlite")
            try:
                if not awaiting_review(db):
                    return 0
                root = tk.Tk()
                root.withdraw()
                theme(root)
                window = ReviewWindow(root, db, is_active, rt.settings)
                root.after(0, window.refresh)
                root.mainloop()
                return 0
            finally:
                db.db.close()
    except BlockingIOError:
        return 0
    except Exception:
        logging.exception("Could not run review reminders")
        return 1
