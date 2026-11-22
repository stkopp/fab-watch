import argparse
import hashlib
import json
import logging
import os
import queue
import sqlite3
import struct
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import runtime as rt
import sources
from updates import UpdateUI
from notification_policy import LABELS, policies, snooze, ask_snooze
from notification_settings import open_settings
from appearance import BG, PANEL, EDGE, TEXT, MUTED, ACCENT, FONT, theme
from authors import own_message
from notifications import send, summary
from review_reminder import run as show_reminders
from storage import Store, exclusive, needs_confirmation
from transport import validate_url
from windows_shell import TrayIcon, show_existing

FILTERS = {"All activity": None, "Unread": None, "Reviews": "new_review", "Discussions": "new_comment",
           "Ratings": "ratings_changed"}
KINDS = {"new_review": "Review", "new_comment": "Discussion", "ratings_changed": "Rating",
         "edited_review": "Review edit", "monitor_error": "Source error"}
PAGE_SIZE = 20
FEED_SORT = {
    "Type": "fab_type(value) COLLATE NOCASE",
    "Product": "json_extract(value,'$.product') COLLATE NOCASE",
    "From": "coalesce(json_extract(value,'$.author'),json_extract(value,'$.review.authorDisplayName'),'') COLLATE NOCASE",
    "Date": "julianday(coalesce(json_extract(value,'$.created_at'),json_extract(value,'$.review.createdAt'),created))",
    "Status": "fab_status(value,accepted,silent,resolved) COLLATE NOCASE",
}


def unread(event, accepted, silent, resolved):
    return needs_confirmation(event, accepted, silent, resolved)


def activity_status(event, accepted, silent, resolved):
    if unread(event, accepted, silent, resolved):
        return "Unread"
    if event.get("confirmed_by_user_at"):
        return "Read"
    if own_message(event):
        return "Seller"
    return "History" if silent else "Notified" if accepted else "New"


def label(parent, text="", size=10, color=TEXT, weight="normal", **options):
    return tk.Label(parent, text=text, bg=options.pop("bg", BG), fg=color,
                    font=(FONT, size, weight), anchor="w", **options)


def format_time(value, with_time=True):
    if not value:
        return "—"
    try:
        value = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value.astimezone().strftime("%d %b %Y, %H:%M" if with_time else "%d %b %Y")
    except (ValueError, TypeError):
        return "—"


class App:
    def __init__(self, root):
        self.root = root
        self.config = rt.settings()
        self.pending = False
        self.results = queue.Queue()
        self.events, self.products = {}, {}
        self.selected = None
        self.snapshot = None
        self.page = 0
        self.feed_sort = ("Date", True)
        self.product_sort = (None, False)
        self.tray = None
        self.engine_snapshot = None
        self.engine_events = {}
        self.seller_unread = self.engine_unread = 0
        self.displayed_unread = None
        self.root.title("Fab Watch")
        self.root.geometry("1050x745")
        self.root.minsize(820, 625)
        theme(root)
        self.updates = UpdateUI(root, rt.VERSION, rt.ROOT, self.install_setup, self.update)
        self.build()
        self.refresh_view(force=True)
        self.root.after(250, self.poll)

    def build(self):
        nav = tk.Frame(self.root, bg=PANEL, padx=22, pady=12)
        nav.pack(fill="x")
        tk.Label(nav, image=self.root.fab_icon, bg=PANEL, borderwidth=0).pack(side="left", padx=(0, 10))
        brand = tk.Frame(nav, bg=PANEL)
        brand.pack(side="left")
        label(brand, "Fab Watch", 16, TEXT, "bold", bg=PANEL).pack(anchor="w")
        self.updates.badge = label(nav, f"v{rt.VERSION}", 9, MUTED, bg=PANEL)
        self.updates.badge.configure(cursor="hand2")
        self.updates.badge.bind("<Button-1>", lambda _: self.updates.open())
        self.updates.badge.pack(side="right")
        self.refresh_button = ttk.Button(nav, text="Check now", style="Accent.TButton", command=self.refresh)
        self.refresh_button.pack(side="right", padx=(8, 14))
        self.unread_button = ttk.Button(nav, text="Unread · 0", command=self.show_unread)
        self.unread_button.pack(side="right")
        status = tk.Frame(self.root, bg=PANEL, padx=18, pady=8)
        status.pack(side="bottom", fill="x")
        self.status = label(status, "Ready", color=MUTED, bg=PANEL)
        self.status.pack(side="left")
        self.next = label(status, "Next check —", color=ACCENT, bg=PANEL)
        self.next.pack(side="right")
        body = tk.Frame(self.root, bg=BG, padx=24, pady=18)
        body.pack(fill="both", expand=True)
        workspace = tk.Frame(body, bg=BG)
        workspace.pack(fill="x", pady=(0, 10))
        intro = tk.Frame(workspace, bg=BG)
        intro.pack(side="left", fill="x", expand=True)
        self.seller_title = label(intro, "Your Fab activity", 22, weight="bold")
        self.seller_title.pack(fill="x")
        self.subtitle = label(intro, "Add your seller link to start tracking reviews and comments.", color=MUTED)
        self.subtitle.pack(fill="x", pady=(3, 0))
        self.add_menu(workspace, "Tools", (
            ("Check details", self.check_details),
            ("Test review", self.test_review),
            ("Test comment", self.test_comment),
            ("Test engine alert", self.test_engine),
            ("App updates…", self.updates.open),
        )).pack(side="right", padx=(6, 0))
        self.add_menu(workspace, "Settings", (
            ("Seller and schedule", self.toggle_seller_settings),
            ("Notifications…", self.notification_settings),
        )).pack(side="right")
        settings = tk.Frame(body, bg=PANEL, padx=13, pady=10, highlightbackground=EDGE, highlightthickness=1)
        self.seller_settings = settings
        if not self.config.get("seller"):
            settings.pack(fill="x", pady=(0, 12))
        label(settings, "Seller URL", color=MUTED, bg=PANEL).grid(row=0, column=0, sticky="w")
        self.url = tk.StringVar()
        url_row = tk.Frame(settings, bg=PANEL)
        url_row.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.url_entry = ttk.Entry(url_row, textvariable=self.url)
        self.url_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(url_row, text="Paste", command=self.paste_url, width=6).pack(side="left", padx=(5, 0))
        self.url_entry.bind("<Return>", lambda _: self.connect())
        self.url_entry.bind("<Control-KeyPress>", self.url_shortcut)
        self.url_entry.bind("<<Paste>>", lambda _: self.paste_url())
        self.url_menu = tk.Menu(self.url_entry, tearoff=False)
        for name, action in (("Paste", self.paste_url), ("Copy", lambda: self.url_entry.event_generate("<<Copy>>")),
                             ("Cut", lambda: self.url_entry.event_generate("<<Cut>>")),
                             ("Select all", self.select_url)):
            self.url_menu.add_command(label=name, command=action)
        self.url_entry.bind("<Button-3>", self.url_context_menu)
        self.connect_button = ttk.Button(settings, text="Connect", command=self.connect)
        self.connect_button.grid(row=1, column=1, padx=(0, 14))
        label(settings, "Check every", color=MUTED, bg=PANEL).grid(row=0, column=2, sticky="w")
        self.interval = ttk.Combobox(settings, values=[f"{n} min" for n in rt.INTERVALS], width=9, state="readonly")
        self.interval.set(f'{self.config["interval"]} min')
        self.interval.grid(row=1, column=2, padx=(0, 14))
        self.interval.bind("<<ComboboxSelected>>", self.change_interval)
        settings.columnconfigure(0, weight=1)
        self.auto_check = tk.BooleanVar(value=self.config.get("auto_check_after_launch", True))
        self.auto_check_button = ttk.Checkbutton(settings, text="Auto check after PC launch",
                                                 variable=self.auto_check, command=self.change_auto_check)
        self.auto_check_button.grid(row=2, column=0, columnspan=4, sticky="w", pady=(9, 0))

        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill="both", expand=True)
        feed = tk.Frame(self.tabs, bg=BG, padx=10, pady=10)
        catalog = tk.Frame(self.tabs, bg=BG, padx=10, pady=10)
        self.tabs.add(feed, text="  Activity  ")
        self.tabs.add(catalog, text="  Products  ")
        engine = tk.Frame(self.tabs, bg=BG, padx=10, pady=10)
        self.tabs.add(engine, text="  Unreal Engine  ")
        engine_bar = tk.Frame(engine, bg=BG)
        engine_bar.pack(fill="x", pady=(0, 8))
        self.engine_filter = ttk.Button(engine_bar, text="Show unread", command=self.toggle_engine_filter)
        self.engine_filter.pack(side="right")
        self.engine_status = label(engine_bar, "Waiting for the first engine check", color=MUTED)
        self.engine_status.pack(side="left", fill="x", expand=True)
        controls = tk.Frame(engine, bg=BG)
        controls.pack(side="bottom", fill="x")
        ttk.Button(controls, text="Check engine now", command=self.check_engine).pack(side="left")
        self.engine_open = ttk.Button(controls, text="Open source", command=self.open_engine, state="disabled")
        self.engine_open.pack(side="right", padx=6)
        self.engine_read = ttk.Button(controls, text="Mark as read", command=self.mark_engine_read, state="disabled")
        self.engine_read.pack(side="right")
        self.engine_later = ttk.Button(controls, text="Remind me later", command=self.snooze_engine, state="disabled")
        self.engine_later.pack(side="right", padx=6)
        self.engine_detail = label(engine, "Select an announcement", color=MUTED, wraplength=880)
        self.engine_detail.pack(side="bottom", fill="x", pady=8)
        self.engine_table = self.table(engine, (("Type", 130), ("Version", 100), ("Date", 160), ("Status", 120)), 7)
        self.engine_table.column("Type", stretch=True)
        self.engine_table.bind("<<TreeviewSelect>>", self.select_engine)
        filters = tk.Frame(feed, bg=BG)
        filters.pack(fill="x", pady=(0, 8))
        label(filters, "Show", color=MUTED).pack(side="left", padx=(0, 8))
        self.filter = ttk.Combobox(filters, values=list(FILTERS), state="readonly", width=15)
        self.filter.set("All activity")
        self.filter.pack(side="left")
        self.filter.bind("<<ComboboxSelected>>", self.change_filter)
        self.paging = tk.Frame(filters, bg=BG)
        self.older_button = ttk.Button(self.paging, text="Next →", command=lambda: self.change_page(1))
        self.older_button.pack(side="right")
        self.newer_button = ttk.Button(self.paging, text="← Previous", command=lambda: self.change_page(-1))
        self.newer_button.pack(side="right", padx=5)
        self.page_label = label(filters, color=MUTED)
        self.page_label.pack(side="right", padx=5)
        commands = tk.Frame(feed, bg=BG)
        commands.pack(side="bottom", fill="x")
        self.detail = tk.Text(feed, height=3, wrap="word", relief="flat", bg=PANEL, fg=TEXT,
                              insertbackground=TEXT, padx=11, pady=7, font=(FONT, 10), state="disabled")
        self.detail.pack(side="bottom", fill="x", pady=(8, 6))
        self.read_button = ttk.Button(commands, text="Mark as read", command=self.mark_read, state="disabled")
        self.read_button.pack(side="right")
        self.later_button = ttk.Button(commands, text="Remind me later", command=self.snooze_selected, state="disabled")
        self.later_button.pack(side="right", padx=6)
        self.open_button = ttk.Button(commands, text="Open source", command=self.open_selected, state="disabled")
        self.open_button.pack(side="right", padx=8)
        self.feed = self.table(feed, (("Type", 105), ("Product", 250), ("From", 140), ("Date", 120), ("Status", 110)), 4)
        self.set_sort_headers(self.feed, self.feed_sort, self.sort_feed)
        self.feed.bind("<<TreeviewSelect>>", self.select)
        self.feed.bind("<Double-Button-1>", lambda _: self.open_selected())
        self.catalog = self.table(catalog, (("Product", 380), ("Type", 100), ("Ratings", 90), ("Discussion", 115)), 12)
        self.set_sort_headers(self.catalog, self.product_sort, self.sort_products)
        self.catalog.bind("<Double-Button-1>", self.open_product)
        ttk.Button(catalog, text="Open selected product", command=self.open_product).pack(anchor="e", pady=(8, 0))

        self.tabs.enable_traversal()
        self.root.bind("<F5>", lambda _: self.refresh())
        self.root.bind("<Control-u>", lambda _: self.show_unread())

    @staticmethod
    def add_menu(parent, title, actions):
        button = ttk.Menubutton(parent, text=title)
        menu = tk.Menu(button, tearoff=False, bg=PANEL, fg=TEXT, activebackground=EDGE, activeforeground=TEXT)
        for name, action in actions:
            menu.add_command(label=name, command=action)
        button.configure(menu=menu)
        return button

    def toggle_seller_settings(self):
        if self.seller_settings.winfo_manager():
            self.seller_settings.pack_forget()
        else:
            self.seller_settings.pack(fill="x", pady=(0, 12), before=self.tabs)
            self.url_entry.focus_set()

    def test_engine(self):
        self.run_job("Creating a test engine alert…", lambda: rt.create_test_review("engine_release"))

    def show_unread(self):
        self.show()
        self.filter.set("Unread")
        self.change_filter()
        self.tabs.select(2 if self.engine_unread and not self.seller_unread else 0)

    def toggle_engine_filter(self):
        self.filter.set("All activity" if self.filter.get() == "Unread" else "Unread")
        self.change_filter()

    def update_unread(self):
        total = self.seller_unread + self.engine_unread
        counts = self.seller_unread, self.engine_unread
        if counts != self.displayed_unread:
            self.displayed_unread = counts
            self.unread_button.configure(text=f"Unread · {total}")
            self.tabs.tab(0, text=f"  Activity ({self.seller_unread})  " if self.seller_unread else "  Activity  ")
            self.tabs.tab(2, text=f"  Unreal Engine ({self.engine_unread})  " if self.engine_unread else "  Unreal Engine  ")
        if self.tray:
            self.tray.set_unread(total)

    def notification_settings(self):
        if self.pending:
            return
        def save(values):
            config = {**self.config, **values}
            def apply():
                rt.configure_engine(config)
                rt.save_settings(config)
                for task in (rt.REVIEW_TASK, rt.ENGINE_REMINDER_TASK, rt.TEST_REVIEW_TASK):
                    rt.scheduler("/Run", "/TN", task, check=False)
            self.run_job("Saving notification settings…", apply)
        open_settings(self.root, self.config, save)

    def check_engine(self):
        config = self.config.copy()
        self.run_job("Checking Unreal Engine announcements…", lambda: rt.check_engine(config, force=True))

    def refresh_engine(self):
        self.engine_filter.configure(text="Show all" if self.filter.get() == "Unread" else "Show unread")
        path = rt.ROOT / "engine" / "monitor.sqlite"
        if not path.exists():
            self.engine_unread = 0
            return
        try:
            db = Store(path)
            try:
                events = sorted(db.records(), key=lambda e: e.get("created_at") or e["detected_at"], reverse=True)
                success = db.meta("engine_last_success")
                error = db.meta("engine_error")
                prefs = policies(self.config)
                times = [datetime.fromtimestamp((db.meta(k) or {}).get("checked", 0) + p["check"] * 60, timezone.utc)
                         for k, p in prefs.items() if k.startswith("engine_") and p["check"]]
            finally:
                db.db.close()
            next_time = min(times) if times else None
            text = ("Check failed: " + error if error else "Last check: " + format_time(success))
            text += "  ·  Next: " + (format_time(next_time) if next_time and next_time > datetime.now(timezone.utc) else "Due / waiting for worker" if times else "Disabled")
            self.engine_status.configure(text=text)
            pending = [e for e in events if unread(e, e["acknowledged_at"], e["silent"], e["resolved_at"])
                       and not e.get("test")]
            self.engine_unread = len(pending)
            if self.filter.get() == "Unread":
                events = pending
            token = json.dumps(events, sort_keys=True)
            if token == self.engine_snapshot:
                return
            self.engine_snapshot = token
            selected = self.engine_table.selection()
            self.engine_table.delete(*self.engine_table.get_children())
            self.engine_events = {e["event_id"]: e for e in events}
            for e in events:
                state = activity_status(e, e["acknowledged_at"], e["silent"], e["resolved_at"])
                self.engine_table.insert("", "end", iid=e["event_id"], values=(LABELS.get(e["kind"], e["kind"]),
                    e.get("version", "—"), format_time(e.get("created_at") or e["detected_at"], False), state))
            if selected and selected[0] in self.engine_events:
                self.engine_table.selection_set(selected[0])
            self.select_engine()
        except Exception:
            logging.exception("Engine activity could not be read")
            self.engine_status.configure(text="Engine activity unavailable; see logs")

    def select_engine(self, _=None):
        ids = self.engine_table.selection()
        event = self.engine_events.get(ids[0]) if ids else None
        self.engine_detail.configure(text=summary(event, 1500) if event else "Select an announcement")
        self.engine_open.configure(state="normal" if event and event.get("url") else "disabled")
        state = "normal" if event and needs_confirmation(event,
            event["acknowledged_at"], event["silent"], event["resolved_at"]) else "disabled"
        self.engine_read.configure(state=state)
        self.engine_later.configure(state=state)

    def open_engine(self):
        ids = self.engine_table.selection()
        if ids:
            self.open_url(self.engine_events[ids[0]].get("url"))

    def mark_engine_read(self):
        ids = self.engine_table.selection()
        if ids:
            db = Store(rt.ROOT / "engine" / "monitor.sqlite")
            try:
                db.confirm_review(ids[0])
            finally:
                db.db.close()
            self.refresh_view()

    def snooze_selected(self):
        if self.selected and self.selected["unread"]:
            self.snooze_event(rt.profile(self.config["seller"]), self.selected["event_id"])

    def snooze_engine(self):
        ids = self.engine_table.selection()
        if ids:
            self.snooze_event(rt.ROOT / "engine", ids[0])

    def snooze_event(self, folder, event_id):
        def apply(minutes):
            db = Store(folder / "monitor.sqlite")
            try:
                snooze(db, event_id, minutes)
            finally:
                db.db.close()
        ask_snooze(self.root, apply)

    def select_url(self):
        self.url_entry.selection_range(0, "end")
        self.url_entry.icursor("end")
        return "break"

    def paste_url(self):
        try:
            value = self.root.clipboard_get().strip()
        except tk.TclError:
            self.status.configure(text="Clipboard does not contain text", fg=MUTED)
            return "break"
        if self.url_entry.selection_present():
            self.url_entry.delete("sel.first", "sel.last")
        self.url_entry.insert("insert", value)
        self.url_entry.focus_set()
        return "break"

    def url_shortcut(self, event):
        # Windows virtual-key codes remain stable with Russian and other layouts.
        if event.keycode == 86:
            return self.paste_url()
        if event.keycode == 65:
            return self.select_url()
        if event.keycode in (67, 88):
            self.url_entry.event_generate("<<Copy>>" if event.keycode == 67 else "<<Cut>>")
            return "break"

    def url_context_menu(self, event):
        self.url_entry.focus_set()
        try:
            self.url_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.url_menu.grab_release()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def enable_tray(self, hidden=False):
        self.tray = TrayIcon()
        self.update_unread()
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
        if hidden and self.tray.ready:
            self.root.withdraw()
        self.root.after(150, self.poll_tray)

    def close_window(self):
        if self.pending:
            self.status.configure(text="Finishing the current check…", fg=ACCENT)
        if self.tray and self.tray.ready:
            self.root.withdraw()
        elif not self.pending:
            self.root.destroy()

    def poll_tray(self):
        while not self.tray.events.empty():
            action = self.tray.events.get_nowait()
            if action == "show":
                self.show()
            elif action == "unread":
                self.show_unread()
            elif action == "refresh":
                self.show()
                self.refresh()
            elif action == "exit":
                if self.pending:
                    self.show()
                    self.status.configure(text="Wait for the current check to finish before exiting.", fg=ACCENT)
                else:
                    self.root.destroy()
                    return
        self.root.after(150, self.poll_tray)

    def table(self, parent, columns, rows):
        panel = tk.Frame(parent, bg=BG)
        panel.pack(fill="both", expand=True)
        names = tuple(name for name, _ in columns)
        tree = ttk.Treeview(panel, columns=names, show="headings", height=rows, selectmode="browse")
        for name, width in columns:
            tree.heading(name, text=name)
            tree.column(name, width=width, minwidth=70, stretch=name == "Product")
        scroll = ttk.Scrollbar(panel, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def run_job(self, message, job):
        if self.pending:
            return
        self.pending = True
        self.status.configure(text=message, fg=ACCENT)
        for button in (self.connect_button, self.refresh_button, self.interval, self.auto_check_button):
            button.state(["disabled"])
        def worker():
            try:
                with exclusive(rt.ROOT, "job.lock"):
                    result = job()
                self.results.put((result, None))
            except BlockingIOError:
                self.results.put((None, "A background check is already running. Try again shortly."))
            except Exception as exc:
                logging.exception("Fab Watch action failed")
                self.results.put((None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def connect(self):
        value = self.url.get()
        try:
            sources.seller_name(value)
        except ValueError as exc:
            messagebox.showerror("Seller URL", str(exc), parent=self.root)
            self.url_entry.focus_set()
            return
        config = self.config.copy()
        def connect_seller():
            seller = sources.resolve_seller(value)
            rt.initialize(seller)
            config["seller"] = seller
            rt.configure_schedule(config, reset=True)
            return rt.check(config)
        self.run_job("Connecting to Fab…", connect_seller)

    def refresh(self):
        config = self.config.copy()
        if not config.get("seller"):
            if not self.seller_settings.winfo_manager():
                self.toggle_seller_settings()
            self.connect()
            return
        self.run_job("Refreshing catalog and activity…", lambda: rt.check(config))

    def change_interval(self, _=None):
        config = {**self.config, "interval": int(self.interval.get().split()[0])}
        def apply():
            if config.get("seller"):
                rt.configure_schedule(config, reset=True)
            else:
                rt.save_settings(config)
        self.run_job("Saving refresh interval…", apply)

    def change_filter(self, _=None):
        self.page = 0
        self.refresh_view(force=True)

    def change_auto_check(self):
        config = {**self.config, "auto_check_after_launch": self.auto_check.get()}
        def apply():
            if config.get("seller"):
                rt.configure_schedule(config)
            else:
                rt.save_settings(config)
            rt.configure_engine(config)
        self.run_job("Saving startup check preference…", apply)

    def change_page(self, delta):
        self.page = max(0, self.page + delta)
        self.refresh_view(force=True)
        self.feed.yview_moveto(0)

    @staticmethod
    def set_sort_headers(tree, sort, callback):
        active, descending = sort
        for name in tree["columns"]:
            arrow = ("  ↓" if descending else "  ↑") if name == active else ""
            tree.heading(name, text=name + arrow, command=lambda col=name: callback(col))

    def sort_feed(self, column):
        active, descending = self.feed_sort
        self.feed_sort = (column, not descending if column == active else column == "Date")
        self.set_sort_headers(self.feed, self.feed_sort, self.sort_feed)
        self.page = 0
        self.refresh_view(force=True)
        self.feed.yview_moveto(0)

    def sort_products(self, column):
        active, descending = self.product_sort
        self.product_sort = (column, not descending if column == active else column == "Ratings")
        self.set_sort_headers(self.catalog, self.product_sort, self.sort_products)
        self.refresh_view(force=True)
        self.catalog.yview_moveto(0)

    def test_review(self):
        self.run_job("Creating a test review…", rt.create_test_review)

    def test_comment(self):
        self.run_job("Creating a test comment…", lambda: rt.create_test_review("new_comment"))

    def poll(self):
        try:
            _, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.pending = False
            new_config = rt.settings()
            if new_config.get("seller") != self.config.get("seller"):
                self.page = 0
                self.seller_unread = 0
                if new_config.get("seller"):
                    self.seller_settings.pack_forget()
            self.config = new_config
            self.interval.set(f'{self.config["interval"]} min')
            self.auto_check.set(self.config.get("auto_check_after_launch", True))
            for button in (self.connect_button, self.refresh_button, self.interval, self.auto_check_button):
                button.state(["!disabled"])
            self.refresh_view(force=True)
            if error:
                messagebox.showerror("Fab Watch", error, parent=self.root)
        self.refresh_view()
        self.root.after(1800 if not self.pending else 300, self.poll)

    def refresh_view(self, force=False):
        self.refresh_engine()
        seller = self.config.get("seller")
        next_run = rt.next_check(self.config)
        self.next.configure(text=f"Next check  {format_time(next_run)}" if seller else "Next update  —")
        if not seller:
            self.seller_unread = 0
            self.update_unread()
            self.detail_text("Paste your Fab seller link and select Connect.")
            self.older_button.state(["disabled"])
            self.newer_button.state(["disabled"])
            return
        self.seller_title.configure(text=seller["name"])
        try:
            path = rt.profile(seller) / "monitor.sqlite"
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
                conn.row_factory = sqlite3.Row
                self.read_snapshot(conn, force)
        except Exception:
            logging.exception("Could not read seller activity")
            self.seller_unread = 0
            if not self.pending:
                self.status.configure(text="Could not load activity. See the log for details.", fg="#ffacac")
        self.update_unread()

    def read_snapshot(self, conn, force):
        meta = {key: json.loads(value) for key, value in conn.execute("SELECT key,value FROM meta")}
        report = meta.get("last_report") or {}
        count, latest, read, confirmed = conn.execute(
            "SELECT count(*),max(created),max(accepted),max(json_extract(value,'$.confirmed_by_user_at')) FROM events").fetchone()
        conn.create_function("fab_unread", 4, lambda value, accepted, silent, resolved:
                             unread(json.loads(value), accepted, silent, resolved))
        unread_filter = ("silent=0 AND resolved IS NULL AND fab_unread(value,accepted,silent,resolved) "
                         "AND COALESCE(json_extract(value,'$.test'),0)=0")
        self.seller_unread = conn.execute(f"SELECT count(*) FROM events WHERE {unread_filter}").fetchone()[0]
        token = (self.config["seller"]["id"], meta.get("last_run_at"), count, latest, read, confirmed,
                 self.seller_unread)
        checking = meta.get("checking")
        active = checking and (datetime.now(timezone.utc) - datetime.fromisoformat(checking)).total_seconds() < 1500
        if not self.pending:
            errors = report.get("errors", [])
            status = ("Refreshing catalog and activity…" if active else
                      f"{len(errors)} source issues · Last check {format_time(report.get('at'))}" if errors else
                      f"Last check  {format_time(report.get('at'))}" if report else "Waiting for first check")
            self.status.configure(text=status, fg="#ffbf8c" if errors and not active else MUTED)
        if not force and token == self.snapshot:
            return
        self.snapshot = token
        previous = self.feed.selection()
        self.feed.delete(*self.feed.get_children())
        self.catalog.delete(*self.catalog.get_children())
        self.events.clear()
        self.products.clear()
        filter_kind = FILTERS[self.filter.get()]
        where = ("WHERE json_extract(value,'$.kind') IN "
                            "('new_review','new_comment','ratings_changed','edited_review','monitor_error') "
                            "AND COALESCE(json_extract(value,'$.test'),0)=0 "
                            "AND (? IS NULL OR json_extract(value,'$.kind')=?)")
        if self.filter.get() == "Unread":
            where += " AND " + unread_filter
        size = conn.execute(f"SELECT count(*) FROM events {where}", (filter_kind, filter_kind)).fetchone()[0]
        last_page = max(0, (size - 1) // PAGE_SIZE)
        self.page = min(self.page, last_page)
        first = self.page * PAGE_SIZE + 1
        self.page_label.configure(text=f"{first}–{min(first + PAGE_SIZE - 1, size)} of {size}" if size else "0 events")
        if last_page:
            self.paging.pack(side="right", before=self.page_label)
        else:
            self.paging.pack_forget()
        self.newer_button.state(["!disabled" if self.page else "disabled"])
        self.older_button.state(["!disabled" if self.page < last_page else "disabled"])
        conn.create_function("fab_type", 1, lambda value: KINDS[json.loads(value)["kind"]])
        conn.create_function("fab_status", 4,
                             lambda value, accepted, silent, resolved: activity_status(json.loads(value), accepted, silent, resolved))
        column, descending = self.feed_sort
        order = FEED_SORT[column]
        direction = "DESC" if descending else "ASC"
        rows = conn.execute(f"SELECT * FROM events {where} ORDER BY {order} {direction},created DESC,id DESC LIMIT ? OFFSET ?",
                            (filter_kind, filter_kind, PAGE_SIZE, self.page * PAGE_SIZE))
        for row in rows:
            event = json.loads(row["value"])
            event["event_id"], event["accepted"] = row["id"], row["accepted"]
            event["unread"] = unread(event, row["accepted"], row["silent"], row["resolved"])
            review = event.get("review") or {}
            state = activity_status(event, row["accepted"], row["silent"], row["resolved"])
            self.events[row["id"]] = event
            self.feed.insert("", "end", iid=row["id"], values=(KINDS[event["kind"]], event.get("product", "—"),
                event.get("author") or review.get("authorDisplayName") or "—",
                format_time(event.get("created_at") or review.get("createdAt") or row["created"], False), state))
        if previous and previous[0] in self.events:
            self.feed.selection_set(previous[0])
            self.select()
        else:
            self.selected = None
            self.select()
        active_ids = meta.get("active_product_ids")
        products = {row[0]: json.loads(row[1]) for row in conn.execute("SELECT id,value FROM products")}
        source_data = {(row[0], row[1]): json.loads(row[2]) for row in conn.execute(
            "SELECT product,stage,value FROM sources WHERE stage IN ('detail','forum_link')")}
        product_rows = []
        for uid in (active_ids if active_ids is not None else products):
            p = products.get(uid)
            if not p:
                continue
            self.products[uid] = p
            ratings = (source_data.get((uid, "detail"), {}).get("ratings") or {}).get("total", "—")
            product_rows.append((uid, (p["title"], "Bundle" if p["kind"] == "bundles" else "Listing",
                ratings, "Available" if (uid, "forum_link") in source_data else "—")))
        column, descending = self.product_sort
        if column:
            index = list(self.catalog["columns"]).index(column)
            if column == "Ratings":
                product_rows.sort(key=lambda row: row[1][index] if isinstance(row[1][index], int) else -1, reverse=descending)
            else:
                product_rows.sort(key=lambda row: row[1][index].casefold(), reverse=descending)
        for uid, values in product_rows:
            self.catalog.insert("", "end", iid=uid, values=values)
        discussions = sum((uid, "forum_link") in source_data for uid in self.products)
        self.subtitle.configure(text=f"{len(self.products)} products  ·  {discussions} discussions")

    def detail_text(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def select(self, _=None):
        ids = self.feed.selection()
        self.selected = self.events.get(ids[0]) if ids else None
        self.read_button.configure(state="normal" if self.selected and self.selected["unread"] else "disabled")
        self.later_button.configure(state="normal" if self.selected and self.selected["unread"] else "disabled")
        self.open_button.configure(state="normal" if self.selected else "disabled")
        if self.selected:
            self.detail_text(summary(self.selected, limit=12000))
        else:
            self.detail_text("Select an event to see its details." if self.events else "No activity in this view yet.")

    def mark_read(self):
        if not self.selected or not self.selected["unread"]:
            return
        db = Store(rt.profile(self.config["seller"]) / "monitor.sqlite")
        try:
            db.confirm_review(self.selected["event_id"])
        except Exception as exc:
            messagebox.showerror("Fab Watch", str(exc), parent=self.root)
        finally:
            db.db.close()
        self.refresh_view(force=True)

    @staticmethod
    def open_url(url):
        if url:
            validate_url(url)
            webbrowser.open(url)

    def open_selected(self):
        if self.selected:
            self.open_url(self.selected.get("url"))

    def open_product(self, _=None):
        ids = self.catalog.selection()
        if ids:
            self.open_url(self.products[ids[0]]["url"])

    def check_details(self):
        seller = self.config.get("seller")
        if not seller:
            messagebox.showinfo("Check details", "Connect a seller to start monitoring.", parent=self.root)
            return
        db = Store(rt.profile(seller) / "monitor.sqlite")
        try:
            report = db.meta("last_report") or {}
        finally:
            db.db.close()
        errors = report.get("errors", [])
        text = "\n".join(f'{e["stage"]}: {e["message"]}' for e in errors[:12])
        messagebox.showinfo("Check details", text or "No source errors in the last completed check.", parent=self.root)

    def update(self):
        selected = filedialog.askopenfilename(title="Choose a Fab Watch setup file",
            filetypes=[("Fab Watch Setup", "FabWatchSetup*.exe")], parent=self.root)
        if selected:
            self.install_setup(Path(selected))

    def install_setup(self, selected):
        if self.pending:
            messagebox.showinfo("Fab Watch", "Wait for the current check to finish before installing an update.", parent=self.root)
            return
        try:
            self.validate_setup(Path(selected))
            if messagebox.askokcancel("Install update", f"Install this Fab Watch update? Your saved data will be kept.\n\n{selected}",
                                      parent=self.root):
                subprocess.Popen([str(selected)], close_fds=True)
                self.root.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Fab Watch", str(exc), parent=self.root)

    @staticmethod
    def validate_setup(path):
        with path.open("rb") as stream:
            size = path.stat().st_size
            if size < 48 or stream.read(2) != b"MZ":
                raise ValueError("Choose a valid Fab Watch Setup file.")
            stream.seek(-48, 2)
            payload_size, digest, magic = struct.unpack("<q32s8s", stream.read(48))
            if magic != b"FABWZIP1" or not 0 < payload_size <= min(128 << 20, size - 48):
                raise ValueError("Choose a valid Fab Watch Setup file.")
            stream.seek(size - 48 - payload_size)
            if hashlib.sha256(stream.read(payload_size)).digest() != digest:
                raise ValueError("The update package is incomplete or damaged.")


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    for name in ("scheduled", "reminder", "test-reminder", "configure", "unregister", "check-now", "tray", "engine-check", "engine-reminder"):
        mode.add_argument(f"--{name}", action="store_true")
    mode.add_argument("--notification-action")
    opts = parser.parse_args()
    rt.setup_logging()
    config = rt.settings()
    if opts.notification_action:
        rt.notification_action(opts.notification_action)
        return 0
    if opts.unregister:
        for task in (rt.CHECK_TASK, rt.REVIEW_TASK, rt.TEST_REVIEW_TASK, rt.ENGINE_TASK, rt.ENGINE_REMINDER_TASK):
            rt.scheduler("/Delete", "/TN", task, "/F", check=False)
        return 0
    if opts.configure:
        config["notifications"] = policies(config)
        rt.configure_engine(config)
        if (rt.ROOT / "test-reviews" / "monitor.sqlite").exists():
            rt.register_task(rt.TEST_REVIEW_TASK, "--test-reminder", 10,
                             datetime.now(timezone.utc))
        else:
            rt.scheduler("/Delete", "/TN", rt.TEST_REVIEW_TASK, "/F", check=False)
        if config.get("seller"):
            rt.configure_schedule(config)
        else:
            rt.save_settings(config)
            for task in (rt.CHECK_TASK, rt.REVIEW_TASK):
                rt.scheduler("/Delete", "/TN", task, "/F", check=False)
        return 0
    if opts.engine_check:
        try:
            with exclusive(rt.ROOT, "job.lock"):
                rt.check_engine(rt.settings())
        except BlockingIOError:
            pass
        return 0
    if opts.engine_reminder or opts.reminder:
        return show_reminders(None, lambda: True, theme)
    if opts.test_reminder:
        folder = rt.ROOT / "test-reviews"
        if not (folder / "monitor.sqlite").exists():
            return 0
        return show_reminders(folder, lambda: True, theme)
    if opts.scheduled or opts.check_now:
        if config.get("seller"):
            try:
                with exclusive(rt.ROOT, "job.lock"):
                    config = rt.settings()
                    if not config.get("seller"):
                        return 0
                    report = rt.check(config, scheduled=opts.scheduled)
                return 2 if report and report["errors"] else 0
            except BlockingIOError:
                return 0
        return 0
    try:
        with exclusive(rt.ROOT, "window.lock"):
            root = tk.Tk()
            app = App(root)
            app.enable_tray(hidden=opts.tray)
            app.updates.start()
            try:
                root.mainloop()
            finally:
                app.tray.close()
    except BlockingIOError:
        if not opts.tray:
            show_existing()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.exception("Fab Watch failed")
        if not any(flag in sys.argv for flag in ("--scheduled", "--reminder", "--test-reminder", "--configure", "--unregister", "--check-now", "--engine-check", "--engine-reminder")):
            messagebox.showerror("Fab Watch could not start", str(exc))
        raise SystemExit(1)
