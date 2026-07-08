"""Construction + handler smoke tests for the new dialogs (needs a wx.App)."""
import pytest

wx = pytest.importorskip("wx")

from core import shortcuts as sc
from core import equalizer as eqmod
from gui.dialogs import KeyboardShortcutsDialog, EqualizerDialog


@pytest.fixture(scope="module")
def app():
    try:
        a = wx.App()
    except Exception as e:  # pragma: no cover - headless
        pytest.skip(f"no wx display: {e}")
    yield a


class _ShortcutController:
    def __init__(self):
        self.overrides = {}
        self.saved = []

    def get_shortcut_overrides(self):
        return dict(self.overrides)

    def save_shortcut_overrides(self, ov):
        self.overrides = dict(ov)
        self.saved.append(dict(ov))


def test_keyboard_shortcuts_dialog_lists_all_commands(app):
    parent = wx.Frame(None)
    try:
        ctl = _ShortcutController()
        dlg = KeyboardShortcutsDialog(parent, ctl)
        try:
            assert dlg.list_ctrl.GetItemCount() == len(sc.iter_commands())
            # Row 0 shows the play/pause default in the Shortcut column.
            assert dlg.list_ctrl.GetItemText(0, 2) == "Ctrl+P"

            # Remove the selected command's binding -> persisted as unbound.
            dlg.list_ctrl.Select(0)
            dlg.on_remove()
            first_id = sc.iter_commands()[0].id
            assert ctl.overrides.get(first_id) == ""
            assert sc.resolve_bindings(ctl.overrides)[first_id] == ""
        finally:
            dlg.Destroy()
    finally:
        parent.Destroy()


class _EqPlayer:
    def __init__(self):
        self.cfg = eqmod.flat_config()
        self.applied = []

    def get_equalizer_config(self):
        return dict(self.cfg)

    def set_equalizer_config(self, cfg, *, persist=True, apply=True):
        self.cfg = eqmod.normalize_config(cfg)
        self.applied.append(dict(self.cfg))

    def list_equalizer_presets(self):
        return [("Rock", 0.0, [4.0] * eqmod.BAND_COUNT)]


def test_equalizer_dialog_enable_and_adjust(app):
    parent = wx.Frame(None)
    try:
        player = _EqPlayer()
        dlg = EqualizerDialog(parent, player)
        try:
            assert len(dlg.band_sliders) == eqmod.BAND_COUNT

            # Enabling pushes an enabled config to the player.
            dlg.enable_cb.SetValue(True)
            dlg.on_enable(None)
            assert player.cfg["enabled"] is True

            # Moving a band updates that band's gain.
            dlg.band_sliders[0].SetValue(6)
            dlg.on_slider(None)
            assert player.cfg["bands"][0] == 6.0

            # Applying a preset copies its gains in.
            dlg.preset_choice.SetSelection(1)
            dlg.on_preset(None)
            assert player.cfg["bands"][0] == 4.0
            assert player.cfg["preset"] == "Rock"

            # Reset flattens everything.
            dlg.on_reset()
            assert all(b == 0.0 for b in player.cfg["bands"])
            assert player.cfg["preamp"] == 0.0
        finally:
            dlg.Destroy()
    finally:
        parent.Destroy()


def test_equalizer_sliders_are_labeled_for_screen_readers(app):
    """Each slider must carry a meaningful accessible name (not a value)."""
    parent = wx.Frame(None)
    try:
        player = _EqPlayer()
        dlg = EqualizerDialog(parent, player)
        try:
            # Preamp + the first band read as their labels, never a bare number.
            assert dlg.preamp_slider.GetName() == "Preamp"
            for s in dlg.band_sliders:
                name = s.GetName()
                assert name and not name.strip().lstrip("+-").isdigit()

            # The custom accessible reports the value in dB, signed.
            acc = getattr(dlg.band_sliders[0], "_acc", None)
            if acc is not None:
                dlg.band_sliders[0].SetValue(3)
                assert acc.GetValue(wx.ACC_SELF)[1] == "+3 dB"
                dlg.band_sliders[0].SetValue(0)
                assert acc.GetValue(wx.ACC_SELF)[1] == "0 dB"
        finally:
            dlg.Destroy()
    finally:
        parent.Destroy()
