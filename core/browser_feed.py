"""Last-resort real-browser retrieval for feeds that normal HTTP cannot fetch.

SeleniumBase is imported lazily and is never involved in the normal refresh
path. The UC/CDP Chromium session always uses SeleniumBase's ``headless2``
mode so no browser window, taskbar button, or user interaction is exposed.

The entry point fails closed.  It returns a small requests-compatible response
only after the browser body has been structurally validated as RSS, Atom, CDF,
or JSON Feed; browser errors, ordinary HTML pages, and missing optional runtime
pieces all return ``None``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from core import config as config_mod


log = logging.getLogger(__name__)

_FETCH_LOCK = threading.Lock()
_RUNTIME_DIRNAME = "feed_browser_runtime"
_PROFILE_DIRNAME = "feed_browser_profile"
_MAX_PAGE_SOURCE_CHARS = 30 * 1024 * 1024
_RUNTIME_FAILURE_COOLDOWN_SECONDS = 300.0
_runtime_unavailable_until = 0.0

# A URL whose browser attempt genuinely ran and still produced no feed is not
# retried in the browser for this long. Refresh cycles over a large collection
# would otherwise pay the same serialized Chromium launch for the same failing
# feed on every cycle (issue #79 follow-up: a several-hundred-feed refresh went
# from ~9 to ~21 minutes). Only the refresh path (fetch_feed) records and
# honors this; user-initiated page detection must always be allowed to retry.
_NEGATIVE_RESULT_COOLDOWN_SECONDS = 6 * 3600.0
_MAX_NEGATIVE_RESULTS = 512
_negative_results: dict[str, float] = {}
_negative_results_lock = threading.Lock()


def _negative_result_active(url: str) -> bool:
    with _negative_results_lock:
        return time.monotonic() < _negative_results.get(url, 0.0)


def _record_negative_result(url: str) -> None:
    now = time.monotonic()
    with _negative_results_lock:
        if len(_negative_results) >= _MAX_NEGATIVE_RESULTS:
            for key in [k for k, until in _negative_results.items() if until <= now]:
                _negative_results.pop(key, None)
            if len(_negative_results) >= _MAX_NEGATIVE_RESULTS:
                _negative_results.clear()
        _negative_results[url] = now + _NEGATIVE_RESULT_COOLDOWN_SECONDS


def _clear_negative_result(url: str) -> None:
    with _negative_results_lock:
        _negative_results.pop(url, None)


def _local_name(tag) -> str:
    text = str(tag or "")
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text.lower()


def _looks_like_feed_text(text: str) -> bool:
    """Return True only for a structurally recognizable feed document."""
    body = str(text or "").lstrip("\ufeff\x00 \t\r\n")
    if not body:
        return False

    if body.startswith("{"):
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            return False
        if not isinstance(payload, dict):
            return False
        version = str(payload.get("version") or "")
        return version.startswith("https://jsonfeed.org/version/") and isinstance(
            payload.get("items", []), list
        )

    try:
        root = ET.fromstring(body)
    except (ET.ParseError, ValueError):
        return False
    return _local_name(root.tag) in {"rss", "rdf", "feed", "channel"}


def _feed_text_from_page_source(page_source: str) -> str | None:
    """Extract the raw feed text Chromium displays inside its ``pre`` wrapper."""
    source = str(page_source or "")
    if not source or len(source) > _MAX_PAGE_SOURCE_CHARS:
        return None
    if _looks_like_feed_text(source):
        return source

    try:
        soup = BeautifulSoup(source, "html.parser")
        pre = soup.find("pre")
        candidate = pre.get_text() if pre is not None else ""
    except Exception:
        return None
    return candidate if _looks_like_feed_text(candidate) else None


@dataclass
class BrowserPageResponse:
    """Minimal requests.Response-compatible value returned by browser fetches."""

    text: str
    url: str
    status_code: int = 200
    headers: dict = field(
        default_factory=lambda: {"Content-Type": "text/html; charset=utf-8"}
    )
    history: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.content = self.text.encode("utf-8")
        self.response = self

    def raise_for_status(self) -> None:
        return None


@dataclass
class BrowserFeedResponse(BrowserPageResponse):
    """Requests-compatible browser response containing a validated feed."""

    headers: dict = field(
        default_factory=lambda: {"Content-Type": "application/rss+xml; charset=utf-8"}
    )


def _looks_like_challenge_page(page_source: str) -> bool:
    """Recognize common browser-verification documents regardless of HTTP status."""
    text = str(page_source or "")[:200000].casefold()
    markers = (
        "challenges.cloudflare.com",
        "just a moment...",
        "_cf_chl_opt",
        "cf-chl-",
        "performing security verification",
        "verify you are human",
    )
    return any(marker in text for marker in markers)


def _google_chrome_available() -> bool:
    names = ("google-chrome", "google-chrome-stable", "chrome", "chrome.exe")
    if any(shutil.which(name) for name in names):
        return True

    candidates = []
    if sys.platform.startswith("win"):
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env_name)
            if base:
                candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    else:
        candidates.extend(("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"))
    return any(os.path.isfile(path) for path in candidates)


def _redirect_seleniumbase_work_files(runtime_dir: str) -> None:
    """Move SeleniumBase's cwd-relative locks/downloads into writable storage."""
    from seleniumbase.fixtures import constants as sb_constants

    work_dir = os.path.join(runtime_dir, "work")
    os.makedirs(work_dir, exist_ok=True)
    sb_constants.Files.DOWNLOADS_FOLDER = work_dir
    # These values are computed from Files.DOWNLOADS_FOLDER at import time, so
    # update the cached paths too. In an installed Windows build the process
    # cwd may be Program Files and must never receive runtime lock files.
    for group_name in ("MultiBrowser", "PipInstall", "Dashboard", "Report"):
        group = getattr(sb_constants, group_name, None)
        if group is None:
            continue
        for name, value in vars(group).items():
            if name.isupper() and isinstance(value, str) and value.endswith(".lock"):
                setattr(group, name, os.path.join(work_dir, os.path.basename(value)))


def _browser_options(profile_dir: str, timeout_s: float, proxy: str | None) -> dict:
    """Build mandatory fully automated, invisible SeleniumBase options."""
    options = {
        "uc": True,
        "headless2": True,
        "test": False,
        "locale": "en",
        "user_data_dir": profile_dir,
        "no_screenshot": True,
        "time_limit": timeout_s,
    }
    if not _google_chrome_available():
        options["cft"] = True
    if proxy:
        options["proxy"] = str(proxy).strip()
    return options


def _cancelled(cancel_event) -> bool:
    try:
        return bool(cancel_event and cancel_event.is_set())
    except Exception:
        return False


def _acquire_fetch_lock(timeout_s: float, cancel_event=None) -> bool:
    deadline = time.monotonic() + max(1.0, float(timeout_s or 1.0))
    while not _cancelled(cancel_event):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if _FETCH_LOCK.acquire(timeout=min(0.25, remaining)):
            return True
    return False


def _current_browser_url(sb, fallback: str) -> str:
    for getter in (
        lambda: sb.get_current_url(),
        lambda: sb.cdp.get_current_url(),
    ):
        try:
            value = str(getter() or "").strip()
            if value:
                return value
        except Exception:
            continue
    return fallback


def _fetch_browser_document(
    url: str,
    *,
    timeout_s: float = 90.0,
    proxy: str | None = None,
    cancel_event=None,
    feed_only: bool,
    remember_failures: bool = False,
) -> BrowserPageResponse | None:
    """Fetch a browser document, optionally requiring a validated feed.

    Calls are serialized because SeleniumBase's UC driver installer/cache and
    GUI challenge click are process-global.  The persistent per-user profile
    keeps clearance cookies between refreshes.  When Google Chrome is absent,
    SeleniumBase downloads Chrome-for-Testing into the writable BlindRSS data
    directory on the first fallback attempt.
    """
    global _runtime_unavailable_until

    target = str(url or "").strip()
    try:
        parts = urllib.parse.urlsplit(target)
    except Exception:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    if _cancelled(cancel_event) or time.monotonic() < _runtime_unavailable_until:
        return None
    if remember_failures and _negative_result_active(target):
        log.info("Skipping automated browser fetch during failure cooldown url=%s", target)
        return None

    timeout_s = max(15.0, min(float(timeout_s or 90.0), 180.0))
    if not _acquire_fetch_lock(timeout_s, cancel_event=cancel_event):
        return None

    try:
        if _cancelled(cancel_event):
            return None
        try:
            from seleniumbase import SB
            from seleniumbase.core import browser_launcher
        except Exception:
            log.warning("Browser feed fallback is unavailable because SeleniumBase could not be imported")
            _runtime_unavailable_until = time.monotonic() + _RUNTIME_FAILURE_COOLDOWN_SECONDS
            return None

        data_dir = config_mod.get_data_dir()
        runtime_dir = os.path.join(data_dir, _RUNTIME_DIRNAME)
        profile_dir = os.path.join(data_dir, _PROFILE_DIRNAME)
        try:
            os.makedirs(runtime_dir, exist_ok=True)
            os.makedirs(profile_dir, exist_ok=True)
            browser_launcher.override_driver_dir(runtime_dir)
            _redirect_seleniumbase_work_files(runtime_dir)
        except OSError:
            log.exception("Could not prepare the browser feed fallback directories")
            _runtime_unavailable_until = time.monotonic() + _RUNTIME_FAILURE_COOLDOWN_SECONDS
            return None

        options = _browser_options(profile_dir, timeout_s, proxy)

        log.info("Attempting automated browser feed fallback url=%s", target)
        try:
            with SB(**options) as sb:
                sb.activate_cdp_mode(target)
                for attempt in range(3):
                    if _cancelled(cancel_event):
                        return None
                    sb.sleep(2 if attempt == 0 else 3)
                    source = str(sb.get_page_source() or "")
                    if feed_only:
                        text = _feed_text_from_page_source(source)
                    else:
                        text = (
                            source
                            if source
                            and len(source) <= _MAX_PAGE_SOURCE_CHARS
                            and not _looks_like_challenge_page(source)
                            else None
                        )
                    if text is not None:
                        final_url = _current_browser_url(sb, target)
                        log.info(
                            "Automated browser %s fallback succeeded bytes=%s url=%s",
                            "feed" if feed_only else "page",
                            len(text.encode("utf-8")),
                            final_url,
                        )
                        _clear_negative_result(target)
                        response_type = BrowserFeedResponse if feed_only else BrowserPageResponse
                        return response_type(text=text, url=final_url)
                    # This is fully automated. solve_captcha() is a no-op when
                    # there is no supported challenge on the current page.
                    sb.solve_captcha()
        except Exception:
            log.exception("Automated browser feed fallback failed for %s", target)
            if remember_failures and not _cancelled(cancel_event):
                _record_negative_result(target)
            return None

        log.info(
            "Automated browser fallback returned no usable %s url=%s",
            "feed" if feed_only else "page",
            target,
        )
        if remember_failures:
            _record_negative_result(target)
        return None
    finally:
        _FETCH_LOCK.release()


def fetch_feed(
    url: str,
    *,
    timeout_s: float = 90.0,
    proxy: str | None = None,
    cancel_event=None,
) -> BrowserFeedResponse | None:
    """Fetch a feed through the browser and return it only after validation.

    Attempts that genuinely ran the browser and still produced no feed start a
    per-URL cooldown so refresh cycles do not repeat the launch back to back.
    """
    response = _fetch_browser_document(
        url,
        timeout_s=timeout_s,
        proxy=proxy,
        cancel_event=cancel_event,
        feed_only=True,
        remember_failures=True,
    )
    return response if isinstance(response, BrowserFeedResponse) else None


def fetch_page(
    url: str,
    *,
    timeout_s: float = 90.0,
    proxy: str | None = None,
    cancel_event=None,
    remember_failures: bool = False,
) -> BrowserPageResponse | None:
    """Fetch a webpage after automatically completing a browser challenge.

    ``remember_failures`` starts the per-URL cooldown on a genuine failure, for
    repeating callers (full-text extraction) that would otherwise pay the
    serialized Chromium launch again for a permanently blocked page. It stays
    off for one-shot, user-initiated detection, which must always retry.
    """
    return _fetch_browser_document(
        url,
        timeout_s=timeout_s,
        proxy=proxy,
        cancel_event=cancel_event,
        feed_only=False,
        remember_failures=remember_failures,
    )
