"""Startup volume application (first-adjustment volume jump bug).

libvlc silently drops audio_set_volume calls made before the audio output
exists, which left VLC playing at its own volume while PlayerFrame.volume
held the configured one — the first Volume Up/Down then jumped to
configured±step. _apply_volume_when_ready retries imposing the configured
volume until VLC confirms it, and only adopts VLC's actual volume if it
never sticks.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("wx")
pytest.importorskip("vlc")

import gui.player as player_mod
from gui.player import PlayerFrame


class DummyPlayer:
    """VLC stand-in whose audio output becomes ready after `ready_after` calls."""

    def __init__(self, vlc_volume=100, ready_after=0):
        self._volume = vlc_volume
        self._ready_after = ready_after
        self.set_calls = []

    def _ready(self):
        return self._ready_after <= 0

    def audio_set_volume(self, value):
        self.set_calls.append(value)
        if self._ready():
            self._volume = int(value)
            return 0
        self._ready_after -= 1
        return -1

    def audio_get_volume(self):
        return self._volume if self._ready() else -1


class DummyFrame:
    def __init__(self, is_casting=False, initial_volume=100, player=None):
        self.is_casting = is_casting
        self.volume = initial_volume
        self.player = player if player is not None else DummyPlayer()
        self.ui_update_calls = []

    def _update_volume_ui(self, val):
        self.ui_update_calls.append(val)

    def _apply_volume_when_ready(self, attempts_left=12):
        return PlayerFrame._apply_volume_when_ready(self, attempts_left)


def _run_synchronously(monkeypatch):
    """Make wx.CallLater invoke the retry immediately (no event loop in tests)."""
    def fake_call_later(_delay_ms, callback, *args):
        callback(*args)
    monkeypatch.setattr(player_mod.wx, "CallLater", fake_call_later)


def test_applies_configured_volume_once_output_is_ready(monkeypatch):
    _run_synchronously(monkeypatch)
    # VLC plays at 100 but the configured volume is 40; the first two set
    # attempts are dropped because the output isn't ready yet.
    frame = DummyFrame(initial_volume=40, player=DummyPlayer(vlc_volume=100, ready_after=2))

    frame._apply_volume_when_ready()

    assert frame.player.audio_get_volume() == 40
    assert frame.volume == 40  # tracked value never drifted
    assert frame.ui_update_calls[-1] == 40


def test_applies_immediately_when_output_ready():
    frame = DummyFrame(initial_volume=55, player=DummyPlayer(vlc_volume=100, ready_after=0))
    frame._apply_volume_when_ready()
    assert frame.player.audio_get_volume() == 55
    assert frame.player.set_calls == [55]


def test_adopts_vlc_volume_when_set_never_sticks(monkeypatch):
    _run_synchronously(monkeypatch)

    class StubbornPlayer:
        """Output exists (get works) but set is rejected — e.g. exotic aout."""
        def audio_set_volume(self, value):
            return -1
        def audio_get_volume(self):
            return 80

    frame = DummyFrame(initial_volume=40, player=StubbornPlayer())
    frame._apply_volume_when_ready(attempts_left=3)

    # Tracked volume matches what the user actually hears, so the next
    # adjustment is 80±step instead of a jump to 40±step.
    assert frame.volume == 80
    assert frame.ui_update_calls[-1] == 80


def test_casting_returns_early():
    frame = DummyFrame(is_casting=True, initial_volume=40)
    frame._apply_volume_when_ready()
    assert frame.player.set_calls == []
    assert frame.volume == 40


def test_player_exception_is_swallowed():
    class ErrorPlayer:
        def audio_set_volume(self, value):
            raise RuntimeError("VLC connection error")
        def audio_get_volume(self):
            raise RuntimeError("VLC connection error")

    frame = DummyFrame(initial_volume=40, player=ErrorPlayer())
    frame._apply_volume_when_ready()  # must not raise
    assert frame.volume == 40
    assert frame.ui_update_calls == []
