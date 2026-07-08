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


class _Host:
    _precompute_article_row_annotations = mainframe.MainFrame._precompute_article_row_annotations
    _article_description_preview = mainframe.MainFrame._article_description_preview
    _article_description_text = mainframe.MainFrame._article_description_text
    _raw_article_description = mainframe.MainFrame._raw_article_description
    _strip_html = mainframe.MainFrame._strip_html
    _article_media_label = mainframe.MainFrame._article_media_label
    _should_play_in_player = mainframe.MainFrame._should_play_in_player


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


def test_precompute_survives_broken_articles():
    h = _Host()
    class _Broken:
        # attribute access raising must not abort the batch
        def __getattr__(self, name):
            raise RuntimeError("nope")
    ok = _Article()
    h._precompute_article_row_annotations([_Broken(), ok])
    assert getattr(ok, "_media_label_cached", None) is not None
