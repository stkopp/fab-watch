import json
import http.client
import ssl
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

HOSTS = {"www.fab.com", "forums.unrealengine.com"}
NETWORK_MESSAGE = "No connection to the source. Check your internet connection."
SHAPE_KEYS = {"results", "next", "paging", "elements", "uid", "title", "ratings",
              "commentThreadStatus", "threadId", "post_stream", "posts_count", "id",
              "stream", "posts", "total", "start", "count", "highest_post_number",
              "topic_list", "topics", "more_topics_url"}


def is_connection_error(error):
    if error.get("category") == "connection":
        return True
    # Older versions stored connection failures without the underlying cause.
    return (error.get("category") in (None, "temporary") and error.get("status") is None
            and error.get("message") in ("URLError", "TimeoutError", "ConnectionError",
                                         "ConnectionResetError", "ConnectionRefusedError"))


def connection_problem(errors):
    return bool(errors) and all(is_connection_error(error) for error in errors)


def now():
    return datetime.now(timezone.utc).isoformat()


class SourceError(Exception):
    def __init__(self, category, message, status=None, shape=None):
        super().__init__(message)
        self.category, self.status, self.shape = category, status, shape


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc not in HOSTS:
        raise SourceError("schema", "Unexpected source host")


class RestrictedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


opener = build_opener(RestrictedRedirect())
cooldown = {}
unreachable = ContextVar("unreachable", default=None)


@contextmanager
def connection_scope():
    """Try each host again on the next check, without retrying it for every listing."""
    token = unreachable.set(set())
    try:
        yield
    finally:
        unreachable.reset(token)


def retry_after(header):
    if header:
        try:
            return max(60, int(header))
        except ValueError:
            try:
                return max(60, parsedate_to_datetime(header).timestamp() - time.time())
            except (ValueError, OverflowError, TypeError):
                pass
    return 3600


def shape(value, depth=0):
    """Describe an unexpected payload without copying data or arbitrary object keys."""
    if isinstance(value, dict):
        return {**{key: shape(value[key], depth + 1) if depth < 2 else type(value[key]).__name__
                   for key in sorted(SHAPE_KEYS & value.keys())}, "_other_fields": len(value.keys() - SHAPE_KEYS)}
    return type(value).__name__


def fetch(url):
    validate_url(url)
    host = urlsplit(url).hostname
    unavailable = unreachable.get()
    if unavailable is not None and host in unavailable:
        raise SourceError("connection", NETWORK_MESSAGE)
    if cooldown.get(host, 0) > time.time():
        raise SourceError("rate_limit", "Waiting for Retry-After", 429)
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                                        "Referer": "https://www.fab.com/", "Cache-Control": "no-cache"})
            with opener.open(req, timeout=12) as response:
                data = response.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise SourceError("incomplete", "Response size limit exceeded", 200)
            try:
                value = json.loads(data)
            except (ValueError, UnicodeError):
                # Login and anti-bot interstitials often return HTTP 200.
                lower = data[:16000].lower()
                if any(s in lower for s in (b"captcha", b"challenge-platform", b"access denied",
                                            b"sign in to continue", b"login required", b"cf-chl-")):
                    raise SourceError("access", "Access challenge or sign-in page", 200) from None
                if lower.lstrip().startswith((b"<!doctype html", b"<html")):
                    raise SourceError("schema", "HTML document instead of JSON", 200, "html") from None
                raise SourceError("response", "Expected JSON; source returned a different response", 200) from None
            if not isinstance(value, dict):
                raise SourceError("schema", "Expected JSON object", 200, shape(value))
            fetch.last_shape = shape(value)
            return value
        except HTTPError as exc:
            code = exc.code
            if code == 429:
                cooldown[host] = time.time() + retry_after(exc.headers.get("Retry-After"))
                raise SourceError("rate_limit", "Source requested fewer requests", code) from None
            if code in (401, 403):
                raise SourceError("access", "Source requires access or sign-in", code) from None
            if code in (404, 410):
                raise SourceError("missing", "Resource no longer available at this address", code) from None
            if code < 500 or attempt == 2:
                raise SourceError("temporary", f"HTTP {code}", code) from None
        except (URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            if isinstance(reason, ssl.SSLError):
                raise SourceError("access", "Could not verify the source's HTTPS connection") from None
            if attempt == 2:
                if isinstance(exc, (URLError, TimeoutError, ConnectionError)):
                    if unavailable is not None:
                        unavailable.add(host)
                    raise SourceError("connection", NETWORK_MESSAGE) from None
                raise SourceError("temporary", type(exc).__name__) from None
        time.sleep(attempt + 1)


fetch.last_shape = None
