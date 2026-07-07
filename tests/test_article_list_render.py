"""GUI-free tests for chunked + memoized article-list rendering.

These exercise MainFrame._render_articles_list and its helpers without a real
wx.App by binding the methods onto a lightweight host and driving a fake
ListCtrl. wx.CallAfter is monkeypatched so the deferred render batches can be
drained deterministically (mirroring the fake-object pattern used by
tests/test_mainframe_issue22_shortcuts.py).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe
from gui.mainframe import (
    ARTICLE_COL_TITLE,
    ARTICLE_COL_AUTHOR,
    ARTICLE_COL_DATE,
    ARTICLE_COL_FEED,
    ARTICLE_COL_DESCRIPTION,
    ARTICLE_COL_STATUS,
)


class _FakeFeed:
    def __init__(self, title):
        self.title = title


class _FakeListCtrl:
    """Minimal non-virtual ListCtrl double that records rows as column dicts."""

    def __init__(self):
        self.rows = []  # list of {col_index: value}
        self.freeze_depth = 0

    def DeleteAllItems(self):
        self.rows = []

    def InsertItem(self, index, label):
        index = max(0, min(int(index), len(self.rows)))
        self.rows.insert(index, {ARTICLE_COL_TITLE: label})
        return index

    def SetItem(self, index, col, value):
        self.rows[index][col] = value

    def GetItemCount(self):
        return len(self.rows)

    def GetItemText(self, index, col=ARTICLE_COL_TITLE):
        if 0 <= index < len(self.rows):
            return self.rows[index].get(col, "")
        return ""

    def DeleteItem(self, index):
        del self.rows[index]

    def Freeze(self):
        self.freeze_depth += 1

    def Thaw(self):
        self.freeze_depth -= 1

    # Test convenience.
    def col(self, index, col):
        return self.rows[index].get(col, "")

    def titles(self):
        return [self.rows[i].get(ARTICLE_COL_TITLE, "") for i in range(len(self.rows))]


class _RenderHost:
    # Methods under test.
    _render_articles_list = mainframe.MainFrame._render_articles_list
    _insert_article_row = mainframe.MainFrame._insert_article_row
    _article_media_label = mainframe.MainFrame._article_media_label
    _should_play_in_player = mainframe.MainFrame._should_play_in_player
    _render_articles_batch = mainframe.MainFrame._render_articles_batch
    _reassert_load_more_placeholder_last = mainframe.MainFrame._reassert_load_more_placeholder_last
    _defer_restore_during_render = mainframe.MainFrame._defer_restore_during_render
    _article_description_preview = mainframe.MainFrame._article_description_preview
    _get_display_title = mainframe.MainFrame._get_display_title
    _add_loading_more_placeholder = mainframe.MainFrame._add_loading_more_placeholder
    _remove_loading_more_placeholder = mainframe.MainFrame._remove_loading_more_placeholder
    _update_loading_placeholder = mainframe.MainFrame._update_loading_placeholder
    _is_load_more_row = mainframe.MainFrame._is_load_more_row

    def __init__(self, *, first_chunk=2, batch_size=2, feed_map=None):
        self.list_ctrl = _FakeListCtrl()
        self.feed_map = feed_map or {}
        self.current_feed_id = "all"
        self._render_generation = 0
        self._render_first_chunk = first_chunk
        self._render_batch_size = batch_size
        self._article_render_inflight = False
        self._loading_more_placeholder = False
        self._load_more_label = "Load more items (Enter)"
        self._loading_label = "Loading more..."
        # Spy: count builder calls per article id so memoization is observable.
        self.desc_text_calls = {}

    def _article_description_text(self, article, include_images=None):
        _ = include_images
        key = article.id
        self.desc_text_calls[key] = self.desc_text_calls.get(key, 0) + 1
        return f"Description for {article.title}"


def _make_article(idx, *, title=None, author=None, read=False):
    return mainframe.Article(
        title=title if title is not None else f"Title {idx}",
        url=f"https://example.com/{idx}",
        content="",
        date="",  # humanize_article_date("") -> "" (deterministic)
        author=author if author is not None else f"Author {idx}",
        feed_id="feed-1",
        id=f"article-{idx}",
        is_read=read,
    )


def _install_capturing_call_after(monkeypatch):
    captured = []

    def _fake_call_after(callback, *args, **kwargs):
        captured.append((callback, args, kwargs))

    monkeypatch.setattr(mainframe.wx, "CallAfter", _fake_call_after)
    return captured


def _drain(captured):
    """Run queued callbacks FIFO; a callback may enqueue further batches."""
    guard = 0
    while captured:
        guard += 1
        assert guard < 10000, "runaway deferred-render queue"
        callback, args, kwargs = captured.pop(0)
        callback(*args, **kwargs)


def test_description_preview_memoized_across_renders(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    host = _RenderHost(first_chunk=2, batch_size=2)
    articles = [_make_article(i) for i in range(5)]

    host._render_articles_list(articles)
    _drain(captured)
    # First full render builds each article's preview exactly once.
    assert {a.id: host.desc_text_calls[a.id] for a in articles} == {a.id: 1 for a in articles}

    host._render_articles_list(articles)
    _drain(captured)
    # Second render of the same articles reuses the memoized preview: no rebuilds.
    assert {a.id: host.desc_text_calls[a.id] for a in articles} == {a.id: 1 for a in articles}


def test_chunked_render_produces_one_row_per_article_in_order(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    feed_map = {"feed-1": _FakeFeed("My Feed")}
    host = _RenderHost(first_chunk=2, batch_size=2, feed_map=feed_map)
    articles = [_make_article(i, read=(i % 2 == 0)) for i in range(5)]

    host._render_articles_list(articles)
    # Only the synchronous first chunk is present immediately.
    assert host.list_ctrl.GetItemCount() == 2
    assert host._article_render_inflight is True
    assert len(captured) == 1

    _drain(captured)

    # Draining the deferred batches completes the list: one row per article,
    # input order preserved, no placeholder, correct column values.
    assert host.list_ctrl.GetItemCount() == 5
    assert host._article_render_inflight is False
    for i, a in enumerate(articles):
        assert host.list_ctrl.col(i, ARTICLE_COL_TITLE) == a.title
        assert host.list_ctrl.col(i, ARTICLE_COL_AUTHOR) == a.author
        assert host.list_ctrl.col(i, ARTICLE_COL_DATE) == ""
        assert host.list_ctrl.col(i, ARTICLE_COL_FEED) == "My Feed"
        assert host.list_ctrl.col(i, ARTICLE_COL_DESCRIPTION) == a._desc_preview_240
        assert host.list_ctrl.col(i, ARTICLE_COL_STATUS) == ("Read" if a.is_read else "Unread")


def test_superseded_generation_stops_stale_batches(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    host = _RenderHost(first_chunk=2, batch_size=2)
    first = [_make_article(i, title=f"A{i}") for i in range(5)]
    second = [_make_article(100 + i, title=f"B{i}") for i in range(3)]

    host._render_articles_list(first)  # renders A0,A1; queues a batch for A2..A4
    assert host.list_ctrl.titles() == ["A0", "A1"]
    assert len(captured) == 1

    # A new render (same feed) supersedes the first by bumping _render_generation.
    host._render_articles_list(second)
    assert host.list_ctrl.titles() == ["B0", "B1"]

    _drain(captured)

    # The stale first-render batch must add nothing; only the new view remains.
    assert host.list_ctrl.titles() == ["B0", "B1", "B2"]
    assert host._article_render_inflight is False


def test_view_switch_without_generation_bump_stops_batches(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    host = _RenderHost(first_chunk=2, batch_size=2)
    articles = [_make_article(i) for i in range(5)]

    host._render_articles_list(articles)  # gen=1, feed="all", batch queued
    assert host._article_render_inflight is True

    # Mirror _select_view's empty cached-view branch: swap the current view and
    # clear the list WITHOUT calling _render_articles_list (no generation bump).
    host.current_feed_id = "feed-9"
    host.list_ctrl.DeleteAllItems()
    host.list_ctrl.InsertItem(0, "No articles found.")

    _drain(captured)

    # The stale batch detects the view change and abandons instead of injecting
    # the old view's rows into the new (empty) view.
    assert host.list_ctrl.titles() == ["No articles found."]
    assert host._article_render_inflight is False


def test_empty_input_renders_single_empty_label(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    host = _RenderHost()

    host._render_articles_list([], empty_label="No articles found.")

    assert host.list_ctrl.GetItemCount() == 1
    assert host.list_ctrl.col(0, ARTICLE_COL_TITLE) == "No articles found."
    assert host._article_render_inflight is False
    assert captured == []


def test_async_batches_keep_load_more_placeholder_last(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    host = _RenderHost(first_chunk=2, batch_size=2)
    articles = [_make_article(i) for i in range(5)]

    host._render_articles_list(articles)
    # Caller adds the placeholder synchronously right after render returns, like
    # _select_view / _populate_articles do. It lands right after the first chunk.
    host._add_loading_more_placeholder()
    assert host._loading_more_placeholder is True
    assert host.list_ctrl.GetItemCount() == 3
    assert host.list_ctrl.col(2, ARTICLE_COL_TITLE) == host._load_more_label

    _drain(captured)

    # All articles rendered in order and the placeholder remains the LAST row,
    # even though later batches appended rows above it.
    assert host.list_ctrl.GetItemCount() == 6
    for i, a in enumerate(articles):
        assert host.list_ctrl.col(i, ARTICLE_COL_TITLE) == a.title
    assert host.list_ctrl.col(5, ARTICLE_COL_TITLE) == host._load_more_label
    assert host._is_load_more_row(5) is True
    assert host._is_load_more_row(4) is False


def test_description_preview_long_max_len_is_not_memoized_short(monkeypatch):
    # The 4000-char sort path must never receive the 240-char list truncation.
    _install_capturing_call_after(monkeypatch)
    host = _RenderHost()
    article = _make_article(0)
    article.description = "word " * 200  # ~1000 chars of plain text

    # Provide the real text builder path for this one article via a stub that
    # returns the raw description so lengths are meaningful.
    host._article_description_text = lambda a, include_images=None: a.description

    short = host._article_description_preview(article)  # default max_len=240
    long = host._article_description_preview(article, max_len=4000)

    assert len(short) <= 240
    assert short.endswith("...")
    assert len(long) > 240  # full text, not the cached 240-char preview
    assert getattr(article, "_desc_preview_240") == short
