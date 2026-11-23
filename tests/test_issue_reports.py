from contextlib import closing
from pathlib import Path
import socket
import ssl
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import issue_reports
import notifications
import runtime as rt
import transport
from review_reminder import awaiting_review
from storage import Store

OFFLINE = {"stage": "catalog", "category": "connection", "message": transport.NETWORK_MESSAGE}
LEGACY = {"stage": "listing", "category": "temporary", "message": "URLError", "status": None}
FORMATS = {"stage": "reviews", "category": "schema", "status": 200, "message": "PRIVATE REVIEW",
           "url": "https://www.fab.com/listings/PRIVATE-ID",
           "shape": {"results": "list", "title": "PRIVATE SELLER", "PRIVATE-FIELD": "str",
                     "paging": {"next": "str", "_other_fields": 2}}}


class ConnectionTests(TestCase):
    def test_unreachable_hosts_are_retried_next_check(self):
        failure = URLError(socket.gaierror("DNS unavailable"))
        with patch.object(transport.opener, "open", side_effect=failure) as request, \
                patch.object(transport.time, "sleep"):
            with transport.connection_scope():
                for host in ("www.fab.com", "www.fab.com", "forums.unrealengine.com"):
                    with self.assertRaises(transport.SourceError) as raised:
                        transport.fetch(f"https://{host}/example")
                    self.assertEqual(raised.exception.category, "connection")
                self.assertEqual(request.call_count, 6)
            with self.assertRaises(transport.SourceError):
                transport.fetch("https://www.fab.com/example")
            self.assertEqual(request.call_count, 9)

    def test_tls_failure_is_not_offline(self):
        with patch.object(transport.opener, "open", side_effect=URLError(ssl.SSLError("invalid certificate"))):
            with self.assertRaises(transport.SourceError) as raised:
                transport.fetch("https://www.fab.com/example")
        self.assertEqual(raised.exception.category, "access")

    def test_old_and_new_connection_errors_are_quiet(self):
        with TemporaryDirectory() as folder:
            db = Store(Path(folder) / "monitor.sqlite", create=True)
            with closing(db.db):
                notifications.update_health(db, [OFFLINE])
                self.assertFalse(list(db.records()))
                with db.db:
                    db.event("legacy", {"kind": "monitor_error", "errors": [LEGACY]})
                self.assertFalse(awaiting_review(db))
                notifications.update_health(db, [OFFLINE, FORMATS])
                self.assertEqual(awaiting_review(db)[0]["errors"], [FORMATS])

    def test_engine_connection_error_goes_to_status(self):
        with TemporaryDirectory() as folder, patch.object(rt, "ROOT", Path(folder)):
            cfg = {"interval": 60}
            with patch.object(rt.engine_releases, "collect",
                              side_effect=transport.SourceError("connection", transport.NETWORK_MESSAGE)), \
                    patch.object(rt, "scheduler") as scheduler:
                rt.check_engine(cfg)
                scheduler.assert_not_called()
            db = Store(Path(folder) / "engine" / "monitor.sqlite")
            with closing(db.db):
                self.assertEqual(db.meta("engine_error"), transport.NETWORK_MESSAGE)
                self.assertFalse(list(db.records()))


class IssueReportTests(TestCase):
    def test_publish_uses_structural_allowlist_and_reuses_existing_issue(self):
        issue = f"https://github.com/{issue_reports.REPOSITORY}/issues/19"
        with patch.object(issue_reports, "run_cli", side_effect=["[]", issue]) as cli:
            self.assertEqual(issue_reports.publish("gh.exe", FORMATS, "1.4.1"), issue)
            create = cli.call_args
            self.assertIn(issue_reports.REPOSITORY, create.args)
            body = create.kwargs["body"]
            for value in ("PRIVATE", "www.fab.com", "title"):
                self.assertNotIn(value, body)
            self.assertIn('"results": "list"', body)
            self.assertIn("1.4.1", body)
            title = create.args[create.args.index("--title") + 1]
        import json
        with patch.object(issue_reports, "run_cli",
                          return_value=json.dumps([{"title": title, "url": issue}])) as cli:
            self.assertEqual(issue_reports.publish("gh.exe", FORMATS, "1.4.1"), issue)
            self.assertEqual(cli.call_count, 1)

    def test_offline_disabled_and_failed_send_retry_across_restart(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "probe.sqlite"
            db = Store(path, create=True)
            with closing(db.db), patch.object(issue_reports.time, "time", return_value=1000), \
                    patch.object(issue_reports, "publish", side_effect=RuntimeError) as publish:
                issue_reports.process(db, [OFFLINE, LEGACY], "gh.exe", "1.4.1")
                issue_reports.process(db, [FORMATS], None, "1.4.1")
                publish.assert_not_called()
                issue_reports.process(db, [FORMATS], "gh.exe", "1.4.1")
                publish.assert_called_once()
            db = Store(path)
            issue = f"https://github.com/{issue_reports.REPOSITORY}/issues/19"
            with closing(db.db), patch.object(issue_reports.time, "time",
                                              return_value=1000 + issue_reports.RETRY_SECONDS), \
                    patch.object(issue_reports, "publish", return_value=issue) as publish:
                issue_reports.process(db, [OFFLINE], "gh.exe", "1.4.1")
                publish.assert_not_called()
                issue_reports.process(db, [], "gh.exe", "1.4.1")
                issue_reports.process(db, [FORMATS], "gh.exe", "1.4.1")
                publish.assert_called_once()
                self.assertEqual(db.meta("github_issue_reports")["last_issue"], issue)
