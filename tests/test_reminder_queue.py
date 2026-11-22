from contextlib import closing
from ctypes import byref
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import runtime as rt
from review_reminder import ReviewWindow, rating_text
from notification_policy import snooze
from storage import Store
from windows_shell import TrayIcon, shell


class ReminderQueueTests(unittest.TestCase):
    def test_sequential_and_grouped_share_due_items_across_sources(self):
        with TemporaryDirectory() as folder:
            self.check_queue(Path(folder))

    def check_queue(self, folder):
        seller = Store(folder / "seller.sqlite", create=True)
        engine = Store(folder / "engine.sqlite", create=True)
        root = tk.Tk()
        root.withdraw()
        try:
            with seller.db, engine.db:
                seller.event("review", {"kind": "new_review", "detected_at": "2026-01-01T00:00:00Z",
                                       "url": "https://www.fab.com/listings/example", "review": {"rating": 5}})
                seller.event("comment", {"kind": "new_comment", "detected_at": "2026-01-03T00:00:00Z",
                                        "url": "https://forums.unrealengine.com/t/1234/2"})
                engine.event("release", {"kind": "engine_release", "detected_at": "2026-01-02T00:00:00Z",
                                         "url": "https://forums.unrealengine.com/t/2345"})
            config = {}
            window = ReviewWindow(root, lambda _: (seller, engine), lambda: True, lambda: config)

            with patch("review_reminder.time.time", return_value=1000):
                window.update_queue()
                window.update_queue()
                self.assertEqual(list(window.shown), [(seller, "review")])
                self.assertIsNone(engine.meta("notice:release"))
                window.keep_open()
                window.update_queue()
                self.assertEqual(list(window.shown), [(engine, "release")])
                self.assertIsNone(seller.meta("notice:comment"))

                config["popout_layout"] = "grouped"
                window.update_queue()
                self.assertEqual(list(window.shown), [(engine, "release"), (seller, "comment")])
                with patch("review_reminder.webbrowser.open") as opened:
                    for card in window.cards.winfo_children():
                        actions = card.winfo_children()[-1]
                        next(w for w in actions.winfo_children() if w.cget("text") == "Open source").invoke()
                    self.assertEqual([call.args[0] for call in opened.call_args_list],
                                     ["https://forums.unrealengine.com/t/2345",
                                      "https://forums.unrealengine.com/t/1234/2"])
                snooze(seller, "comment", 10, clock=1000)
                window.confirm((engine, "release"))
                window.update_queue()
                self.assertEqual(list(window.shown), [])
                self.assertEqual({e["event_id"] for e in seller.records(reminders=True)}, {"review", "comment"})
                self.assertFalse(list(engine.records(reminders=True)))
            reopened = Store(folder / "seller.sqlite")
            with closing(reopened.db):
                self.assertEqual(reopened.meta("snooze:comment"), 1600)
        finally:
            root.destroy()
            seller.db.close()
            engine.db.close()

    def test_unread_view_counts_background_activity_while_hidden(self):
        with TemporaryDirectory() as folder, patch.object(rt, "ROOT", Path(folder)):
            seller = {"id": "fixture", "name": "Example", "url": "https://www.fab.com/sellers/Example"}
            rt.save_settings({"seller": seller})
            seller_db = Store(rt.initialize(seller) / "monitor.sqlite")
            engine_db = Store(rt.engine_folder() / "monitor.sqlite")
            root = tk.Tk()
            root.withdraw()
            try:
                view = app.App(root)
                self.assertEqual(view.displayed_unread, (0, 0))
                with seller_db.db, engine_db.db:
                    seller_db.event("review", {"kind": "new_review"})
                    seller_db.event("history", {"kind": "new_comment", "silent": True})
                    seller_db.event("owner", {"kind": "new_comment", "author_id": 1, "owner_id": 1})
                    seller_db.event("demo", {"kind": "new_review", "test": True})
                    engine_db.event("release", {"kind": "engine_release"})
                snooze(seller_db, "review", 10)
                view.refresh_view()
                self.assertEqual(view.displayed_unread, (1, 1))
                view.show_unread()
                self.assertEqual(view.feed.get_children(), ("review",))
                self.assertEqual(view.engine_table.get_children(), ("release",))
                seller_db.confirm_review("review")
                engine_db.confirm_review("release")
                view.refresh_view()
                self.assertEqual(view.displayed_unread, (0, 0))
                self.assertEqual(view.feed.get_children(), ())
            finally:
                root.destroy()
                seller_db.db.close()
                engine_db.db.close()

    def test_rating_labels(self):
        self.assertEqual(rating_text({"rating": 1}), "1/5   ★☆☆☆☆")
        self.assertEqual(rating_text({"rating": 5}), "5/5   ★★★★★")
        for value in (None, True, 0, 6, "4", 1.5):
            self.assertEqual(rating_text({"rating": value}), "")

    def test_unread_tray_icon_survives_explorer_restart_message(self):
        tray = TrayIcon()
        try:
            self.assertTrue(tray.ready)
            self.assertTrue(tray.unread_icon)
            tray.set_unread(2)
            self.assertEqual(tray.data.hIcon, tray.unread_icon)
            self.assertIn("2 unread", tray.data.szTip)
            shell.Shell_NotifyIconW(2, byref(tray.data))
            tray.dispatch(tray.hwnd, tray.restart, 0, 0)
            self.assertTrue(tray.ready)
            self.assertEqual(tray.data.hIcon, tray.unread_icon)
            tray.set_unread(0)
            self.assertEqual(tray.data.hIcon, tray.icon)
        finally:
            tray.close()
