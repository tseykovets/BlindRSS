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

import configparser
import glob as glob_mod
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.parse

from core import config as config_mod
from core.cookies_import import _read_text, is_netscape_cookie_jar, _iter_cookie_records

log = logging.getLogger(__name__)

JAR_FILENAME = "site_cookies.txt"
UA_FILENAME = "site_cookies_ua.txt"

_lock = threading.Lock()
_write_lock = threading.Lock()
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
    """Merge a validated export into the managed site jar.

    Merging (rather than replacing) means importing cookies for a second site
    never wipes the first site's imported session.
    """
    merge_jar_file(src_path)
    return jar_path()


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


# ---------------------------------------------------------------------------
# Direct browser import (Firefox family)
#
# Firefox-based browsers keep cookies in an UNENCRYPTED profile SQLite
# (cookies.sqlite), so they can be read directly. Chromium browsers on
# Windows use App-Bound Encryption since v127 — unreadable from outside the
# browser — which is why the dialog points Chrome users at the
# "Get cookies.txt LOCALLY" extension instead.
# ---------------------------------------------------------------------------

def _firefox_like_roots():
    """[(browser label, root dir)] for every Firefox-family browser we know."""
    roots = []
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            roots = [
                ("Firefox", os.path.join(appdata, "Mozilla", "Firefox")),
                ("LibreWolf", os.path.join(appdata, "librewolf")),
                ("Waterfox", os.path.join(appdata, "Waterfox")),
                ("Floorp", os.path.join(appdata, "Floorp")),
                ("Zen Browser", os.path.join(appdata, "zen")),
                ("Pale Moon", os.path.join(appdata, "Moonchild Productions", "Pale Moon")),
                ("Thunderbird", os.path.join(appdata, "Thunderbird")),
            ]
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
        roots = [
            ("Firefox", os.path.join(base, "Firefox")),
            ("LibreWolf", os.path.join(base, "librewolf")),
            ("Waterfox", os.path.join(base, "Waterfox")),
            ("Floorp", os.path.join(base, "Floorp")),
            ("Zen Browser", os.path.join(base, "zen")),
        ]
    else:
        home = os.path.expanduser("~")
        roots = [
            ("Firefox", os.path.join(home, ".mozilla", "firefox")),
            ("Firefox (Flatpak)", os.path.join(home, ".var", "app", "org.mozilla.firefox", ".mozilla", "firefox")),
            ("Firefox (Snap)", os.path.join(home, "snap", "firefox", "common", ".mozilla", "firefox")),
            ("LibreWolf", os.path.join(home, ".librewolf")),
            ("Waterfox", os.path.join(home, ".waterfox")),
            ("Floorp", os.path.join(home, ".floorp")),
        ]
    return [(label, root) for label, root in roots if os.path.isdir(root)]


def list_browser_profiles():
    """Importable browser profiles, newest cookie database first.

    Returns ``[{"browser", "profile", "path", "mtime"}]`` where ``path`` is
    the profile directory containing cookies.sqlite.
    """
    found = []
    seen = set()
    for label, root in _firefox_like_roots():
        candidates = glob_mod.glob(os.path.join(root, "Profiles", "*", "cookies.sqlite"))
        candidates += glob_mod.glob(os.path.join(root, "*", "cookies.sqlite"))
        for db in candidates:
            profile_dir = os.path.dirname(os.path.abspath(db))
            if profile_dir.lower() in seen:
                continue
            seen.add(profile_dir.lower())
            try:
                mtime = os.path.getmtime(db)
            except OSError:
                continue
            found.append({
                "browser": label,
                "profile": os.path.basename(profile_dir),
                "path": profile_dir,
                "mtime": mtime,
            })
    found.sort(key=lambda item: item["mtime"], reverse=True)
    return found


def _read_firefox_cookies(profile_dir: str):
    """moz_cookies rows as (host, path, secure, http_only, expiry, name, value).

    The live database is locked (and WAL-buffered) while the browser runs, so
    the db + sidecar files are copied to a temp dir and read from the copy.
    """
    src = os.path.join(profile_dir, "cookies.sqlite")
    if not os.path.isfile(src):
        raise OSError("cookies.sqlite not found")
    tmp_dir = tempfile.mkdtemp(prefix="blindrss-cookies-")
    try:
        dst = os.path.join(tmp_dir, "cookies.sqlite")
        shutil.copyfile(src, dst)
        for suffix in ("-wal", "-shm"):
            side = src + suffix
            if os.path.isfile(side):
                try:
                    shutil.copyfile(side, dst + suffix)
                except OSError:
                    pass
        conn = sqlite3.connect(dst)
        try:
            rows = conn.execute(
                "SELECT host, path, isSecure, isHttpOnly, expiry, name, value "
                "FROM moz_cookies"
            ).fetchall()
        finally:
            conn.close()
        out = []
        for host, path, secure, http_only, expiry, name, value in rows:
            host = str(host or "").strip()
            name = str(name or "")
            if host and name:
                out.append((host, str(path or "/"), bool(secure), bool(http_only),
                            int(expiry or 0), name, str(value or "")))
        return out
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def firefox_profile_user_agent(profile_dir: str) -> str:
    """A User-Agent string matching the profile's browser version, or "".

    Gecko UAs are fully derivable from the major version in the profile's
    compatibility.ini, and Cloudflare needs the UA to match the session the
    cookies came from.
    """
    ini = os.path.join(profile_dir, "compatibility.ini")
    version = ""
    try:
        parser = configparser.ConfigParser()
        parser.read(ini, encoding="utf-8")
        raw = parser.get("Compatibility", "LastVersion", fallback="")
        version = raw.split("_", 1)[0].split(".", 1)[0].strip()
    except Exception:
        version = ""
    if not version.isdigit():
        return ""
    if sys.platform.startswith("win"):
        platform_token = "Windows NT 10.0; Win64; x64"
    elif sys.platform == "darwin":
        platform_token = "Macintosh; Intel Mac OS X 10.15"
    else:
        platform_token = "X11; Linux x86_64"
    return (
        f"Mozilla/5.0 ({platform_token}; rv:{version}.0) "
        f"Gecko/20100101 Firefox/{version}.0"
    )


def _jar_records():
    """Raw (domain_field, flag, path, secure, expiry, name, value) rows of the managed jar."""
    text = _read_text(jar_path()) or ""
    records = []
    for fields in _iter_cookie_records(text):
        records.append(tuple(fields[:7]))
    return records


def _record_key(fields):
    domain_field = str(fields[0])
    key_domain = domain_field.replace("#HttpOnly_", "", 1).lstrip(".").lower()
    return (key_domain, fields[2], fields[5])


def _merge_records_into_jar(new_records) -> None:
    """Write the managed jar as (existing records) overridden by new_records.

    Existing entries for the same (domain, path, name) are replaced;
    everything else is kept, so importing from a second browser or for a
    second site never wipes an earlier import.
    """
    dest = jar_path()
    dest_dir = os.path.dirname(dest)
    os.makedirs(dest_dir, exist_ok=True)
    temp_path = ""
    with _write_lock:
        merged = {}
        for fields in _jar_records():
            merged[_record_key(fields)] = fields
        for fields in new_records:
            merged[_record_key(fields)] = fields
        fd, temp_path = tempfile.mkstemp(prefix="site-cookies-", suffix=".tmp", dir=dest_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("# Netscape HTTP Cookie File\n")
                fh.write("# Imported by BlindRSS (Import Site Cookies)\n\n")
                for record in merged.values():
                    fh.write("\t".join(str(f) for f in record) + "\n")
            os.replace(temp_path, dest)
            temp_path = ""
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
    _invalidate()


def merge_jar_file(src_path: str) -> int:
    """Merge a Netscape cookies.txt export into the managed jar.

    Returns the number of records read from the export. Raises ValueError for
    files that are not a cookie jar.
    """
    ok, message = validate_jar_file(src_path)
    if not ok:
        raise ValueError(message)
    text = _read_text(src_path) or ""
    new_records = [tuple(fields[:7]) for fields in _iter_cookie_records(text)]
    _merge_records_into_jar(new_records)
    return len(new_records)


def import_from_browser_profile(profile_dir: str) -> int:
    """Merge a Firefox-family profile's cookies into the managed jar.

    Returns the number of cookies read from the browser.
    """
    rows = _read_firefox_cookies(profile_dir)
    new_records = []
    for host, path, secure, http_only, expiry, name, value in rows:
        domain_field = ("#HttpOnly_" + host) if http_only else host
        flag = "TRUE" if host.startswith(".") else "FALSE"
        new_records.append((
            domain_field, flag, path,
            "TRUE" if secure else "FALSE",
            str(int(expiry)), name, value,
        ))
    _merge_records_into_jar(new_records)
    return len(rows)


def auto_import_downloads(config_manager, *, search_dirs=None, now=None):
    """Auto-import a freshly exported cookies.txt from Downloads (hands-free).

    Mirrors the YouTube cookie auto-import: any Netscape jar the user just
    exported (e.g. ``chromewebstore.google.com_cookies.txt`` from the
    "Get cookies.txt LOCALLY" extension) is merged into the site jar, so a
    challenge-protected site starts working without opening any dialog.
    Returns the imported source path, or None. Gated by the same
    ``auto_import_browser_cookies`` setting as the YouTube flow, and by a
    persisted mtime (``site_cookies_last_import_mtime``) so the same export
    is never merged twice.
    """
    from core import cookies_import

    try:
        if not bool(config_manager.get("auto_import_browser_cookies", True)):
            return None
    except Exception:
        return None
    try:
        last_mtime = float(config_manager.get("site_cookies_last_import_mtime", 0) or 0)
    except (TypeError, ValueError):
        last_mtime = 0.0

    now_ts = time.time() if now is None else now
    cutoff = max(now_ts - cookies_import.DEFAULT_MAX_AGE_S, last_mtime)
    dirs = search_dirs if search_dirs is not None else cookies_import.default_download_dirs()

    managed = {os.path.abspath(jar_path()).lower()}
    best_path = None
    best_mtime = -1.0
    for d in dirs or []:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith(".txt"):
                continue
            if name.lower() == cookies_import.IMPORTED_COOKIE_FILENAME.lower():
                continue
            path = os.path.join(d, name)
            if os.path.abspath(path).lower() in managed:
                continue
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime <= cutoff or mtime <= best_mtime:
                continue
            ok, _msg = validate_jar_file(path)
            if ok:
                best_path = path
                best_mtime = mtime
    if not best_path:
        return None

    try:
        merge_jar_file(best_path)
    except (ValueError, OSError) as exc:
        log.debug("Site cookie auto-import skipped (%s): %s", best_path, exc)
        return None
    try:
        config_manager.set("site_cookies_last_import_mtime", best_mtime)
    except Exception:
        log.exception("Failed to persist site cookie auto-import state")
        return None
    log.info("Auto-imported site cookies from %s", best_path)
    return best_path


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
