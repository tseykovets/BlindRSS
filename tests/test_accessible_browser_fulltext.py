"""Full-text extraction in the macOS accessible browser.

On macOS with VoiceOver the AccessibleBrowserFrame is the primary reading surface
(auto-opened from MainFrame). Before this wiring it only ever showed the raw feed
snippet, so "full text" did nothing on macOS. These tests cover both the GUI-free
body extractor and the frame's background load/apply pipeline.
"""

from types import SimpleNamespace

import pytest

from core import article_extractor
from core import utils as core_utils
from gui.accessibility import extract_article_body


# --------------------------------------------------------------------------- #
# GUI-free body extractor
# --------------------------------------------------------------------------- #

def test_extract_body_uses_web_when_longer_than_feed(monkeypatch):
    # Truncated feed (e.g. Neowin) + a full web article -> use the web full text.
    monkeypatch.setattr(
        article_extractor,
        "extract_full_article",
        lambda url, **kw: SimpleNamespace(text="WEB FULL ARTICLE BODY " * 50),
    )
    article = SimpleNamespace(
        url="https://example.com/post", content="<p>short feed snippet</p>",
        title="T", author="A",
    )
    body, cacheable = extract_article_body(article)
    assert body.startswith("WEB FULL ARTICLE BODY")
    assert cacheable is True  # real web full text is authoritative


def test_extract_body_keeps_feed_when_web_is_shorter(monkeypatch):
    # THE bug this whole episode chased: web extraction returned LESS than the feed
    # already had (e.g. fraservalleytoday feed_len=1886 vs web=672). We must NOT downgrade
    # the user below the feed — keep the longer feed body.
    calls = []

    def _short_web(url, **kw):
        calls.append(url)
        return SimpleNamespace(text="tiny partial web result")  # short

    monkeypatch.setattr(article_extractor, "extract_full_article", _short_web)
    full_feed = "This is a complete feed article paragraph. " * 40  # ~1700 chars
    article = SimpleNamespace(
        url="https://example.com/post",
        content=f"<article><p>{full_feed}</p></article>",
        title="T", author="A",
    )
    body, cacheable = extract_article_body(article)
    assert calls == ["https://example.com/post"]  # web WAS attempted
    assert "complete feed article paragraph" in body  # feed kept
    assert "tiny partial web result" not in body      # not downgraded to the shorter web text
    assert len(body) > 1000
    assert cacheable is True  # feed beat a working web fetch -> stable, cache it


def test_extract_body_uses_provider_when_web_and_feed_are_short(monkeypatch):
    # Paywalled/anti-bot site: web scrape returns a stub and the feed is tiny, but the
    # provider's server-side fetch (Miniflux fetch-content) returns the full article.
    monkeypatch.setattr(
        article_extractor, "extract_full_article",
        lambda url, **kw: SimpleNamespace(text="short stub from paywall"),
    )
    calls = []

    def _provider_fetch(article_id, url):
        calls.append((article_id, url))
        return "<article><p>" + ("Full provider-fetched article body. " * 60) + "</p></article>"

    article = SimpleNamespace(
        id="42", url="https://www.ft.com/content/abc", content="<p>tiny feed</p>",
        title="T", author="A",
    )
    body, cacheable = extract_article_body(article, provider_fetch=_provider_fetch)
    assert calls == [("42", "https://www.ft.com/content/abc")]
    assert "Full provider-fetched article body" in body
    assert cacheable is True


def test_extract_body_skips_provider_when_web_is_already_full(monkeypatch):
    # When client-side web extraction already yields a full-length article, don't bother
    # the provider (avoids hammering the Miniflux server for articles we already have).
    monkeypatch.setattr(
        article_extractor, "extract_full_article",
        lambda url, **kw: SimpleNamespace(text="WEB FULL ARTICLE BODY " * 120),  # well over the gate
    )
    calls = []
    article = SimpleNamespace(
        id="9", url="https://example.com/post", content="<p>short feed</p>", title="T", author="A",
    )
    body, cacheable = extract_article_body(article, provider_fetch=lambda *a: calls.append(a))
    assert calls == []  # provider not consulted when web extraction is already full
    assert body.startswith("WEB FULL ARTICLE BODY")
    assert cacheable is True


def test_extract_body_never_shorter_than_the_snippet(monkeypatch):
    # The reader pane first shows html_to_text(content) as the snippet. trafilatura's
    # extract_from_html sometimes drops the lead and returns LESS than that snippet, and a
    # short web scrape is shorter still; the full-text result must never come out shorter
    # than the snippet the user already heard (that reads as "full text made it shorter").
    monkeypatch.setattr(
        article_extractor, "extract_full_article",
        lambda url, **kw: SimpleNamespace(text="short web stub"),
    )
    monkeypatch.setattr(
        article_extractor, "extract_from_html",
        lambda html, url="", **kw: SimpleNamespace(text="cleaned but truncated body"),
    )
    full_snippet = "Full article opening that trafilatura dropped. " * 40
    monkeypatch.setattr(core_utils, "html_to_text", lambda html, **kw: full_snippet)

    article = SimpleNamespace(
        url="https://example.com/post", content="<p>x</p>", title="T", author="A",
    )
    body, cacheable = extract_article_body(article)
    assert body == full_snippet.strip()  # the fuller raw-feed snippet wins, not the truncated extract
    assert "cleaned but truncated body" not in body


def test_extract_body_web_total_failure_is_not_cacheable(monkeypatch):
    # A total web failure falls back to feed content, but that result is a (possibly
    # transient) failure and must NOT be cached, so the next visit retries.
    def _boom(url, **kw):
        raise article_extractor.ExtractionError("blocked")

    monkeypatch.setattr(article_extractor, "extract_full_article", _boom)
    body_text = "Long feed body sentence number one. " * 8
    article = SimpleNamespace(
        url="https://example.com/post",
        content=f"<article><p>{body_text}</p></article>",
        title="T", author="A",
    )
    body, cacheable = extract_article_body(article)
    assert body and "Long feed body sentence" in body
    assert cacheable is False  # transient web failure must retry next time


def test_extract_body_skips_web_for_media_url(monkeypatch):
    calls = []

    def _track(url, **kw):
        calls.append(url)
        return SimpleNamespace(text="should not be used")

    monkeypatch.setattr(article_extractor, "extract_full_article", _track)
    feed_text = "Episode description paragraph text here. " * 6
    article = SimpleNamespace(
        url="https://example.com/ep1.mp3",
        content=f"<p>{feed_text}</p>", title="", author="",
    )
    body, cacheable = extract_article_body(article)
    assert calls == []  # media URL must not trigger a web scrape
    assert body and "Episode description" in body
    assert cacheable is True  # feed is authoritative for a media item with no web target


def test_extract_body_none_when_no_content():
    body, cacheable = extract_article_body(SimpleNamespace(url="", content="", title="", author=""))
    assert body is None
    assert cacheable is False


# --------------------------------------------------------------------------- #
# GUI wiring
# --------------------------------------------------------------------------- #

wx = pytest.importorskip("wx")

from gui import accessibility  # noqa: E402
from gui.accessibility import AccessibleBrowserFrame  # noqa: E402


class _SyncThread:
    """Run the worker inline so background loads are deterministic in tests."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


class _StubMainFrame(wx.Frame):
    article_page_size = 400

    def __init__(self):
        super().__init__(None, title="StubMainFrame")
        self.feed_map = {}
        self._accessible_view_entries = []
        self.current_feed_id = "all"
        self.provider = SimpleNamespace(
            get_articles_page=lambda *a, **k: ([], 0),
            mark_read=lambda _id: None,
            mark_unread=lambda _id: None,
        )

    def _filter_articles(self, articles, _query):
        return list(articles or [])

    def _sort_articles_for_display(self, articles):
        return list(articles or [])

    def _get_display_title(self, article):
        return str(getattr(article, "title", "") or "")

    def _strip_html(self, html, include_images=False):
        return str(html or "")

    def _article_cache_id(self, article):
        return getattr(article, "id", id(article))


@pytest.fixture(scope="module")
def wxapp():
    app = wx.App(False)
    yield app
    try:
        app.Destroy()
    except Exception:
        pass


def _make_browser():
    mainframe = _StubMainFrame()
    frame = AccessibleBrowserFrame(mainframe)
    return mainframe, frame


def _destroy(mainframe, frame):
    try:
        frame.Destroy()
    finally:
        mainframe.Destroy()


def _article(**over):
    base = dict(
        id="a1", title="Headline", url="https://example.com/post",
        content="<p>feed snippet</p>", date="", author="Author Name",
        is_read=False, timestamp=0.0, media_url=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _select(frame, article):
    frame._current_articles = [article]
    frame.article_list.Set([frame._article_label(article)])
    frame.article_list.SetSelection(0)


def _patch_sync(monkeypatch, body, cacheable=True):
    monkeypatch.setattr(accessibility, "extract_article_body", lambda a, **kw: (body, cacheable))
    monkeypatch.setattr(accessibility.threading, "Thread", _SyncThread)
    monkeypatch.setattr(accessibility.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))


def test_full_text_replaces_snippet_and_caches(wxapp, monkeypatch):
    mainframe, frame = _make_browser()
    try:
        _patch_sync(monkeypatch, "FULL ARTICLE BODY TEXT")
        article = _article()
        _select(frame, article)

        frame._show_article_at_index(0)
        assert "feed snippet" in frame.content_ctrl.GetValue()  # immediate snippet

        # Drive the (otherwise debounced) load directly.
        frame._start_fulltext("a1", frame._content_token)

        value = frame.content_ctrl.GetValue()
        assert "FULL ARTICLE BODY TEXT" in value
        assert "feed snippet" not in value
        assert "Link: https://example.com/post" in value  # header preserved
        assert frame._fulltext_cache["a1"] == "FULL ARTICLE BODY TEXT"
        assert frame._fulltext_inflight == set()
    finally:
        _destroy(mainframe, frame)


def test_stale_token_does_not_overwrite_pane(wxapp, monkeypatch):
    mainframe, frame = _make_browser()
    try:
        _patch_sync(monkeypatch, "LATE BODY")
        article = _article()
        _select(frame, article)
        frame._show_article_at_index(0)
        before = frame.content_ctrl.GetValue()

        # A result tagged with an outdated token must not clobber the pane,
        # but is still cached for the next time the article is shown.
        frame._finish_fulltext("a1", token=-1, body="LATE BODY", cacheable=True)
        assert frame.content_ctrl.GetValue() == before
        assert frame._fulltext_cache["a1"] == "LATE BODY"
    finally:
        _destroy(mainframe, frame)


def test_feed_fallback_result_is_not_cached(wxapp, monkeypatch):
    mainframe, frame = _make_browser()
    try:
        _patch_sync(monkeypatch, "FEED FALLBACK SNIPPET", cacheable=False)
        article = _article()
        _select(frame, article)
        frame._show_article_at_index(0)
        frame._start_fulltext("a1", frame._content_token)

        # Shown in the pane, but NOT cached — so the next visit retries extraction
        # instead of being pinned to a transient feed-fallback result.
        assert "FEED FALLBACK SNIPPET" in frame.content_ctrl.GetValue()
        assert "a1" not in frame._fulltext_cache
    finally:
        _destroy(mainframe, frame)


def test_prefetch_enqueues_read_ahead_articles(wxapp):
    mainframe, frame = _make_browser()
    try:
        arts = [_article(id=f"a{i}", url=f"https://example.com/{i}") for i in range(8)]
        frame._current_articles = arts
        frame._prefetch_ahead = 3
        frame._enqueue_prefetch_from(0)
        queued = [art_id for art_id, _ in frame._prefetch_queue]
        # The current article (a0) is handled by the selection path; prefetch only the
        # next few (read-ahead), bounded by _prefetch_ahead.
        assert queued == ["a1", "a2", "a3"]
    finally:
        _destroy(mainframe, frame)


def test_cached_body_used_without_refetch(wxapp, monkeypatch):
    mainframe, frame = _make_browser()
    try:
        def _should_not_run(_a):
            raise AssertionError("extractor must not run on cache hit")

        monkeypatch.setattr(accessibility, "extract_article_body", _should_not_run)
        article = _article()
        _select(frame, article)
        frame._fulltext_cache["a1"] = "PRECACHED BODY"

        frame._show_article_at_index(0)
        value = frame.content_ctrl.GetValue()
        assert "PRECACHED BODY" in value
        assert "feed snippet" not in value
        assert frame._fulltext_inflight == set()
    finally:
        _destroy(mainframe, frame)


def test_content_focus_forces_load(wxapp, monkeypatch):
    mainframe, frame = _make_browser()
    try:
        _patch_sync(monkeypatch, "FOCUS LOADED BODY")
        article = _article()
        _select(frame, article)
        frame.content_ctrl.SetValue(frame._article_header(article) + "feed snippet")

        frame.on_content_focus(SimpleNamespace(Skip=lambda: None))
        assert "FOCUS LOADED BODY" in frame.content_ctrl.GetValue()
    finally:
        _destroy(mainframe, frame)
