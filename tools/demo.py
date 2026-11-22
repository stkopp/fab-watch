"""Real UI with synthetic temporary data for documentation; no scheduler/network work."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import runtime as rt
import sources
import updates
from storage import Store, encode
from notification_settings import open_settings
from review_reminder import ReviewWindow
from appearance import theme


def demo():
    with TemporaryDirectory(prefix="fabwatch-demo-") as folder, \
            patch.object(rt, "ROOT", Path(folder)), patch.object(rt, "scheduler"), \
            patch.object(rt, "configure_engine"), patch.object(rt, "check"), \
            patch.object(rt, "check_engine"), patch.object(updates, "latest", return_value=None), \
            patch.object(sources, "resolve_seller", side_effect=ValueError("Demo mode does not connect to sources")):
        stamp = datetime.now(timezone.utc)
        seller = {"id": "demo-studio", "name": "Example Studio", "url": "https://www.fab.com/sellers/Example"}
        rt.save_settings({"seller": seller, "interval": 60, "auto_check_after_launch": True,
                          "schedule_anchor": stamp.isoformat()})
        db = Store(rt.initialize(seller) / "monitor.sqlite")
        titles = ["Modular Forest Village", "Stylized Adventure Props", "Dynamic Weather Toolkit",
                  "Sci-Fi Interior Kit", "Procedural Terrain Materials", "Fantasy Environment Bundle"]
        with db.db:
            for i, title in enumerate(titles):
                uid = f"sample-{i}"
                db.db.execute("INSERT INTO products VALUES (?,?)", (uid, encode({
                    "uid": uid, "title": title, "kind": "listings", "url": "https://www.fab.com"})))
                if i < 4:
                    db.set_source(uid, "forum_link", {"thread_id": i + 1})
            db.set_meta("last_report", {"at": stamp.isoformat(), "errors": []})
            db.set_meta("last_run_at", stamp.isoformat())
            db.set_meta("last_success_at", stamp.isoformat())
            for i, (kind, title, author, content, state) in enumerate([
                ("new_review", titles[0], "Sample Buyer 01", "Great modular kit. Easy to customize and well organized!", "unread"),
                ("new_comment", titles[2], "Sample Buyer 02", "Does the weather system support multiplayer projects?", "unread"),
                ("new_comment", titles[2], "Example Studio", "Yes! The included guide explains the multiplayer setup.", "seller"),
                ("new_review", titles[1], "Sample Buyer 03", "A useful collection for our prototype.", "read"),
                ("new_comment", titles[3], "Sample Buyer 04", "Thanks for the material examples.", "history"),
                ("new_review", titles[4], "Sample Buyer 05", "Clear documentation and flexible controls.", "history"),
            ]):
                event = {"kind": kind, "product": title, "author": author,
                         "created_at": (stamp - timedelta(days=i)).isoformat(),
                         "url": "https://www.fab.com", "silent": state == "history"}
                if state == "seller":
                    event.update(author_id=10, owner_id=10)
                if kind == "new_review":
                    event["review"] = {"content": content, "title": "Sample review", "rating": 5,
                                       "authorDisplayName": author, "createdAt": event["created_at"]}
                else:
                    event["content_html"] = "<p>" + content + "</p>"
                db.event(f"demo-{i}", event)
            db.confirm_review("demo-3")
        db.db.close()
        engine = rt.ROOT / "engine"
        engine.mkdir()
        db = Store(engine / "monitor.sqlite", create=True)
        with db.db:
            db.set_meta("engine_last_success", stamp.isoformat())
            for kind in ("engine_release", "engine_preview"):
                db.set_meta(kind, {"checked": stamp.timestamp()})
            for i, (kind, number) in enumerate([
                ("engine_preview", "5.9"), ("engine_release", "5.8"),
                ("engine_preview", "5.8"), ("engine_release", "5.7"), ("engine_preview", "5.7")]):
                db.event(f"engine-demo-{i}", {"kind": kind, "version": number,
                    "created_at": (stamp - timedelta(days=i*15)).isoformat(), "silent": True,
                    "title": "Sample Unreal Engine announcement", "url": "https://forums.unrealengine.com",
                    "message": "Demo data: a new version of Unreal Engine is available."})
        db.db.close()
        root = tk.Tk()
        view = app.App(root)
        root.title("Fab Watch — Demo data")
        root.geometry("1050x800+200+120")
        view.feed.selection_set("demo-0")
        view.select()
        mode = sys.argv[1] if len(sys.argv) > 1 else "main"
        if mode in ("engine", "notifications"):
            view.tabs.select(2)
        if mode == "notifications":
            def dialog():
                open_settings(root, view.config, lambda values: None)
            root.after(500, dialog)
        if mode == "reminders":
            root.withdraw()
            db = Store(rt.profile(seller) / "monitor.sqlite")
            try:
                popup = tk.Toplevel(root)
                theme(popup)
                reminder = ReviewWindow(popup, db, lambda: True, lambda: {"popout_layout": "grouped"})
                popup.geometry("640x620+220+120")
                reminder.refresh()
                popup.bind("<Destroy>", lambda event: root.quit() if event.widget is popup else None)
                root.after(600000, root.quit)
                root.mainloop()
            finally:
                db.db.close()
                root.destroy()
            return
        root.after(600000, root.destroy)
        root.mainloop()


if __name__ == "__main__":
    demo()
