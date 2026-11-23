"""Opt-in public reports built from bounded, structural diagnostics."""
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from storage import identity
from transport import SHAPE_KEYS, connection_problem
from updates import REPOSITORY

STAGES = {"catalog", "listing", "reviews", "discussion_link", "forum", "engine"}
CATEGORIES = {"schema", "incomplete", "response", "critical"}
SHAPE_TYPES = {"dict", "list", "str", "int", "float", "bool", "NoneType", "html"}
MAX_QUEUED = 24
RETRY_SECONDS = 15 * 60


def safe_shape(value, depth=0):
    if isinstance(value, str) and value in SHAPE_TYPES:
        return value
    if not isinstance(value, dict) or depth > 2:
        return None
    keys = SHAPE_KEYS | {"_other_fields"}
    result = {}
    for key in sorted(keys & value.keys()):
        item = value[key]
        if key == "_other_fields":
            if type(item) is int and 0 <= item <= 10000:
                result[key] = item
        else:
            child = safe_shape(item, depth + 1)
            if child is not None:
                result[key] = child
    return result or None


def diagnostic(error):
    stage, category = error.get("stage"), error.get("category")
    if stage not in STAGES or category not in CATEGORIES:
        return None
    status = error.get("status")
    return {"stage": stage, "category": category,
            "status": status if type(status) is int and 100 <= status <= 599 else None,
            "shape": safe_shape(error.get("shape"))}


def cli_path(value):
    path = Path(value)
    if not path.is_absolute() or path.name.lower() != "gh.exe" or not path.is_file():
        raise ValueError("Choose an installed GitHub CLI executable (gh.exe).")
    return path


def run_cli(executable, *args, body=None):
    env = dict(os.environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", GH_HOST="github.com")
    # Use the signed-in Windows user's CLI account, not an inherited CI credential.
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_REPO"):
        env.pop(name, None)
    result = subprocess.run([str(cli_path(executable)), *args], input=body or "",
                            encoding="utf-8", errors="replace", capture_output=True, timeout=20,
                            cwd=os.environ["SystemRoot"], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("GitHub CLI could not complete the request.")
    return result.stdout.strip()


def check_auth(executable):
    try:
        if not run_cli(executable, "api", "user", "--jq", ".login"):
            raise RuntimeError("No GitHub account returned")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Sign in with GitHub CLI before enabling public reports.") from exc


def publish(executable, details, version):
    # Rebuild the outbound payload even if the stored queue is from an older version.
    details = diagnostic(details)
    if not details or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid public report")
    key = identity(details)
    title = f"Fab Watch report: {details['stage']} / {details['category']} [{key}]"
    matches = json.loads(run_cli(executable, "issue", "list", "--repo", REPOSITORY,
                                 "--state", "all", "--search", f'{key} in:title',
                                 "--json", "title,url", "--limit", "10"))
    prefix = f"https://github.com/{REPOSITORY}/issues/"

    def valid_url(value):
        return isinstance(value, str) and value.startswith(prefix) and value[len(prefix):].isascii() and value[len(prefix):].isdigit()

    for match in matches:
        if match.get("title") == title and valid_url(match.get("url")):
            return match["url"]
    body = (
        f"Fab Watch {version} detected a source failure.\n\n"
        f"- Check: {details['stage']}\n"
        f"- Failure: {details['category']}\n"
        f"- HTTP status: {details['status'] if details['status'] is not None else 'unavailable'}\n"
        f"- Response structure: `{json.dumps(details['shape'], sort_keys=True)}`\n"
    )
    url = run_cli(executable, "issue", "create", "--repo", REPOSITORY,
                  "--title", title, "--body-file", "-", body=body)
    if not valid_url(url):
        raise ValueError("GitHub CLI did not return an issue URL")
    return url


def process(db, errors, executable, version):
    if not executable or connection_problem(errors):
        return
    state = db.meta("github_issue_reports") or {}
    pending = state.get("pending", {})
    sent = state.get("sent", {})
    for error in errors:
        details = diagnostic(error)
        if details:
            key = identity(details)
            if key not in sent and len(pending) < MAX_QUEUED:
                pending.setdefault(key, details)
    if not pending:
        return
    state.update(pending=pending, sent=sent)
    clock = time.time()
    key = next(iter(pending))
    attempt = clock >= state.get("retry_at", 0)
    if attempt:
        state["retry_at"] = clock + RETRY_SECONDS
    with db.db:
        db.set_meta("github_issue_reports", state)
    if not attempt:
        return
    try:
        url = publish(executable, pending[key], version)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        logging.warning("Could not publish a public diagnostic report. Will retry during a later check.")
        return
    sent[key] = url
    del pending[key]
    state["last_issue"] = url
    with db.db:
        db.set_meta("github_issue_reports", state)
