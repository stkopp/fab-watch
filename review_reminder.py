"""Notification delivery and the shared live popout queue."""
import logging
import sqlite3
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk
from urllib.parse import urlencode

from authors import own_message
from appearance import ACCENT, BG, EDGE, FONT, MUTED, PANEL, TEXT
from storage import Store, exclusive
from transport import SourceError, validate_url
from notifications import PlainText, send, summary
from notification_policy import policies, due, remember, LABELS, snooze, ask_snooze, popout_layout


def awaiting_review(db):
    return [event for event in db.records(reminders=True) if not own_message(event)]


def rating_text(review):
    rating = review.get("rating")
    if type(rating) not in (float, int) or rating not in range(1, 6):
        return ""
    stars = int(rating)
    return f"{stars}/5   " + "★" * stars + "☆" * (5 - stars)


def card_content(event):
    kind = event["kind"]
    if kind == "new_review":
        review = event.get("review") or {}
        return (event.get("product"), review.get("authorDisplayName"), review.get("createdAt"),
                review.get("title"), review.get("content"), rating_text(review))
    if kind == "new_comment":
        parser = PlainText()
        parser.feed(event.get("content_html") or "")
        return (event.get("product"), event.get("author"), event.get("created_at"),
                None, " ".join(parser.parts), "")
    return (event.get("title") or event.get("product"), None, event.get("created_at"),
            None, summary(event, 2000), "")


class ReviewWindow:
    def __init__(self, root, db, is_active, config_provider=lambda: {}):
        self.root, self.is_active = root, is_active
        self.databases = db if callable(db) else lambda config: (db,)
        self.config_provider = config_provider
        self.shown = {}
        self.timer = None
        self.layout = None
        self.snooze_dialog = False
        root.title("Fab Watch")
        root.minsize(550, 320)
        root.geometry("640x490")
        root.protocol("WM_DELETE_WINDOW", self.keep_open)
        root.attributes("-topmost", True)
        frame = tk.Frame(root, bg=BG, padx=18, pady=16)
        frame.pack(fill="both", expand=True)
        self.heading = tk.Label(frame, bg=BG, fg=TEXT, font=(FONT, 17, "bold"), anchor="w")
        self.heading.pack(fill="x", pady=(0, 10))
        footer = tk.Label(frame, text="Closing this window leaves the items unread.",
                          bg=BG, fg=MUTED, font=(FONT, 9), anchor="w")
        footer.pack(side="bottom", fill="x", pady=(10, 0))
        self.status = tk.Label(frame, bg=BG, fg=ACCENT, font=(FONT, 9), anchor="w")
        self.status.pack(side="bottom", fill="x")
        viewport = tk.Frame(frame, bg=BG)
        viewport.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(viewport, bg=BG, highlightthickness=0, takefocus=True)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.cards = tk.Frame(self.canvas, bg=BG)
        layer = self.canvas.create_window(0, 0, window=self.cards, anchor="nw")
        self.cards.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(layer, width=event.width))
        root.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(-int(event.delta / 120), "units"))
        self.canvas.bind("<Prior>", lambda _: self.canvas.yview_scroll(-1, "pages"))
        self.canvas.bind("<Next>", lambda _: self.canvas.yview_scroll(1, "pages"))

    def keep_open(self):
        clock = time.time()
        prefs = policies(self.config_provider())
        try:
            for (db, _), event in self.shown.items():
                policy = prefs[event["kind"]]
                if policy["mode"] == "popout" and due(db, event, policy, clock):
                    remember(db, event, policy, clock)
        except sqlite3.Error:
            logging.exception("Could not save reminder dismissal")
        self.shown.clear()
        self.root.withdraw()
        self.tick_soon()

    def tick_soon(self):
        if self.timer is not None:
            self.root.after_cancel(self.timer)
        self.timer = self.root.after_idle(self.refresh)

    def remind_later(self, key):
        if key not in self.shown:
            return
        db, event_id = key

        def apply(minutes):
            snooze(db, event_id, minutes)
            self.tick_soon()

        self.snooze_dialog = True
        try:
            dialog = ask_snooze(self.root, apply)
            self.root.wait_window(dialog)
        finally:
            self.snooze_dialog = False
            self.tick_soon()

    def open_review(self, event):
        try:
            url = event.get("url", "")
            validate_url(url)
            webbrowser.open(url)
        except (SourceError, ValueError, OSError, RuntimeError):
            self.status.configure(text="Could not open the source.")

    def confirm(self, key=None):
        key = key or next(iter(self.shown), None)
        if key not in self.shown:
            return
        db, event_id = key
        try:
            db.confirm_review(event_id)
        except sqlite3.Error:
            logging.exception("Could not save acknowledgement")
            self.status.configure(text="Could not save. Try Mark as read again.")
            return
        self.tick_soon()

    def refresh(self):
        try:
            if not self.is_active():
                self.root.destroy()
                return
            if not self.snooze_dialog:
                self.update_queue()
        except Exception:
            logging.exception("Could not refresh reminders")
        if self.root.winfo_exists():
            self.timer = self.root.after(5000, self.refresh)

    def update_queue(self):
        config = self.config_provider()
        prefs = policies(config)
        layout = popout_layout(config)
        clock = time.time()
        eligible, pending = {}, []
        unread = False
        for db in self.databases(config):
            for event in awaiting_review(db):
                policy = prefs[event["kind"]]
                if policy["mode"] == "none":
                    continue
                unread = True
                if policy["mode"] == "windows":
                    self.deliver_windows(db, event, policy, clock)
                else:
                    key = db, event["event_id"]
                    if (db.meta("snooze:" + key[1], 0) or 0) <= clock:
                        eligible[key] = event
                        if key not in self.shown and due(db, event, policy, clock):
                            pending.append(key)

        if not unread:
            self.root.destroy()
            return

        retained = {key: event for key, event in self.shown.items() if key in eligible}
        if layout == "sequential":
            retained = dict(list(retained.items())[:1])
        pending.sort(key=lambda key: (eligible[key]["detected_at"], key[1]))
        if layout == "sequential":
            pending = [] if retained else pending[:1]
        visible = {**retained, **{key: eligible[key] for key in pending}}
        if tuple(visible) == tuple(self.shown) and layout == self.layout:
            return

        if visible:
            self.render(visible)
            self.root.deiconify()
            if pending:
                self.root.lift()
                self.root.bell()
            for db, event_id in pending:
                event = visible[db, event_id]
                remember(db, event, prefs[event["kind"]], clock)
        else:
            self.root.withdraw()
        self.shown, self.layout = visible, layout

    def deliver_windows(self, db, event, policy, clock):
        key = event["event_id"]
        if not due(db, event, policy, clock) or clock < db.meta("notice_retry:" + key, 0):
            return
        try:
            folder = Path(db.db.execute("PRAGMA database_list").fetchone()[2]).parent
            query = urlencode({"scope": folder.name, "event": key})
            send({"title": "Fab Watch | " + LABELS[event["kind"]],
                  "body": summary(event), "url": event.get("url"),
                  "snooze_url": "fabwatch://snooze?" + query,
                  "read_url": "fabwatch://read?" + query,
                  "tag": key[:16]})
            remember(db, event, policy, clock)
        except Exception:
            logging.exception("Windows notification failed; will retry")
            with db.db:
                db.set_meta("notice_retry:" + key, clock + 300)

    def render(self, events):
        position = self.canvas.yview()[0]
        for widget in self.cards.winfo_children():
            widget.destroy()
        kind = LABELS[next(iter(events.values()))["kind"]]
        heading = f"{len(events)} reminders" if len(events) > 1 else kind
        if all(event.get("test") for event in events.values()):
            heading = "Test · " + heading
        self.root.title("Fab Watch | " + heading)
        self.heading.configure(text=heading)
        self.status.configure(text="")
        for key, event in events.items():
            self.render_card(key, event)
        self.canvas.yview_moveto(position if len(events) > 1 else 0)

    def render_card(self, key, event):
        title, author, stamp, subject, body, rating = card_content(event)
        card = tk.Frame(self.cards, bg=PANEL, padx=14, pady=12, highlightthickness=1, highlightbackground=EDGE)
        card.pack(fill="x", pady=(0, 8))

        def line(text, size, color=TEXT, weight="normal"):
            if text:
                tk.Label(card, text=text, bg=PANEL, fg=color, font=(FONT, size, weight), anchor="w",
                         justify="left", wraplength=475).pack(fill="x", pady=(0, 5))

        line(LABELS[event["kind"]], 9, ACCENT, "bold")
        line(title or LABELS[event["kind"]], 13, weight="bold")
        line(" · ".join(str(part) for part in (author, str(stamp or "")[:10]) if part), 9, MUTED)
        line(rating, 16, "#ffd478", "bold")
        line(subject, 10, weight="bold")
        line(body or "No message text.", 10)
        controls = ttk.Frame(card)
        controls.pack(fill="x", pady=(7, 0))
        if event.get("url") and not event.get("test"):
            ttk.Button(controls, text="Open source", command=lambda: self.open_review(event)).pack(side="left")
        ttk.Button(controls, text="Remind me later", command=lambda: self.remind_later(key)).pack(side="left", padx=5)
        ttk.Button(controls, text="Mark as read", style="Accent.TButton",
                   command=lambda: self.confirm(key)).pack(side="right")


def run(data, is_active, theme):
    import runtime as rt
    try:
        with exclusive(rt.ROOT, "live-reminders.lock") if data is None else exclusive(data, "reminders.lock"):
            databases = {}

            def stores(config):
                paths = set(rt.live_activity_paths(config)) if data is None else {data / "monitor.sqlite"}
                for path in databases.keys() - paths:
                    databases.pop(path).db.close()
                for path in paths - databases.keys():
                    if path.is_file():
                        try:
                            databases[path] = Store(path)
                        except (OSError, sqlite3.Error):
                            logging.exception("Could not open reminder database")
                return tuple(databases.values())

            try:
                if not any(awaiting_review(db) for db in stores(rt.settings())):
                    return 0
                root = tk.Tk()
                root.withdraw()
                theme(root)
                window = ReviewWindow(root, stores, is_active, rt.settings)
                root.after(0, window.refresh)
                root.mainloop()
                return 0
            finally:
                for db in databases.values():
                    db.db.close()
    except BlockingIOError:
        return 0
    except Exception:
        logging.exception("Could not run reminders")
        return 1
