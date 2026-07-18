"""Per-site cookie jar for challenge-protected sites (issue #79)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core import site_cookies


_JAR = (
    "# Netscape HTTP Cookie File\n"
    ".forum.audiogames.net\tTRUE\t/\tTRUE\t9999999999\tcf_clearance\tabc.123\n"
    "#HttpOnly_.forum.audiogames.net\tTRUE\t/\tTRUE\t9999999999\t__cfsid\txyz\n"
    "forum.audiogames.net\tFALSE\t/\tFALSE\t0\tphpbb_sess\tzzz\n"
    ".expired.example\tTRUE\t/\tTRUE\t1000000000\told\tgone\n"
    ".other.example\tTRUE\t/api\tTRUE\t9999999999\tscoped\tpathy\n"
)


@pytest.fixture(autouse=True)
def _jar(tmp_path, monkeypatch):
    jar = tmp_path / site_cookies.JAR_FILENAME
    jar.write_text(_JAR, encoding="utf-8")
    monkeypatch.setattr(site_cookies.config_mod, "get_data_dir", lambda: str(tmp_path))
    site_cookies._invalidate()
    yield tmp_path
    site_cookies._invalidate()


def test_cookie_header_matches_domain_and_subdomains():
    header = site_cookies.cookie_header_for(
        "https://forum.audiogames.net/feed/rss/", now=2000000000
    )
    assert "cf_clearance=abc.123" in header
    assert "__cfsid=xyz" in header
    assert "phpbb_sess=zzz" in header


def test_no_cookies_for_unrelated_host():
    assert site_cookies.cookie_header_for("https://example.com/", now=2000000000) == ""
    # audiogames.net (parent of the cookie domain) must NOT match either.
    assert site_cookies.cookie_header_for("https://audiogames.net/", now=2000000000) == ""


def test_expired_cookies_are_dropped():
    assert site_cookies.cookie_header_for("https://expired.example/", now=2000000000) == ""


def test_path_scoping():
    assert site_cookies.cookie_header_for("https://other.example/", now=2000000000) == ""
    assert "scoped=pathy" in site_cookies.cookie_header_for(
        "https://other.example/api/things", now=2000000000
    )


def test_user_agent_only_for_cookie_domains(tmp_path):
    site_cookies.set_user_agent("Mozilla/5.0 TestBrowser")
    assert site_cookies.user_agent_for("https://forum.audiogames.net/x", now=2000000000) == "Mozilla/5.0 TestBrowser"
    assert site_cookies.user_agent_for("https://example.com/", now=2000000000) == ""
    site_cookies.set_user_agent("")
    assert site_cookies.user_agent_for("https://forum.audiogames.net/x", now=2000000000) == ""


def test_challenge_detection():
    body = '<title>Just a moment...</title><script src="https://challenges.cloudflare.com/x"></script>'
    assert site_cookies.looks_like_challenge_response(403, body)
    assert not site_cookies.looks_like_challenge_response(200, body)
    assert not site_cookies.looks_like_challenge_response(403, "<html>plain forbidden</html>")


def test_import_jar_validates(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello world", encoding="utf-8")
    with pytest.raises(ValueError):
        site_cookies.import_jar(str(bad))
    good = tmp_path / "export.txt"
    good.write_text(_JAR, encoding="utf-8")
    dest = site_cookies.import_jar(str(good))
    assert os.path.basename(dest) == site_cookies.JAR_FILENAME
