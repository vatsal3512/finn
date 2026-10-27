"""HTTP layer: one polite client per site, with pacing, retries and clear failures.

Design notes
- Every site gets its own minimum gap between requests, so a full refresh never bursts.
- Transient failures (timeouts, 429, 5xx) are retried with exponential backoff and
  jitter. Anything else fails fast with the status code in the error.
- screener.in accepts a User-Agent that names this project, so we send that. NSE and BSE
  reject unknown clients, so for those two we send a standard browser User-Agent. We do
  not spoof TLS fingerprints or solve bot challenges: if an exchange blocks us, the
  caller falls back to the other exchange or to cached data.
"""

from __future__ import annotations

import logging
import threading
import time
from functools import cache
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

log = logging.getLogger(__name__)

PROJECT_UA = "FINN-prototype/0.1 (research project for the ENAM build challenge)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class TransientHTTPError(Exception):
    """A failure worth retrying: timeout, connection reset, 429 or 5xx."""


class HTTPError(Exception):
    """A failure not worth retrying, such as 403 or 404."""

    def __init__(self, url: str, status: int):
        super().__init__(f"HTTP {status} for {url}")
        self.url, self.status = url, status


class SiteClient:
    def __init__(
        self,
        name: str,
        *,
        user_agent: str,
        min_interval: float,
        headers: dict[str, str] | None = None,
        warmup_url: str | None = None,
        timeout: float = 30.0,
    ):
        self.name = name
        self.min_interval = min_interval
        self.timeout = timeout
        self.warmup_url = warmup_url
        self.requests_made = 0
        self._warmed = False
        self._last = 0.0
        self._lock = threading.Lock()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "*/*"})
        self.session.headers.update(headers or {})

    def _pace(self) -> None:
        with self._lock:
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests_made += 1

    def _warm(self) -> None:
        """Some sites set session cookies on their home page. Best effort only."""
        if self.warmup_url and not self._warmed:
            self._warmed = True
            try:
                self._pace()
                self.session.get(self.warmup_url, timeout=self.timeout)
            except requests.RequestException as exc:
                log.debug("%s warm-up failed: %s", self.name, exc)

    @retry(
        retry=retry_if_exception_type(TransientHTTPError),
        stop=stop_after_attempt(4),
        wait=wait_random_exponential(multiplier=1, max=20),
        reraise=True,
    )
    def get(self, url: str, params: dict[str, Any] | None = None, **kw: Any) -> requests.Response:
        self._warm()
        self._pace()
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout, **kw)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise TransientHTTPError(f"{self.name}: {exc}") from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise TransientHTTPError(f"{self.name}: HTTP {resp.status_code} for {resp.url}")
        if resp.status_code >= 400:
            raise HTTPError(resp.url, resp.status_code)
        return resp

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        # BSE refuses a bare "application/json"; this is the standard XHR Accept value.
        resp = self.get(url, params=params, headers={"Accept": "application/json, text/plain, */*"})
        try:
            return resp.json()
        except ValueError as exc:  # exchanges sometimes answer with an HTML error page
            raise TransientHTTPError(f"{self.name}: non-JSON reply from {resp.url}") from exc

    @retry(
        retry=retry_if_exception_type(TransientHTTPError),
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=2, max=20),
        reraise=True,
    )
    def get_bytes(self, url: str) -> bytes:
        """Download a file and refuse to return it truncated.

        NSE's archive server sometimes drops a transfer midway: one HDFC Bank results PDF
        declared 1,193,121 bytes and arrived as 983,040. So we check the byte count against
        Content-Length and that a PDF ends with its end-of-file marker, and retry if not.
        """
        resp = self.get(url)
        data = resp.content
        declared = resp.headers.get("Content-Length")
        encoded = resp.headers.get("Content-Encoding")
        if declared and not encoded and declared.isdigit() and len(data) < int(declared):
            raise TransientHTTPError(
                f"{self.name}: truncated download, {len(data)} of {declared} bytes"
            )
        if data[:5] == b"%PDF-" and b"%%EOF" not in data[-4096:]:
            raise TransientHTTPError(
                f"{self.name}: PDF has no end-of-file marker, likely truncated"
            )
        return data


@cache
def nse() -> SiteClient:
    return SiteClient(
        "nse",
        user_agent=BROWSER_UA,
        min_interval=0.8,
        headers={"Referer": "https://www.nseindia.com/"},
        warmup_url="https://www.nseindia.com/",
    )


@cache
def bse() -> SiteClient:
    return SiteClient(
        "bse",
        user_agent=BROWSER_UA,
        min_interval=0.8,
        # No Origin header: BSE's API answers 403 when one is sent.
        headers={"Referer": "https://www.bseindia.com/"},
    )


@cache
def screener() -> SiteClient:
    # A personal-use site: slow pacing, and every page is cached locally by the caller.
    return SiteClient("screener", user_agent=PROJECT_UA, min_interval=2.5)


@cache
def documents() -> SiteClient:
    """Company investor-relations sites and other hosts of primary documents."""
    return SiteClient("documents", user_agent=BROWSER_UA, min_interval=1.0, timeout=90.0)


def client_for(url: str) -> SiteClient:
    if "nseindia.com" in url:
        return nse()
    if "bseindia.com" in url:
        return bse()
    if "screener.in" in url:
        return screener()
    return documents()


def all_clients() -> list[SiteClient]:
    return [nse(), bse(), screener(), documents()]
