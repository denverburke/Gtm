"""Allow-listed HTTP for the REST-based fetchers (HubSpot, Search Console, Semrush).

Every request is checked against an explicit (method, host, path) allow-list of read endpoints.
Anything else raises before a byte leaves the machine. Some read endpoints use POST
(HubSpot search, GSC searchAnalytics.query), so the list matches exact paths, not just methods.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

import requests

from . import NotReadOnlyError

ALLOWED: list[tuple[str, str, str]] = [
    # HubSpot
    ("POST", "api.hubapi.com", r"/oauth/v2/private-apps/get/access-token-info"),  # read our own scopes
    ("POST", "api.hubapi.com", r"/crm/v3/objects/(contacts|deals)/search"),
    ("GET", "api.hubapi.com", r"/crm/v3/objects/(contacts|deals)"),
    # Search Console (readonly OAuth scope as well)
    ("POST", "searchconsole.googleapis.com", r"/webmasters/v3/sites/[^/]+/searchAnalytics/query"),
    ("GET", "searchconsole.googleapis.com", r"/webmasters/v3/sites(/[^/]+)?"),
    # Semrush Analytics API (no write operations exist on it; type= is checked separately)
    ("GET", "api.semrush.com", r"/"),
]
SEMRUSH_TYPES = {"domain_organic"}


def check(method: str, url: str, params: dict | None = None) -> None:
    u = urlsplit(url)
    ok = any(method == m and u.hostname == h and re.fullmatch(p, u.path) for m, h, p in ALLOWED)
    if ok and u.hostname == "api.semrush.com" and (params or {}).get("type") not in SEMRUSH_TYPES:
        ok = False
    if not ok:
        raise NotReadOnlyError(f"Blocked non-allow-listed request: {method} {u.hostname}{u.path}")


class ReadOnlySession:
    """Wraps a requests-compatible session (plain, or google-auth's AuthorizedSession)."""

    def __init__(self, session=None, headers: dict | None = None, min_interval: float = 0.0):
        self._s = session or requests.Session()
        if headers:
            self._s.headers.update(headers)
        self._min, self._last = min_interval, 0.0

    def request(self, method: str, url: str, *, params=None, json=None, retries: int = 4):
        method = method.upper()
        check(method, url, params)
        for attempt in range(retries + 1):
            wait = self._min - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self._s.request(method, url, params=params, json=json, timeout=120)
            except requests.RequestException as ex:  # its message includes the full URL (and any key in it)
                u = urlsplit(url)
                raise RuntimeError(f"{type(ex).__name__} calling {method} {u.hostname}{u.path}") from None
            if r.status_code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:  # never echo the URL: Semrush puts the API key in the query string
                u = urlsplit(url)
                raise RuntimeError(f"HTTP {r.status_code} from {method} {u.hostname}{u.path}: {r.text[:300]}")
            return r
        return r

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)
