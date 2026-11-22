import os
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import struct
import sys
from tempfile import TemporaryDirectory
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import runtime as rt
import sources
import collector
from storage import Store, encode
from review_reminder import awaiting_review, ReviewWindow
from windows_shell import TrayIcon, show_existing


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root_patch = patch.object(rt, "ROOT", Path(self.tmp.name))
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.tmp.cleanup()

    def test_clean_profile_and_corrupt_settings_preserved(self):
        self.assertEqual(rt.settings(), {"interval": 60, "auto_check_after_launch": True})
        path = rt.ROOT / "settings.json"
        path.write_text('{invalid')
        with self.assertRaises(ValueError):
            rt.settings()
        self.assertEqual(path.read_text(), '{invalid')

    def test_invalid_interval_rejected(self):
        for value in (0, -1, True, "10", 11):
            rt.save_settings({"interval": value})
            with self.assertRaises(ValueError):
                rt.settings()

    def test_startup_preference_migration_and_persistence(self):
        rt.save_settings({"interval": 10})
        self.assertTrue(rt.settings()["auto_check_after_launch"])
        rt.save_settings({**rt.settings(), "auto_check_after_launch": False})
        self.assertFalse(rt.settings()["auto_check_after_launch"])
        rt.save_settings({"auto_check_after_launch": "false"})
        with self.assertRaises(ValueError):
            rt.settings()

    def test_startup_scheduler_xml_and_regular_reminders(self):
        from xml.etree import ElementTree as ET
        from datetime import datetime, timezone
        captured = {}
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        def capture(*args, **kwargs):
            if args[0] == "/Create":
                captured[args[2]] = ET.parse(args[4]).getroot()
        config = {"interval": 60, "schedule_anchor": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with patch.object(rt.subprocess, "check_output", return_value='"test","S-1-5-21-123"'), \
             patch.object(rt, "scheduler", side_effect=capture):
            for enabled in (True, False, True):
                config["auto_check_after_launch"] = enabled
                anchor = config["schedule_anchor"]
                rt.configure_schedule(config)
                check = captured[rt.CHECK_TASK]
                self.assertEqual(check.find("t:Triggers/t:LogonTrigger", ns) is not None, enabled)
                self.assertEqual(check.findtext("t:Settings/t:StartWhenAvailable", namespaces=ns), str(enabled).lower())
                self.assertEqual(check.findtext("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", namespaces=ns), "PT60M")
                self.assertIsNotNone(captured[rt.REVIEW_TASK].find("t:Triggers/t:LogonTrigger", ns))
                self.assertEqual(config["schedule_anchor"], anchor)
                self.assertEqual(rt.settings()["auto_check_after_launch"], enabled)

    def test_startup_checkbox_saves_and_reloads(self):
        root = tk.Tk()
        root.withdraw()
        try:
            view = app.App(root)
            self.assertTrue(view.auto_check.get())
            with patch.object(view, "run_job", side_effect=lambda message, job: job()), patch.object(rt, "configure_engine"):
                view.auto_check_button.invoke()
            self.assertFalse(rt.settings()["auto_check_after_launch"])
        finally:
            root.destroy()
        root = tk.Tk()
        root.withdraw()
        try:
            self.assertFalse(app.App(root).auto_check.get())
        finally:
            root.destroy()

    def test_clipboard_layout_independent_and_replacement(self):
        root = tk.Tk()
        root.withdraw()
        try:
            view = app.App(root)
            self.assertEqual(view.url.get(), "")
            self.assertFalse(view.config.get("seller"))
            with patch.object(root, "clipboard_get", return_value=" https://www.fab.com/sellers/Test%20Seller \n"):
                view.url_shortcut(SimpleNamespace(keycode=86, keysym="Cyrillic_em"))
                self.assertEqual(view.url.get(), "https://www.fab.com/sellers/Test%20Seller")
                view.url_shortcut(SimpleNamespace(keycode=65))
                view.paste_url()
                self.assertEqual(view.url.get(), "https://www.fab.com/sellers/Test%20Seller")
                view.select_url()
                view.url_entry.event_generate("<<Paste>>")
                self.assertEqual(view.url.get(), "https://www.fab.com/sellers/Test%20Seller")
            self.assertFalse(list(rt.ROOT.glob("profiles/*")))
        finally:
            root.destroy()

    def test_native_tray_lifecycle_reopen_and_explorer_restart(self):
        root = tk.Tk()
        root.withdraw()
        tray = TrayIcon()
        try:
            self.assertTrue(tray.ready)
            show_existing()
            root.update()
            self.assertEqual(tray.events.get_nowait(), "show")
            # Remove then send Explorer's documented restoration message.
            from windows_shell import shell, c
            shell.Shell_NotifyIconW(2, c.byref(tray.data))
            tray.dispatch(tray.hwnd, tray.restart, 0, 0)
            self.assertTrue(tray.ready)
        finally:
            tray.close()
            root.destroy()
        self.assertFalse(tray.ready)

    def test_test_review_uses_persistent_store_and_scheduler(self):
        with patch.object(rt, "register_task") as register, patch.object(rt, "scheduler") as scheduler:
            rt.create_test_review()
            rt.create_test_review()
        self.assertEqual(register.call_args.args[:3], (rt.TEST_REVIEW_TASK, "--test-reminder", 10))
        scheduler.assert_called_with("/Run", "/TN", rt.TEST_REVIEW_TASK)
        db = Store(rt.ROOT / "test-reviews" / "monitor.sqlite")
        try:
            events = awaiting_review(db)
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0]["test"])
            self.assertFalse((rt.ROOT / "profiles").exists())
        finally:
            db.db.close()

    def test_close_repeats_at_600_seconds_restart_and_manual_confirmation(self):
        for kind in ("new_review", "new_comment"):
            with self.subTest(kind=kind):
                self.check_reminder_lifecycle(kind)

    def check_reminder_lifecycle(self, kind):
        with patch.object(rt, "register_task"), patch.object(rt, "scheduler"):
            rt.create_test_review(kind)
        path = rt.ROOT / "test-reviews" / "monitor.sqlite"
        db = Store(path)
        root = tk.Tk()
        root.withdraw()
        window = ReviewWindow(root, db, lambda: True, lambda: {"notifications": {"new_comment": {"repeat": 10}}})
        def refresh_at(clock):
            if window.timer is not None:
                root.after_cancel(window.timer)
                window.timer = None
            with patch("review_reminder.time.time", return_value=clock):
                window.refresh()
        try:
            refresh_at(1000)
            self.assertEqual(root.state(), "normal")
            with patch("review_reminder.time.time", return_value=1001):
                root.tk.call(root.protocol("WM_DELETE_WINDOW"))
            self.assertEqual(root.state(), "withdrawn")
            refresh_at(1599)
            self.assertEqual(root.state(), "withdrawn")
            refresh_at(1600)
            self.assertEqual(root.state(), "normal")
            with patch("review_reminder.time.time", return_value=1601):
                window.keep_open()
            if window.timer is not None:
                root.after_cancel(window.timer)
            root.destroy()
            db.db.close()

            db = Store(path)
            root = tk.Tk()
            root.withdraw()
            window = ReviewWindow(root, db, lambda: True, lambda: {"notifications": {"new_comment": {"repeat": 10}}})
            refresh_at(1601)
            self.assertEqual(root.state(), "withdrawn")
            refresh_at(2200)
            self.assertEqual(root.state(), "normal")
            window.confirm()
            self.assertEqual(awaiting_review(db), [])
            db.db.close()
            db = Store(path)
            self.assertEqual(awaiting_review(db), [])
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass
            db.db.close()

    def test_legacy_toast_comment_requires_personal_confirmation(self):
        import notifications
        db = Store(rt.ROOT / "legacy.sqlite", create=True)
        try:
            with db.db:
                for key, extra in (("missed", {}), ("history", {"silent": True}),
                                   ("owner", {"author_id": 5, "owner_id": 5}),
                                   ("read", {"confirmed_by_user_at": "2026-11-15T00:00:00Z"})):
                    db.event(key, {"kind": "new_comment", "author": "Buyer", **extra,
                                   "acknowledged_at": "2026-11-15T00:00:00Z"})
                db.event("fresh", {"kind": "new_comment", "author": "Buyer"})
            self.assertEqual({e["event_id"] for e in awaiting_review(db)}, {"missed", "fresh"})
            with patch.object(notifications, "send") as send:
                notifications.deliver(db)
                send.assert_not_called()
            event = next(e for e in db.records() if e["event_id"] == "missed")
            self.assertEqual(app.activity_status(event, event["acknowledged_at"], False, None), "Unread")
            self.assertTrue(db.confirm_review("missed"))
            event = next(e for e in db.records() if e["event_id"] == "missed")
            self.assertEqual(app.activity_status(event, event["acknowledged_at"], False, None), "Read")
            self.assertEqual(event["acknowledged_at"], "2026-11-15T00:00:00Z")
            self.assertEqual([e["event_id"] for e in awaiting_review(db)], ["fresh"])
        finally:
            db.db.close()

    def test_pagination_sort_and_filtered_counts(self):
        seller = {"id": "fixture", "name": "Example seller", "url": "https://www.fab.com/sellers/Example"}
        rt.save_settings({"interval": 60, "seller": seller})
        db = Store(rt.initialize(seller) / "monitor.sqlite")
        with db.db:
            for i in range(45):
                db.event(str(i), {"kind": "new_review" if i % 2 else "new_comment",
                                  "product": f"Product {i:02}", "author": f"Buyer {i:02}", "silent": True})
        db.db.close()
        root = tk.Tk()
        root.withdraw()
        try:
            view = app.App(root)
            first = set(view.feed.get_children())
            view.older_button.invoke()
            self.assertTrue(first.isdisjoint(view.feed.get_children()))
            for column in view.feed["columns"]:
                root.tk.call(view.feed.heading(column, "command"))
                self.assertEqual(view.page, 0)
            root.tk.call(view.feed.heading("Type", "command"))
            values = [view.feed.item(i, "values")[0] for i in view.feed.get_children()]
            self.assertTrue(all(v == values[0] for v in values))
            view.filter.set("Reviews")
            view.change_filter()
            self.assertEqual(view.page_label.cget("text"), "1–20 of 22")
        finally:
            root.destroy()

    def test_repeated_reviews_checkpoint_and_confirmation_after_restart(self):
        path = rt.ROOT / "state.sqlite"
        db = Store(path, create=True)
        product = {"uid": "p", "title": "Test", "url": "https://www.fab.com/listings/test"}
        try:
            for n in (1, 2, 3):
                latest = {str(i): {"uid": str(i), "createdAt": "2026-11-13T12:00:00Z"} for i in range(n)}
                collector.save_reviews(db, product, db.source("p", "reviews") or {}, latest, None)
                self.assertEqual(len(awaiting_review(db)), n)
            event = awaiting_review(db)[0]
            db.confirm_review(event["event_id"])
        finally:
            db.db.close()
        db = Store(path)
        try:
            self.assertEqual(len(awaiting_review(db)), 2)
            self.assertNotIn(event["event_id"], [e["event_id"] for e in awaiting_review(db)])
        finally:
            db.db.close()

    def test_owner_comments_silent_and_failed_fetch_preserves_checkpoint(self):
        db = Store(rt.ROOT / "state.sqlite", create=True)
        product = {"uid": "p", "title": "Test"}
        snapshot = {"url": "https://forums.unrealengine.com/t/1", "owner_id": 10,
                    "owner_username": "Seller", "seen_ids": [1, 2, 3], "checked_at": "now"}
        posts = [{"id": n, "post_number": n, "username": name, "user_id": uid,
                  "created_at": "2026-11-13T12:00:00Z", "cooked": "Test"}
                 for n, name, uid in ((2, "Seller", 10), (3, "Buyer", 20))]
        try:
            with patch.object(sources, "forum_snapshot", return_value=(snapshot, posts)):
                self.assertTrue(collector.check_forum(db, product, 1, []))
            self.assertEqual([e["author"] for e in db.records(pending=True)], ["Buyer"])
            old = db.source("p", "forum:1")
            errors = []
            with patch.object(sources, "forum_snapshot", side_effect=ValueError("Incomplete stream")):
                self.assertFalse(collector.check_forum(db, product, 1, errors))
            self.assertEqual(db.source("p", "forum:1"), old)
            self.assertEqual(len(errors), 1)
        finally:
            db.db.close()

    def test_package_has_no_user_data(self):
        package = Path(os.environ.get("FABWATCH_TEST_PACKAGE",
            str(Path(__file__).resolve().parents[1] / "dist" / f"FabWatchSetup-{rt.VERSION}-x64.exe")))
        if not package.exists() and "FABWATCH_TEST_PACKAGE" not in os.environ:
            self.skipTest("Build the installer first to validate the package")
        payload = package.read_bytes()
        size, checksum, magic = struct.unpack("<q32s8s", payload[-48:])
        data = payload[-48-size:-48]
        self.assertEqual(magic, b"FABWZIP1")
        self.assertEqual(hashlib.sha256(data).digest(), checksum)
        archive = zipfile.ZipFile(io.BytesIO(data))
        self.assertIn("_internal/fab-watch.ico", archive.namelist())
        self.assertIn("_internal/fab-watch-unread.ico", archive.namelist())
        self.assertIn("_internal/licenses/FabWatch-MIT.txt", archive.namelist())
        self.assertIn("_internal/licenses/Python-LICENSE.txt", archive.namelist())
        self.assertIn("_internal/licenses/Tcl-8.6.12.txt", archive.namelist())
        for name in archive.namelist():
            self.assertNotIn(Path(name).suffix, (".json", ".sqlite", ".db", ".log"))
            self.assertFalse(set(Path(name).parts) & {"profiles", "backups", "incidents", "test-reviews"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
