"""GUI-free tests for the off-UI-thread article row annotation precompute.

Large-category lag fix: first-time computation of the description preview
(HTML->text parse) and media label (yt-dlp extractor URL matching) is too slow
for the list-render loop, so the loader threads warm both memos via
_precompute_article_row_annotations before handing articles to wx.CallAfter.
These tests pin that the precompute fills the per-Article memos and that the
render-path helpers then serve from cache without recomputing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe


class _Article:
    def __init__(self, **kw):
        self.title = kw.get("title", "t")
        self.url = kw.get("url", "https://example.com/news/story")
        self.media_url = kw.get("media_url", "")
        self.media_type = kw.get("media_type", "")
        self.description = kw.get("description", "<p>Hello   <b>world</b></p>")
        self.content = kw.get("content", "")
        self.feed_id = kw.get("feed_id", "f1")
        self.id = kw.get("id", 1)


class _Host:
    _precompute_article_row_annotations = mainframe.MainFrame._precompute_article_row_annotations
    _article_description_preview = mainframe.MainFrame._article_description_preview
    _article_description_text = mainframe.MainFrame._article_description_text
    _raw_article_description = mainframe.MainFrame._raw_article_description
    _strip_html = mainframe.MainFrame._strip_html
    _article_media_label = mainframe.MainFrame._article_media_label
    _should_play_in_player = mainframe.MainFrame._should_play_in_player
    _playback_state_for_article = mainframe.MainFrame._playback_state_for_article
    _playback_time_annotation = mainframe.MainFrame._playback_time_annotation
    _format_media_time = staticmethod(mainframe.MainFrame._format_media_time)
    _update_live_media_annotation = mainframe.MainFrame._update_live_media_annotation


def test_precompute_fills_both_memos():
    h = _Host()
    articles = [
        _Article(),
        _Article(url="https://www.youtube.com/watch?v=abc123"),
        _Article(media_url="https://cdn.example.com/e.mp3", media_type="audio/mpeg"),
    ]
    h._precompute_article_row_annotations(articles)
    for a in articles:
        assert getattr(a, "_desc_preview_240", None) is not None
        assert getattr(a, "_media_label_cached", None) is not None


def test_render_path_uses_memo_without_recompute():
    h = _Host()
    a = _Article()
    h._precompute_article_row_annotations([a])
    preview = a._desc_preview_240
    label = a._media_label_cached
    assert "Hello world" in preview

    # After precompute the render-loop calls must be pure cache reads: poison
    # the recompute paths and make sure the memoized values are still served.
    h._strip_html = None  # would raise TypeError if the preview re-parsed
    def _boom(*_a, **_k):
        raise AssertionError("media label recomputed on render path")
    h._should_play_in_player = _boom

    assert h._article_description_preview(a) == preview
    assert h._article_media_label(a) == label


def test_preview_cache_survives_article_object_rebuilds():
    """Refresh reload storms build NEW Article objects each cycle; the
    second-level LRU (keyed by article id + content hash) must serve them
    without re-parsing, or every refresh cycle costs ~1.5s of loader-thread
    CPU and starves the UI via the GIL."""
    h = _Host()
    h._article_cache_id = lambda a: "id-1"

    parses = []
    orig_strip = _Host._strip_html
    def counting_strip(self, html, include_images=None):
        parses.append(1)
        return orig_strip(self, html, include_images=include_images)
    h._strip_html = counting_strip.__get__(h)

    first = _Article()
    h._precompute_article_row_annotations([first])
    assert len(parses) == 1

    # Same article id + identical content, but a brand-new object (as built by
    # the next refresh cycle): must be a cache hit, not a re-parse.
    rebuilt = _Article()
    h._precompute_article_row_annotations([rebuilt])
    assert len(parses) == 1
    assert rebuilt._desc_preview_240 == first._desc_preview_240

    # Changed content -> re-parse (cache key includes the content hash).
    changed = _Article(description="<p>Different</p>")
    h._precompute_article_row_annotations([changed])
    assert len(parses) == 2


def test_precompute_survives_broken_articles():
    h = _Host()
    class _Broken:
        # attribute access raising must not abort the batch
        def __getattr__(self, name):
            raise RuntimeError("nope")
    ok = _Article()
    h._precompute_article_row_annotations([_Broken(), ok])
    assert getattr(ok, "_media_label_cached", None) is not None


def test_live_player_duration_refreshes_visible_media_column():
    class _List:
        def __init__(self):
            self.value = mainframe.ARTICLE_MEDIA_YES + ", not played"

        def GetItemText(self, _row, _col):
            return self.value

        def SetItem(self, _row, _col, value):
            self.value = value

    h = _Host()
    article = _Article(id=42, media_url="https://cdn.example.com/show.mp3", media_type="audio/mpeg")
    h.current_articles = [article]
    h.list_ctrl = _List()
    h._playback_states_cache = {}
    h._precompute_article_row_annotations([article])

    h._update_live_media_annotation({
        "has_media": True,
        "article_id": 42,
        "media_url": article.media_url,
        "position_ms": 2_000,
        "duration_ms": 125_000,
    })

    assert h.list_ctrl.value == "Contains audio, 2:05, played 0:02"
