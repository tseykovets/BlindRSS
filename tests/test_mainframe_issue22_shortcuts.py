import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe


class _DummyKeyEvent:
    def __init__(self, key, *, ctrl=False, shift=False, alt=False, meta=False):
        self._key = int(key)
        self._ctrl = bool(ctrl)
        self._shift = bool(shift)
        self._alt = bool(alt)
        self._meta = bool(meta)
        self.skipped = False

    def GetKeyCode(self):
        return int(self._key)

    def ControlDown(self):
        return bool(self._ctrl)

    def ShiftDown(self):
        return bool(self._shift)

    def AltDown(self):
        return bool(self._alt)

    def MetaDown(self):
        return bool(self._meta)

    def Skip(self):
        self.skipped = True


class _DummyHost:
    on_char_hook = mainframe.MainFrame.on_char_hook
    on_article_list_key_down = mainframe.MainFrame.on_article_list_key_down
    _is_delete_key = mainframe.MainFrame._is_delete_key
    _window_is_or_child = mainframe.MainFrame._window_is_or_child

    def __init__(self):
        self.tree = object()
        self.list_ctrl = object()
        self.player_window = None
        self._media_hotkeys = None
        self.calls = []
        self._focus = None

    def _get_focused_window(self):
        return self._focus

    def on_edit_feed(self, event):
        self.calls.append(("edit_feed", event))

    def on_find_feed(self, event):
        self.calls.append(("find_feed", event))

    def on_delete_article(self):
        self.calls.append(("delete_article", None))

    def on_remove_feed(self, event):
        self.calls.append(("remove_feed", event))

    def on_article_activate(self, event):
        self.calls.append(("article_activate", event))

    def _make_list_activate_event(self, idx):
        self.calls.append(("make_list_evt", idx))
        return object()


class _FakeMenuItem:
    def __init__(self, item_id, label):
        self._id = int(item_id)
        self.label = str(label)

    def GetId(self):
        return int(self._id)


class _FakeMenu:
    last_menu = None

    def __init__(self):
        self._next_id = 1000
        self._items = []
        _FakeMenu.last_menu = self

    def Append(self, item_id, label, help_text=""):
        _ = help_text
        if int(item_id) == int(mainframe.wx.ID_ANY):
            item_id = self._next_id
            self._next_id += 1
        item = _FakeMenuItem(item_id, label)
        self._items.append(item)
        return item

    def AppendSeparator(self):
        return self.Append(mainframe.wx.ID_ANY, "---")

    def GetMenuItems(self):
        return list(self._items)

    def Destroy(self):
        pass


class _FakeProvider:
    def supports_article_delete(self):
        return True

    def supports_favorites(self):
        return False


class _FakeRect:
    def GetPosition(self):
        return mainframe.wx.Point(0, 0)


class _FakeListCtrl:
    def __init__(self):
        self.popup_menu = None
        self.popup_pos = None

    def GetFirstSelected(self):
        return 0

    def GetFocusedItem(self):
        return 0

    def GetItemRect(self, idx):
        _ = idx
        return _FakeRect()

    def PopupMenu(self, menu, pos):
        self.popup_menu = menu
        self.popup_pos = pos


class _DummyContextMenuHost:
    on_list_context_menu = mainframe.MainFrame.on_list_context_menu
    _get_selected_article_index = mainframe.MainFrame._get_selected_article_index
    _supports_article_delete = mainframe.MainFrame._supports_article_delete
    _supports_favorites = mainframe.MainFrame._supports_favorites

    def __init__(self):
        self.provider = _FakeProvider()
        self.list_ctrl = _FakeListCtrl()
        self.current_articles = [
            mainframe.Article(
                title="Title",
                url="https://example.com/article",
                content="",
                date="",
                author="",
                feed_id="feed-1",
                id="article-1",
            )
        ]
        self.bindings = []

    def _is_load_more_row(self, idx):
        _ = idx
        return False

    def Bind(self, evt, handler, item):
        self.bindings.append((evt, handler, int(item.GetId())))

    def on_article_activate(self, event):
        self.bindings.append(("activate", event, None))

    def _make_list_activate_event(self, idx):
        return ("activate", idx)

    def on_open_in_browser(self, idx):
        self.bindings.append(("browser", idx, None))

    def mark_article_read(self, idx):
        self.bindings.append(("read", idx, None))

    def mark_article_unread(self, idx):
        self.bindings.append(("unread", idx, None))

    def on_delete_article(self):
        self.bindings.append(("delete", None, None))

    def on_copy_link(self, idx):
        self.bindings.append(("copy", idx, None))

    def on_detect_audio(self, article):
        self.bindings.append(("detect", article, None))


class _KeyboardContextEvent:
    def GetPosition(self):
        return mainframe.wx.DefaultPosition


def test_f2_shortcut_opens_edit_feed_when_tree_focused():
    host = _DummyHost()
    host._focus = host.tree
    evt = _DummyKeyEvent(mainframe.wx.WXK_F2)

    host.on_char_hook(evt)

    assert ("edit_feed", None) in host.calls
    assert evt.skipped is False


def test_ctrl_shift_f_shortcut_opens_feed_search():
    host = _DummyHost()
    evt = _DummyKeyEvent(ord("F"), ctrl=True, shift=True)

    host.on_char_hook(evt)

    assert ("find_feed", None) in host.calls
    assert evt.skipped is False


def test_delete_shortcut_deletes_article_when_list_focused():
    host = _DummyHost()
    host._focus = host.list_ctrl
    evt = _DummyKeyEvent(mainframe.wx.WXK_DELETE)

    host.on_char_hook(evt)

    assert ("delete_article", None) in host.calls
    assert evt.skipped is False


def test_article_list_key_down_deletes_article():
    host = _DummyHost()
    evt = _DummyKeyEvent(mainframe.wx.WXK_DELETE)

    host.on_article_list_key_down(evt)

    assert ("delete_article", None) in host.calls
    assert evt.skipped is False


def test_article_context_menu_includes_delete_for_supported_provider(monkeypatch):
    monkeypatch.setattr(mainframe.wx, "Menu", _FakeMenu)
    host = _DummyContextMenuHost()

    host.on_list_context_menu(_KeyboardContextEvent())

    labels = [item.label for item in host.list_ctrl.popup_menu.GetMenuItems()]
    assert "Delete Article\tDel" in labels
