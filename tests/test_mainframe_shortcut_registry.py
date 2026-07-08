"""GUI-free tests for MainFrame's shortcut/speed/queue helper wiring.

Binds the real methods onto a lightweight host (same pattern as
test_article_list_render.py) so the registry glue is covered without a wx.App.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe
from core import utils


class _FakeConfig:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class _Host:
    get_shortcut_overrides = mainframe.MainFrame.get_shortcut_overrides
    get_shortcut_bindings = mainframe.MainFrame.get_shortcut_bindings
    save_shortcut_overrides = mainframe.MainFrame.save_shortcut_overrides
    _rebuild_shortcut_map = mainframe.MainFrame._rebuild_shortcut_map
    reload_shortcuts = mainframe.MainFrame.reload_shortcuts
    _refresh_shortcut_menu_labels = mainframe.MainFrame._refresh_shortcut_menu_labels
    binding_label = mainframe.MainFrame.binding_label

    _get_play_queue = mainframe.MainFrame._get_play_queue
    _play_queue_step = mainframe.MainFrame._play_queue_step
    on_play_queue_next = mainframe.MainFrame.on_play_queue_next
    on_play_queue_prev = mainframe.MainFrame.on_play_queue_prev

    _nudge_playback_speed = mainframe.MainFrame._nudge_playback_speed
    _apply_playback_speed = mainframe.MainFrame._apply_playback_speed
    _player_for_speed = mainframe.MainFrame._player_for_speed

    def __init__(self, config=None):
        self.config_manager = _FakeConfig(config)
        self._shortcut_cmd_map = {}
        self._shortcut_menu_items = {}
        self._current_queue_index = None
        self.player_window = None
        self.announcements = []
        self.played = []
        self._rebuild_shortcut_map()

    def _announce(self, msg):
        self.announcements.append(msg)

    def play_queue_index(self, index):
        self.played.append(int(index))
        self._current_queue_index = int(index)
        return True


def test_default_binding_labels_and_map():
    h = _Host()
    assert h.binding_label("player.play_pause") == "Ctrl+P"
    assert h.binding_label("player.stop") == "Ctrl+S"
    assert h.binding_label("player.equalizer") == "Ctrl+Shift+E"
    assert h._shortcut_cmd_map["Ctrl+P"] == "player.play_pause"
    assert h._shortcut_cmd_map["Ctrl+Shift+C"] == "queue.open"
    assert h._shortcut_cmd_map["Ctrl+Shift+E"] == "player.equalizer"
    assert h._shortcut_cmd_map["Ctrl+Shift+U"] == "speed.up"
    assert h._shortcut_cmd_map["Ctrl+Shift+D"] == "speed.down"
    assert h._shortcut_cmd_map["Ctrl+Shift+N"] == "speed.reset"


class _AnyAttr:
    # Any handler-method lookup resolves to a placeholder so we can read the
    # dispatch map's keys without a real MainFrame.
    def __getattr__(self, name):
        return lambda *a, **k: None


def test_every_command_has_a_dispatch_handler():
    """Guard against adding a registry command without wiring its handler."""
    from core import shortcuts as sc

    mapped = set(mainframe.MainFrame._shortcut_handlers(_AnyAttr()).keys())
    for cmd in sc.iter_commands():
        assert cmd.id in mapped, f"no handler wired for {cmd.id}"


def test_speed_shortcuts_dispatch_but_are_not_text_guarded():
    """Speed keys must work even while a text control is focused (e.g. reading
    an article while listening) — their combos can't hijack typing."""
    guarded = mainframe.MainFrame._SHORTCUT_TEXT_GUARDED
    mapped = mainframe.MainFrame._shortcut_handlers(_AnyAttr())
    for cmd_id in ("speed.up", "speed.down", "speed.reset"):
        assert cmd_id in mapped, f"{cmd_id} has no handler"
        assert cmd_id not in guarded, f"{cmd_id} should not be text-guarded"


def test_save_override_rebuilds_map_and_label():
    h = _Host()
    h.save_shortcut_overrides({"player.play_pause": "Ctrl+Alt+P"})
    assert h.binding_label("player.play_pause") == "Ctrl+Alt+P"
    assert h._shortcut_cmd_map["Ctrl+Alt+P"] == "player.play_pause"
    # Old default no longer maps to the command.
    assert h._shortcut_cmd_map.get("Ctrl+P") != "player.play_pause"
    # Persisted to config.
    assert h.config_manager.get("keyboard_shortcuts")["player.play_pause"] == "Ctrl+Alt+P"


def test_unbind_removes_from_map():
    h = _Host()
    h.save_shortcut_overrides({"player.stop": ""})
    assert h.binding_label("player.stop") == ""
    assert "Ctrl+S" not in h._shortcut_cmd_map


def test_queue_step_from_idle_plays_first_then_advances():
    h = _Host({"play_queue": [
        {"article_id": "a", "media_url": "u1", "title": "One"},
        {"article_id": "b", "media_url": "u2", "title": "Two"},
    ]})
    h.on_play_queue_next()          # idle -> first
    assert h.played == [0]
    h.on_play_queue_next()          # -> second
    assert h.played == [0, 1]
    h.on_play_queue_prev()          # -> first
    assert h.played == [0, 1, 0]


def test_queue_step_empty_announces():
    h = _Host({"play_queue": []})
    h.on_play_queue_next()
    assert h.played == []
    assert h.announcements  # announced empty


def test_nudge_playback_speed_persists_when_no_player():
    h = _Host({"playback_speed": 1.0})
    speeds = utils.build_playback_speeds()
    h._nudge_playback_speed(+1)
    # With no player window, the new speed is persisted to config.
    saved = float(h.config_manager.get("playback_speed"))
    idx = min(range(len(speeds)), key=lambda i: abs(speeds[i] - 1.0))
    assert saved == speeds[min(len(speeds) - 1, idx + 1)]


def test_apply_speed_uses_player_when_present():
    h = _Host({"playback_speed": 1.0})

    class _PW:
        def __init__(self):
            self.speed = None

        def set_playback_speed(self, s):
            self.speed = s

    h.player_window = _PW()
    h._apply_playback_speed(1.5)
    assert h.player_window.speed == 1.5
