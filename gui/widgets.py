"""Shared accessible custom controls.

CheckListCtrl exists because wx.CheckListBox is invisible to screen readers on
Windows: wxMSW implements it as an owner-drawn ListBox whose checkboxes are
only painted, so MSAA/UIA report a plain list with no checkable state and NVDA
users hear "selected" instead of "checked"/"not checked" (nvaccess/nvda#7325 —
the NVDA project itself replaced wx.CheckListBox for the same reason). A
wx.ListCtrl with native checkboxes is the ListView control Windows Disk
Cleanup uses: NVDA reports the check state per item, announces changes, and
Space toggles the focused item natively.
"""
from typing import Callable, Optional

import wx


class CheckListCtrl(wx.ListCtrl):
    """Single-column checkable list with a CheckListBox-like API.

    Set ``on_user_check`` to a ``callable(index, checked)``; it fires only for
    user-initiated toggles (Space or a checkbox click), never for programmatic
    ``Check()``/``Set()`` calls, so consumers can update their model without
    re-entrancy guards.
    """

    def __init__(self, parent):
        super().__init__(
            parent,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER,
        )
        self.InsertColumn(0, "")
        self.EnableCheckBoxes(True)
        self.on_user_check: Optional[Callable[[int, bool], None]] = None
        self._programmatic = 0
        self.Bind(wx.EVT_LIST_ITEM_CHECKED, lambda e: self._on_check_event(e, True))
        self.Bind(wx.EVT_LIST_ITEM_UNCHECKED, lambda e: self._on_check_event(e, False))
        self.Bind(wx.EVT_SIZE, self._on_size)

    def _on_size(self, event):
        event.Skip()
        # The single column tracks the control width so labels aren't clipped
        # at the ListCtrl's tiny default column width.
        width = self.GetClientSize().width
        if width > 0:
            self.SetColumnWidth(0, max(40, width - 4))

    def _on_check_event(self, event, checked: bool) -> None:
        if self._programmatic:
            return
        callback = self.on_user_check
        if callback is None:
            return
        index = int(event.GetIndex())
        if 0 <= index < self.GetItemCount():
            callback(index, bool(checked))

    # -- CheckListBox-compatible surface ---------------------------------

    def Set(self, labels) -> None:
        """Replace all rows (all unchecked; selection is cleared)."""
        self._programmatic += 1
        try:
            self.DeleteAllItems()
            for i, label in enumerate(list(labels or [])):
                self.InsertItem(i, str(label))
        finally:
            self._programmatic -= 1

    def GetCount(self) -> int:
        return self.GetItemCount()

    def Check(self, index: int, check: bool = True) -> None:
        self._programmatic += 1
        try:
            self.CheckItem(int(index), bool(check))
        finally:
            self._programmatic -= 1

    def IsChecked(self, index: int) -> bool:
        return bool(self.IsItemChecked(int(index)))

    def GetSelection(self) -> int:
        return int(self.GetFirstSelected())

    def SetSelection(self, index: int) -> None:
        index = int(index)
        if 0 <= index < self.GetItemCount():
            self.Select(index)
            self.Focus(index)

    def SetString(self, index: int, label: str) -> None:
        self.SetItemText(int(index), str(label))
