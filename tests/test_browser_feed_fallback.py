"""Automated real-browser feed fallback tests."""

import os
import tempfile
import uuid

import requests

import core.db
from core import browser_feed
import providers.local as local_mod
from providers.local import LocalProvider


_RSS_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Browser Fallback Feed</title>
    <item>
      <guid>browser-item-1</guid>
      <title>Recovered item</title>
      <link>https://example.com/recovered</link>
      <description>Recovered through the browser.</description>
    </item>
  </channel>
</rss>
"""

_HTML = "<!doctype html><html><head><title>Blocked</title></head><body>No feed</body></html>"


class _Response:
    def __init__(self, text, status=200, content_type="text/html"):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.url = "https://example.com/feed.xml"
        self.history = []
        self.response = self

    def raise_for_status(self):
        if self.status_code >= 400:
            exc = requests.HTTPError(f"{self.status_code} error")
            exc.response = self
            raise exc


def _insert_feed(url="https://example.com/feed.xml"):
    feed_id = str(uuid.uuid4())
    conn = core.db.get_connection()
    try:
        conn.execute("DELETE FROM articles")
        conn.execute("DELETE FROM feeds")
        conn.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (feed_id, url, "Browser fallback test", "Tests", ""),
        )
        conn.commit()
    finally:
        conn.close()
    return feed_id


def _provider(enabled=True):
    return LocalProvider(
        {
            "providers": {"local": {}},
            "feed_timeout_seconds": 2,
            "feed_retry_attempts": 0,
            "browser_feed_fallback_enabled": enabled,
            "browser_feed_fallback_timeout_seconds": 45,
        }
    )


def test_extracts_chromium_pre_wrapped_rss():
    wrapped = (
        '<html><head></head><body><pre style="word-wrap: break-word">'
        + _RSS_XML.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        + "</pre></body></html>"
    )
    assert browser_feed._feed_text_from_page_source(wrapped) == _RSS_XML


def test_feed_validation_accepts_json_feed_and_rejects_html():
    assert browser_feed._looks_like_feed_text(
        '{"version":"https://jsonfeed.org/version/1.1","items":[]}'
    )
    assert not browser_feed._looks_like_feed_text(_HTML)
    assert browser_feed._feed_text_from_page_source(
        "<html><body><pre>ordinary text</pre></body></html>"
    ) is None


def test_browser_options_are_fully_automatic_and_invisible(monkeypatch):
    monkeypatch.setattr(browser_feed, "_google_chrome_available", lambda: False)

    options = browser_feed._browser_options("profile", 45.0, None)

    assert options["uc"] is True
    assert options["headless2"] is True
    assert options["test"] is False
    assert options["no_screenshot"] is True
    assert options["cft"] is True


def test_http_error_uses_browser_fallback_once(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(enabled=True)
            feed_id = _insert_feed()
            browser_calls = []

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(
                local_mod.utils,
                "safe_requests_get",
                lambda *_a, **_k: _Response(_HTML, status=403),
            )

            def _browser_fetch(url, **kwargs):
                browser_calls.append((url, kwargs))
                return browser_feed.BrowserFeedResponse(_RSS_XML, url)

            monkeypatch.setattr(local_mod.browser_feed_mod, "fetch_feed", _browser_fetch)

            assert provider.refresh_feed(feed_id) is True
            assert len(browser_calls) == 1
            assert browser_calls[0][1]["timeout_s"] == 45
            articles = provider.get_articles(feed_id=feed_id)
            assert len(articles) == 1
            assert articles[0].title == "Recovered item"
        finally:
            core.db.DB_FILE = old_db


def test_html_success_response_also_uses_browser_fallback(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(enabled=True)
            feed_id = _insert_feed()
            browser_calls = []

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(
                local_mod.utils,
                "safe_requests_get",
                lambda *_a, **_k: _Response(_HTML, status=200),
            )
            monkeypatch.setattr(
                local_mod.browser_feed_mod,
                "fetch_feed",
                lambda url, **_k: browser_calls.append(url)
                or browser_feed.BrowserFeedResponse(_RSS_XML, url),
            )

            assert provider.refresh_feed(feed_id) is True
            assert browser_calls == ["https://example.com/feed.xml"]
            assert len(provider.get_articles(feed_id=feed_id)) == 1
        finally:
            core.db.DB_FILE = old_db


def test_malformed_feed_response_uses_browser_fallback(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(enabled=True)
            feed_id = _insert_feed()
            browser_calls = []

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(
                local_mod.utils,
                "safe_requests_get",
                lambda *_a, **_k: _Response(
                    "<rss><channel>",
                    status=200,
                    content_type="application/rss+xml",
                ),
            )
            monkeypatch.setattr(
                local_mod.browser_feed_mod,
                "fetch_feed",
                lambda url, **_k: browser_calls.append(url)
                or browser_feed.BrowserFeedResponse(_RSS_XML, url),
            )

            assert provider.refresh_feed(feed_id) is True
            assert browser_calls == ["https://example.com/feed.xml"]
            assert len(provider.get_articles(feed_id=feed_id)) == 1
        finally:
            core.db.DB_FILE = old_db


def test_partial_config_keeps_browser_fallback_disabled(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "feed_timeout_seconds": 2,
                    "feed_retry_attempts": 0,
                }
            )
            feed_id = _insert_feed()
            states = []

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(
                local_mod.utils,
                "safe_requests_get",
                lambda *_a, **_k: _Response(_HTML, status=403),
            )
            monkeypatch.setattr(
                local_mod.browser_feed_mod,
                "fetch_feed",
                lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not launch")),
            )

            assert provider.refresh_feed(feed_id, progress_cb=states.append) is True
            assert states[-1]["status"] == "error"
        finally:
            core.db.DB_FILE = old_db
