import hashlib
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import updates


class UpdateTests(unittest.TestCase):
    def fixture(self, payload=b"x" * 100):
        return {"tag_name": "v1.4.0", "draft": False, "prerelease": False,
                "assets": [{"name": "FabWatchSetup-1.4.0-x64.exe",
                            "browser_download_url": updates.RELEASES + "/download/v1.4.0/FabWatchSetup-1.4.0-x64.exe",
                            "digest": "sha256:" + hashlib.sha256(payload).hexdigest(), "size": len(payload)}]}

    def test_version_comparison_and_prerelease(self):
        data = self.fixture()
        self.assertEqual(updates.parse_release(data, "1.3.1")["version"], "1.4.0")
        self.assertIsNone(updates.parse_release(data, "1.4.0"))
        self.assertIsNone(updates.parse_release(data, "1.10.0"))
        data["prerelease"] = True
        self.assertIsNone(updates.parse_release(data, "1.3.1"))
        for value in (None, "1.2", "v1.2.3-beta", "../../evil", True):
            with self.assertRaises(ValueError):
                updates.version(value)

    def test_rejects_wrong_repository_missing_digest_and_oversize(self):
        for key, value in (("browser_download_url", "https://github.com/other/repo/setup.exe"),
                           ("digest", None), ("digest", "sha256:no"), ("size", True),
                           ("size", updates.MAX_PACKAGE + 1)):
            data = self.fixture()
            data["assets"][0][key] = value
            with self.assertRaises(ValueError):
                updates.parse_release(data, "1.0.0")

    def test_download_verified_and_failed_partial_removed(self):
        payload = b"x" * 100
        release = updates.parse_release(self.fixture(payload), "1.0.0")
        with TemporaryDirectory() as folder:
            with patch.object(updates, "request", return_value=io.BytesIO(payload)):
                path = updates.download(release, folder)
            self.assertEqual(path.read_bytes(), payload)
            for bad in (b"y" * 100, b"x" * 20, b"x" * 101):
                with patch.object(updates, "request", return_value=io.BytesIO(bad)):
                    with self.assertRaises(ValueError):
                        updates.download(release, folder)
                self.assertEqual(path.read_bytes(), payload)
                self.assertFalse(list(Path(folder).glob("*.part")))

    def test_redirect_hosts_and_scheme(self):
        for url in (updates.API, updates.RELEASES, "https://release-assets.githubusercontent.com/asset"):
            updates.allowed(url)
        for url in ("http://github.com/file", "https://github.com.evil.test/file", "file:///tmp/a",
                    "https://evil.test/file", "https://user:pass@github.com/file", "https://github.com:444/file"):
            with self.assertRaises(ValueError):
                updates.allowed(url)

    def test_latest_invalid_data_and_network_errors_are_not_up_to_date(self):
        with patch.object(updates, "request", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                updates.latest("1.3.1")
        with patch.object(updates, "request", return_value=io.BytesIO(b"not json")):
            with self.assertRaises(ValueError):
                updates.latest("1.3.1")
        with patch.object(updates, "request", return_value=io.BytesIO(json.dumps(self.fixture()).encode())):
            self.assertEqual(updates.latest("1.3.1")["version"], "1.4.0")


if __name__ == "__main__":
    unittest.main()
