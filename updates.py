"""Public GitHub release checks; no credentials, telemetry or automatic execution."""
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import webbrowser

from appearance import BG, TEXT, MUTED, ACCENT, FONT
from storage import write_file

REPOSITORY = "stkopp/fab-watch"
RELEASES = f"https://github.com/{REPOSITORY}/releases"
API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_PACKAGE = 128 << 20


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise ValueError("Unsupported release version")
    return tuple(map(int, value.lstrip("v").split(".")))


def allowed(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.username or parts.password or
            parts.port not in (None, 443) or parts.hostname not in
            {"api.github.com", "github.com", "release-assets.githubusercontent.com",
             "objects.githubusercontent.com"}):
        raise ValueError("Unexpected update download host")


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request(url):
    allowed(url)
    return build_opener(SafeRedirect()).open(Request(url, headers={
        "User-Agent": "FabWatch-updates", "Accept": "application/vnd.github+json"}), timeout=30)


def parse_release(data, current):
    if not isinstance(data, dict):
        raise ValueError("Invalid GitHub release response")
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name")
    numbers = version(tag)
    if numbers <= version(current):
        return None
    number = ".".join(map(str, numbers))
    name = f"FabWatchSetup-{number}-x64.exe"
    expected = f"{RELEASES}/download/{tag}/{name}"
    for asset in data.get("assets", []):
        if asset.get("name") != name:
            continue
        digest = asset.get("digest", "")
        if (asset.get("browser_download_url") != expected or
                not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or
                type(asset.get("size")) is not int or not 48 < asset["size"] <= MAX_PACKAGE):
            raise ValueError("Release installer metadata could not be verified. See GitHub Releases.")
        return {"version": number, "name": name, "url": expected,
                "page": f"{RELEASES}/tag/{tag}", "sha256": digest[7:], "size": asset["size"]}
    raise ValueError("The latest release has no Windows x64 installer yet. Try again later.")


def latest(current):
    try:
        with request(API) as response:
            raw = response.read((2 << 20) + 1)
            if len(raw) > 2 << 20:
                raise ValueError("Release response is too large")
            return parse_release(json.loads(raw), current)
    except HTTPError as exc:
        if exc.code == 404:
            raise ValueError("No public release is available yet. Try again later.") from exc
        raise


def download(release, directory):
    # Revalidate metadata even when it came from a local cache.
    release = parse_release({"tag_name": "v" + release["version"], "assets": [{
        "name": release["name"], "browser_download_url": release["url"],
        "digest": "sha256:" + release["sha256"], "size": release["size"]}]}, "0.0.0")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / release["name"]
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    total = 0
    try:
        with request(release["url"]) as response, partial.open("wb") as stream:
            while chunk := response.read(1 << 20):
                total += len(chunk)
                if total > release["size"] or total > MAX_PACKAGE:
                    raise ValueError("Update download exceeds its declared size")
                stream.write(chunk)
                digest.update(chunk)
        if total != release["size"] or digest.hexdigest() != release["sha256"]:
            raise ValueError("Update checksum mismatch. The installer was not run.")
        os.replace(partial, target)
        return target
    finally:
        partial.unlink(missing_ok=True)


class UpdateUI:
    def __init__(self, root, current, directory, install, local_install):
        self.root, self.current, self.directory = root, current, Path(directory)
        self.install, self.local_install = install, local_install
        self.results = queue.Queue()
        self.busy = False
        self.release = None
        self.window = None
        self.message = "Check GitHub for a newer Fab Watch version."
        self.badge = None

    def start(self):
        self.root.after(200, self.poll)
        self.root.after(3000, self.automatic)

    def automatic(self):
        try:
            cached = json.loads((self.directory / "update-state.json").read_text("utf-8"))
            age = time.time() - float(cached.get("checked_at", 0))
            if 0 <= age < 86400:
                # Only restore an availability indication. Installation rechecks GitHub.
                if cached.get("version") and version(cached["version"]) > version(self.current):
                    self.badge.configure(text=f"Update {cached['version']} available", fg=ACCENT)
            else:
                self.check()
        except (OSError, ValueError, TypeError, AttributeError):
            self.check()
        self.root.after(3600000, self.automatic)

    def open(self):
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
        self.window = tk.Toplevel(self.root, bg=BG)
        self.window.title("Fab Watch updates")
        self.window.geometry("540x245")
        self.window.minsize(540, 245)
        self.window.transient(self.root)
        try:
            self.window.iconphoto(True, self.root.fab_icon)
        except AttributeError:
            pass
        tk.Label(self.window, text=f"Installed version: {self.current}", bg=BG, fg=TEXT,
                 font=(FONT, 13, "bold")).pack(anchor="w", padx=20, pady=(20, 10))
        self.status = tk.Label(self.window, text=self.message, bg=BG, fg=MUTED,
                               font=(FONT, 10), wraplength=495, justify="left")
        self.status.pack(fill="x", padx=20, pady=6)
        row = tk.Frame(self.window, bg=BG)
        row.pack(fill="x", padx=20, pady=10)
        self.check_button = ttk.Button(row, text="Check for updates", command=self.check)
        self.check_button.pack(side="left")
        self.install_button = ttk.Button(row, text="Download and install", command=self.get_update)
        self.install_button.pack(side="right")
        row = tk.Frame(self.window, bg=BG)
        row.pack(fill="x", padx=20)
        ttk.Button(row, text="Release notes", command=lambda: webbrowser.open(RELEASES)).pack(side="left")
        ttk.Button(row, text="Install local file…", command=self.local_install).pack(side="right")
        self.paint()
        self.check()

    def paint(self):
        if self.window and self.window.winfo_exists():
            self.status.configure(text=self.message)
            self.check_button.state(["disabled" if self.busy else "!disabled"])
            self.install_button.state(["!disabled" if self.release and not self.busy else "disabled"])

    def work(self, kind, action):
        self.busy = True
        self.paint()
        def run():
            try:
                self.results.put((kind, action(), None))
            except Exception as exc:
                self.results.put((kind, None, str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def check(self):
        if self.busy:
            return
        self.message = "Checking GitHub Releases…"
        self.work("check", lambda: latest(self.current))

    def get_update(self):
        if self.busy or not self.release:
            return
        self.message = "Downloading and verifying the installer…"
        def fresh_download():
            release = latest(self.current)
            if not release:
                raise ValueError("No newer release is available")
            return download(release, self.directory / "updates")
        self.work("download", fresh_download)

    def poll(self):
        try:
            kind, result, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if error:
                self.release = None
                self.message = "Could not check or download the update: " + error[:260]
            elif kind == "check":
                self.release = result
                self.message = f"Version {result['version']} is available." if result else "You have the latest published version."
                if self.badge:
                    self.badge.configure(text=f"Update {result['version']} available" if result else f"v{self.current}",
                                         fg=ACCENT if result else MUTED)
                try:
                    self.directory.mkdir(parents=True, exist_ok=True)
                    write_file(self.directory / "update-state.json", json.dumps({
                        "checked_at": time.time(), "version": result["version"] if result else self.current}))
                except OSError:
                    pass
            else:
                self.message = "Installer verified."
                self.paint()
                self.install(result)
            self.paint()
        self.root.after(200, self.poll)
