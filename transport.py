import json
import http.client
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

HOSTS = {"www.fab.com", "forums.unrealengine.com"}


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
        known = {"results", "next", "paging", "elements", "uid", "title", "ratings",
                 "commentThreadStatus", "threadId", "post_stream", "posts_count", "id",
                 "stream", "posts", "total", "start", "count", "highest_post_number"}
        return {**{key: shape(value[key], depth + 1) if depth < 2 else type(value[key]).__name__
                   for key in sorted(known & value.keys())}, "_other_fields": len(value.keys() - known)}
    return type(value).__name__


def fetch(url):
    validate_url(url)
    host = urlsplit(url).hostname
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
            if attempt == 2:
                raise SourceError("temporary", type(exc).__name__) from None
        time.sleep(attempt + 1)


fetch.last_shape = None
