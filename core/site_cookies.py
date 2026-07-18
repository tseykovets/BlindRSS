"""Per-site cookie jar for the HTTP fetch layer (issue #79).

Sites behind an interactive bot check (Cloudflare's "Just a moment..."
interstitial, as on forum.audiogames.net) cannot be fetched by any plain HTTP
client — the challenge requires real JavaScript in a real browser, and TLS
impersonation alone never passes it. The workable client-side approach is to
reuse a browser session that already passed the challenge: the user exports a
Netscape cookies.txt from their browser (same extension workflow as the
YouTube cookie import) and imports it via Tools > Import Site Cookies. Every
``safe_requests_*`` call then attaches the matching cookies (e.g.
``cf_clearance``) — and the browser's own User-Agent string, because
Cloudflare only accepts a clearance cookie together with the exact UA it was
issued to.

The jar lives in the app data dir as ``site_cookies.txt`` with the browser UA
in a ``site_cookies_ua.txt`` sidecar, so this module needs no config-manager
plumbing and stays importable from ``core.utils`` without cycles.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import urllib.parse

from core import config as config_mod
from core.cookies_import import _read_text, is_netscape_cookie_jar, _iter_cookie_records

log = logging.getLogger(__name__)

JAR_FILENAME = "site_cookies.txt"
UA_FILENAME = "site_cookies_ua.txt"

_lock = threading.Lock()
_cache = {"path": None, "mtime": None, "cookies": [], "ua_mtime": None, "ua": ""}


def jar_path() -> str:
    return os.path.join(config_mod.get_data_dir(), JAR_FILENAME)


def ua_path() -> str:
    return os.path.join(config_mod.get_data_dir(), UA_FILENAME)


def validate_jar_file(path: str) -> tuple[bool, str]:
    """Return (ok, message) for a user-picked cookies.txt (any domains)."""
    if not path or not os.path.isfile(path):
        return False, "File not found."
    text = _read_text(path)
    if text is None:
        return False, "Could not read the file (too large or unreadable)."
    if not is_netscape_cookie_jar(text):
        return False, "This does not look like a Netscape cookies.txt export."
    return True, "Looks like a valid cookie export."


def import_jar(src_path: str) -> str:
    """Copy a validated jar into the data dir as the managed site jar."""
    ok, message = validate_jar_file(src_path)
    if not ok:
        raise ValueError(message)
    dest = jar_path()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.abspath(src_path) != os.path.abspath(dest):
        shutil.copyfile(src_path, dest)
    _invalidate()
    return dest


def set_user_agent(ua: str) -> None:
    """Persist (or clear) the browser User-Agent the cookies belong to."""
    ua = str(ua or "").strip()
    path = ua_path()
    try:
        if ua:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(ua + "\n")
        elif os.path.isfile(path):
            os.remove(path)
    except OSError:
        log.exception("Could not persist site-cookies User-Agent")
    _invalidate()


def get_user_agent() -> str:
    try:
        with open(ua_path(), "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _invalidate() -> None:
    with _lock:
        _cache["mtime"] = None
        _cache["ua_mtime"] = None


def _parse_jar(text: str):
    """[(domain, include_subdomains, path, name, value, expires), ...]"""
    out = []
    for fields in _iter_cookie_records(text):
        domain = fields[0].lstrip("#")
        if domain.startswith("HttpOnly_"):
            domain = domain[len("HttpOnly_"):]
        raw_domain = domain.strip().lower()
        include_sub = raw_domain.startswith(".") or fields[1].strip().upper() == "TRUE"
        domain_clean = raw_domain.lstrip(".")
        cookie_path = fields[2].strip() or "/"
        try:
            expires = int(fields[4].strip() or 0)
        except ValueError:
            expires = 0
        name = fields[5]
        value = fields[6]
        if domain_clean and name:
            out.append((domain_clean, include_sub, cookie_path, name, value, expires))
    return out


def _load_cookies():
    path = jar_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []
    with _lock:
        if _cache["path"] == path and _cache["mtime"] == mtime:
            return _cache["cookies"]
    text = _read_text(path) or ""
    cookies = _parse_jar(text) if is_netscape_cookie_jar(text) else []
    with _lock:
        _cache.update({"path": path, "mtime": mtime, "cookies": cookies})
    return cookies


def _host_matches(host: str, domain: str, include_sub: bool) -> bool:
    if host == domain:
        return True
    return include_sub and host.endswith("." + domain)


def cookies_for(url: str, *, now: float | None = None) -> dict:
    """Unexpired jar cookies applicable to ``url`` as an ordered name->value map."""
    try:
        parts = urllib.parse.urlsplit(str(url or ""))
        host = (parts.hostname or "").lower()
        req_path = parts.path or "/"
    except Exception:
        return {}
    if not host:
        return {}
    now_ts = time.time() if now is None else now
    matched = {}
    for domain, include_sub, cookie_path, name, value, expires in _load_cookies():
        if not _host_matches(host, domain, include_sub):
            continue
        if expires and expires < now_ts:
            continue
        if cookie_path not in ("", "/") and not (
            req_path == cookie_path or req_path.startswith(cookie_path.rstrip("/") + "/")
        ):
            continue
        matched[name] = value
    return matched


def cookie_header_for(url: str, *, now: float | None = None) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies_for(url, now=now).items())


def user_agent_for(url: str, *, now: float | None = None) -> str:
    """The imported browser UA — only for sites the jar has cookies for.

    Scoped this way so importing cookies for one challenge-protected forum
    never changes the fingerprint of every other request the app makes.
    """
    if not cookies_for(url, now=now):
        return ""
    return get_user_agent()


# Markers that identify a bot-verification interstitial rather than content.
_CHALLENGE_MARKERS = (
    "challenges.cloudflare.com",
    "cf-mitigated",
    "Just a moment...",
    "_cf_chl_opt",
    "Performing security verification",
)


def looks_like_challenge_response(status_code: int, body: str) -> bool:
    """True when a response is a bot-check interstitial, not real content."""
    if status_code not in (401, 403, 503):
        return False
    text = str(body or "")[:20000]
    return any(marker in text for marker in _CHALLENGE_MARKERS)
