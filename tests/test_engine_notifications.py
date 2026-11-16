from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine_releases as engine
import runtime as rt
import app
from storage import Store
from notification_policy import policies, due, snooze, remember
from notification_settings import open_settings
from review_reminder import ReviewWindow, awaiting_review


def topic(kind, version, uid=1):
    return {"kind": kind, "version_tuple": tuple(version), "version": ".".join(map(str, version)),
            "topic_id": uid, "title": "Announcement", "created_at": "2026-11-01T00:00:00Z",
            "url": f"https://forums.unrealengine.com/t/{uid}"}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(rt, "ROOT", Path(self.tmp.name))
        self.patch.start()
        self.db = Store(rt.ROOT / "test.sqlite", create=True)

    def tearDown(self):
        self.db.db.close()
        self.patch.stop()
        self.tmp.cleanup()

    def test_classification(self):
        for title, expected in (
            ("Unreal Engine 5.8 Released", ("engine_release", (5, 8))),
            ("Unreal Engine 6 is now available!", ("engine_release", (6, 0))),
            ("5.8.4 Hotfix Released", ("engine_hotfix", (5, 8, 4))),
            ("Unreal Engine 5.9 MegaJam Preview", ("engine_preview", (5, 9, 0))),
            ("Unreal Engine 5.9 Preview 2", ("engine_preview", (5, 9, 2))),
            ("How we built a game with Unreal Engine 5.8", None),
            ("RealityCapture 1.4 is now available", None)):
            self.assertEqual(engine.classify(title), expected)

    def test_baseline_then_multiple_releases_no_duplicates(self):
        items = [topic("engine_release", (5, 8)), topic("engine_preview", (5, 9, 0), 2)]
        with patch.object(engine, "scan", return_value=items):
            engine.collect(self.db, {})
        self.assertEqual(awaiting_review(self.db), [])
        items += [topic("engine_release", (5, 9), 3), topic("engine_release", (6, 0), 4)]
        with patch.object(engine, "scan", return_value=items):
            engine.collect(self.db, {}, force=True)
            engine.collect(self.db, {}, force=True)
        events = awaiting_review(self.db)
        self.assertEqual([e["version"] for e in events], ["5.9", "6.0"])
        self.db.confirm_review(events[0]["event_id"])
        self.assertEqual(len(awaiting_review(self.db)), 1)
        self.assertIsNone(self.db.meta("engine_hotfix"))

    def test_disabled_no_fetch_and_independent_intervals(self):
        disabled = {"notifications": {k: {"check": None} for k in engine.KINDS}}
        with patch.object(engine, "scan") as scan:
            engine.collect(self.db, disabled, force=True)
            scan.assert_not_called()
        items = [topic("engine_release", (5, 8)), topic("engine_preview", (5, 9, 0), 2)]
        with patch.object(engine, "scan", return_value=items) as scan:
            engine.collect(self.db, {})
            engine.collect(self.db, {})
            self.assertEqual(scan.call_count, 1)
        before = self.db.meta("engine_release")
        with patch.object(engine, "scan", side_effect=ValueError("Incomplete page")):
            with self.assertRaises(ValueError):
                engine.collect(self.db, {}, force=True)
        self.assertEqual(self.db.meta("engine_release"), before)

    def test_pagination_and_schema_errors(self):
        page1 = {"topic_list": {"topics": [{"id": 1, "title": "Other", "created_at": "2026-11-16T00:00:00Z"}],
                               "more_topics_url": "?page=1"}}
        page2 = {"topic_list": {"topics": [{"id": 2, "title": "Unreal Engine 5.9 Released", "created_at": "2026-11-15T00:00:00Z"}],
                               "more_topics_url": None}}
        with patch.object(engine, "fetch", side_effect=[page1, page2]) as fetch:
            result = engine.scan(datetime(2026, 1, 1, tzinfo=timezone.utc))
            self.assertEqual(result[0]["version"], "5.9")
            self.assertEqual(fetch.call_count, 2)
        page2["topic_list"]["topics"][0]["title"] = "Unreal Engine 5.9 now available to everyone"
        with patch.object(engine, "fetch", return_value=page2), self.assertRaises(ValueError):
            engine.scan(datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_policy_validation_defaults_and_save(self):
        prefs = policies({})
        self.assertEqual(prefs["new_comment"], {"mode": "popout", "repeat": 30})
        self.assertEqual(prefs["engine_hotfix"]["check"], None)
        self.assertEqual(prefs["engine_release"]["check"], 720)
        for bad in ({"repeat": 0}, {"repeat": True}, {"mode": "email"}, {"unknown": 5}):
            with self.assertRaises(ValueError):
                policies({"notifications": {"new_review": bad}})
        rt.save_settings({"interval": 60, "notifications": prefs})
        self.assertEqual(policies(rt.settings()), prefs)

    def test_snooze_overrides_repeat_survives_restart_and_is_not_read(self):
        with self.db.db:
            self.db.event("s", {"kind": "engine_release", "message": "Release"})
        event = awaiting_review(self.db)[0]
        policy = policies({})["engine_release"]
        remember(self.db, event, policy, 1000)
        snooze(self.db, "s", 10, clock=1000)
        self.assertFalse(due(self.db, event, policy, 1599))
        self.assertTrue(due(self.db, event, policy, 1600))
        self.db.db.close()
        self.db = Store(rt.ROOT / "test.sqlite")
        self.assertEqual(len(awaiting_review(self.db)), 1)
        self.assertTrue(due(self.db, event, policy, 1600))
        remember(self.db, event, policy, 1600)
        self.assertFalse(due(self.db, event, policy, 1601))
        snooze(self.db, "s", 30, clock=1605)
        remember(self.db, event, policy, 1600)
        self.assertEqual(self.db.meta("snooze:s"), 3405)

    def test_toast_protocol_actions_scope_validation(self):
        from storage import identity
        folder = rt.engine_folder()
        db = Store(folder / "monitor.sqlite")
        key = identity("test", "engine")
        try:
            with db.db:
                db.event(key, {"kind": "engine_release", "message": "Test"})
            rt.notification_action(f"fabwatch://snooze?scope=engine&event={key}")
            self.assertTrue(db.meta("snooze:" + key))
            self.assertEqual(len(awaiting_review(db)), 1)
            rt.notification_action(f"fabwatch://read?scope=engine&event={key}")
            self.assertEqual(awaiting_review(db), [])
            for bad in (f"fabwatch://snooze?scope=../profiles&event={key}",
                        f"https://snooze?scope=engine&event={key}",
                        f"fabwatch://snooze?scope=engine&event={key}&event=other"):
                with self.assertRaises(ValueError):
                    rt.notification_action(bad)
        finally:
            db.db.close()

    def test_windows_repeat_once_none_and_mode_switch(self):
        with self.db.db:
            self.db.event("preview", {"kind": "engine_preview", "product": "Engine", "message": "New preview"})
        config = {"notifications": {"engine_preview": {"mode": "windows", "repeat": 720}}}
        root = tk.Tk(); root.withdraw()
        window = ReviewWindow(root, self.db, lambda: True, lambda: config)
        def tick(clock):
            if window.timer is not None:
                root.after_cancel(window.timer)
            with patch("review_reminder.time.time", return_value=clock):
                window.refresh()
        try:
            with patch("review_reminder.send") as send:
                tick(1000); tick(1001); tick(44199)
                self.assertEqual(send.call_count, 1)
                tick(44200)
                self.assertEqual(send.call_count, 2)
                self.assertEqual(root.state(), "withdrawn")
                self.assertEqual(len(awaiting_review(self.db)), 1)
                config["notifications"]["engine_preview"]["repeat"] = None
                tick(999999)
                self.assertEqual(send.call_count, 2)
                config["notifications"]["engine_preview"]["mode"] = "popout"
                tick(1000000)
                self.assertEqual(root.state(), "normal")
                self.assertIn("preview", root.title().lower())
                window.keep_open()
                tick(2000000)
                self.assertEqual(root.state(), "withdrawn")
                window.confirm()
                self.assertEqual(awaiting_review(self.db), [])
        finally:
            try: root.destroy()
            except tk.TclError: pass

    def test_failed_windows_delivery_does_not_acknowledge(self):
        with self.db.db:
            self.db.event("p", {"kind": "engine_preview", "message": "Preview"})
        root = tk.Tk(); root.withdraw()
        window = ReviewWindow(root, self.db, lambda: True)
        try:
            with patch("review_reminder.send", side_effect=RuntimeError("blocked")), \
                 self.assertLogs(level="ERROR"):
                window.refresh()
            self.assertEqual(len(awaiting_review(self.db)), 1)
            self.assertIsNone(self.db.meta("notice:p"))
        finally:
            root.destroy()

    def test_settings_dialog_and_engine_tab_without_seller(self):
        root = tk.Tk(); root.withdraw()
        try:
            view = app.App(root)
            self.assertEqual(len(view.tabs.tabs()), 3)
            root.geometry("820x625")
            view.tabs.select(2)
            root.deiconify()
            root.update_idletasks()
            self.assertTrue(view.engine_later.winfo_ismapped())
            self.assertLessEqual(view.engine_later.winfo_rooty() + view.engine_later.winfo_height(),
                                 root.winfo_rooty() + root.winfo_height())
            saved = []
            dialog = open_settings(root, {}, saved.append)
            def descendants(w):
                for child in w.winfo_children():
                    yield child
                    yield from descendants(child)
            save = next(w for w in descendants(dialog) if w.winfo_class() == "TButton" and w.cget("text") == "Save")
            save.invoke()
            self.assertEqual(saved, [policies({})])
            self.assertFalse((rt.ROOT / "profiles").exists())
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
