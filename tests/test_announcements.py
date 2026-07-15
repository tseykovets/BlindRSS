"""Screen-reader announcement config + emit logic (issue #67).

Covers per-event mode resolution/normalization and the Announcer emit paths
(speech/Braille selection, disabled events, and the accessible-output2 ->
direct NVDA/JAWS fallback) without needing a running screen reader.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import announcements as ann
from core import screen_reader_announce


# --------------------------------------------------------------------------
# Mode table + resolution
# --------------------------------------------------------------------------

def test_default_modes_are_all_both():
    defaults = ann.default_modes()
    assert set(defaults) == {e.id for e in ann.iter_events()}
    assert all(mode == ann.MODE_BOTH for mode in defaults.values())


def test_mode_choices_cover_all_modes_in_order():
    choices = ann.mode_choices()
    assert [m for m, _label in choices] == ann.MODE_ORDER
    # None / Only speech / Only Braille / Speech and Braille
    assert [label for _m, label in choices] == [
        "None",
        "Only speech",
        "Only Braille",
        "Speech and Braille",
    ]


def test_normalize_fills_defaults_and_drops_unknown():
    out = ann.normalize_modes(
        {"filter_change": "none", "status_toggle": "bogus", "unknown_evt": "speech"}
    )
    assert out["filter_change"] == "none"          # kept (valid)
    assert out["status_toggle"] == ann.MODE_BOTH   # invalid -> default
    assert "unknown_evt" not in out                # dropped
    assert set(out) == {e.id for e in ann.iter_events()}


def test_normalize_handles_non_dict():
    assert ann.normalize_modes(None) == ann.default_modes()
    assert ann.normalize_modes("nope") == ann.default_modes()


def test_mode_for_falls_back_to_default():
    assert ann.mode_for({"playback_speed": "braille"}, "playback_speed") == "braille"
    assert ann.mode_for({}, "playback_speed") == ann.MODE_BOTH
    assert ann.mode_for({"playback_speed": "bad"}, "playback_speed") == ann.MODE_BOTH
    assert ann.mode_for(None, "general") == ann.MODE_BOTH


# --------------------------------------------------------------------------
# Announcer emit paths
# --------------------------------------------------------------------------

class _FakeOutput:
    def __init__(self):
        self.spoke = []
        self.brailled = []

    def speak(self, text, interrupt=False):
        self.spoke.append((text, interrupt))

    def braille(self, text):
        self.brailled.append(text)


def _announcer_with_output(modes, output):
    a = ann.Announcer(lambda: modes)
    a._ao2 = output
    a._ao2_attempted = True
    return a


def test_disabled_event_emits_nothing(monkeypatch):
    calls = {"speak": 0, "braille": 0}
    monkeypatch.setattr(screen_reader_announce, "speak_status", lambda *a, **k: calls.__setitem__("speak", calls["speak"] + 1) or True)
    monkeypatch.setattr(screen_reader_announce, "braille_message", lambda *a, **k: calls.__setitem__("braille", calls["braille"] + 1) or True)
    out = _FakeOutput()
    a = _announcer_with_output({"general": "none"}, out)
    assert a.announce("general", "hello") is False
    assert out.spoke == [] and out.brailled == []
    assert calls == {"speak": 0, "braille": 0}


def test_blank_message_is_noop():
    out = _FakeOutput()
    a = _announcer_with_output({"general": "both"}, out)
    assert a.announce("general", "   ") is False
    assert out.spoke == [] and out.brailled == []


def test_speech_only_uses_speak_not_braille():
    out = _FakeOutput()
    a = _announcer_with_output({"status_toggle": "speech"}, out)
    assert a.announce("status_toggle", "Read") is True
    assert out.spoke == [("Read", True)]
    assert out.brailled == []


def test_braille_only_uses_braille_not_speak():
    out = _FakeOutput()
    a = _announcer_with_output({"status_toggle": "braille"}, out)
    assert a.announce("status_toggle", "Unread") is True
    assert out.spoke == []
    assert out.brailled == ["Unread"]


def test_both_uses_speech_and_braille():
    out = _FakeOutput()
    a = _announcer_with_output({"filter_change": "both"}, out)
    assert a.announce("filter_change", "Unread Only") is True
    assert out.spoke == [("Unread Only", True)]
    assert out.brailled == ["Unread Only"]


def test_falls_back_to_direct_path_when_no_ao2(monkeypatch):
    spoke, brailled = [], []
    monkeypatch.setattr(screen_reader_announce, "speak_status", lambda text, interrupt=True: spoke.append(text) or True)
    monkeypatch.setattr(screen_reader_announce, "braille_message", lambda text: brailled.append(text) or True)
    a = ann.Announcer(lambda: {"general": "both"})
    a._ao2 = None
    a._ao2_attempted = True
    assert a.announce("general", "Refresh Feeds") is True
    assert spoke == ["Refresh Feeds"]
    assert brailled == ["Refresh Feeds"]


def test_getter_exceptions_do_not_propagate():
    def boom():
        raise RuntimeError("nope")

    a = ann.Announcer(boom)
    # resolve_mode swallows the getter error -> default mode; emit is guarded.
    assert a.resolve_mode("general") == ann.MODE_BOTH


def test_ao2_speak_signature_without_interrupt():
    class Old:
        def __init__(self):
            self.calls = []

        def speak(self, text):  # no interrupt kwarg
            self.calls.append(text)

        def braille(self, text):
            pass

    out = Old()
    assert ann.Announcer._ao2_speak(out, "hi") is True
    assert out.calls == ["hi"]
