"""Central registry of user-editable keyboard shortcuts (NVDA-gestures style).

This module is deliberately pure (no wx) so the command table and the
accelerator-string parsing/normalization are unit-testable without a GUI.

An *accelerator string* is a ``+``-joined list of modifier tokens followed by a
single key token, e.g. ``"Ctrl+Shift+P"``, ``"Ctrl+Left"``, ``"Ctrl+Shift+."``.
Modifiers are normalized to the canonical order Ctrl, Alt, Shift, Cmd. An
empty/blank string means the command is *unbound*.

The GUI layer (``gui.shortcut_keys``) maps these strings to/from wx key events
and dispatches commands from the global char-hook; the editable dialog
(Keyboard Shortcuts) reads/writes user overrides which are merged over the
defaults here.
"""
from __future__ import annotations

from collections import namedtuple, OrderedDict
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Command table
# --------------------------------------------------------------------------

# label/category are English msgids; the dialog wraps them with _() at display
# time. `id` is the stable key used in config overrides and dispatch handlers.
Command = namedtuple("Command", "id category label default")

# NOTE: keep ids stable — they are persisted in config under "keyboard_shortcuts".
COMMANDS: List[Command] = [
    Command("player.play_pause", "Player", "Play/Pause", "Ctrl+P"),
    Command("player.stop", "Player", "Stop", "Ctrl+S"),
    Command("player.show_hide", "Player", "Show/Hide Player", "Ctrl+Shift+P"),

    Command("queue.open", "Play Queue", "Open Play Queue", "Ctrl+Shift+C"),
    Command("queue.next", "Play Queue", "Play Next in Queue", "Ctrl+Shift+T"),
    Command("queue.prev", "Play Queue", "Play Previous in Queue", "Ctrl+Shift+V"),

    Command("speed.up", "Playback Speed", "Increase Playback Speed", "Ctrl+Shift+."),
    Command("speed.down", "Playback Speed", "Decrease Playback Speed", "Ctrl+Shift+,"),
    Command("speed.reset", "Playback Speed", "Reset Playback Speed (1x)", "Ctrl+Shift+0"),
]

_COMMANDS_BY_ID: "OrderedDict[str, Command]" = OrderedDict((c.id, c) for c in COMMANDS)


def iter_commands() -> List[Command]:
    return list(COMMANDS)


def command_by_id(command_id: str) -> Optional[Command]:
    return _COMMANDS_BY_ID.get(str(command_id))


def categories() -> List[str]:
    """Distinct categories in first-seen (display) order."""
    seen: List[str] = []
    for c in COMMANDS:
        if c.category not in seen:
            seen.append(c.category)
    return seen


def commands_in_category(category: str) -> List[Command]:
    return [c for c in COMMANDS if c.category == category]


# --------------------------------------------------------------------------
# Accelerator-string parsing / normalization
# --------------------------------------------------------------------------

_MOD_ALIASES = {
    "ctrl": "Ctrl", "control": "Ctrl", "ctl": "Ctrl",
    "alt": "Alt", "option": "Alt", "opt": "Alt",
    "shift": "Shift",
    "cmd": "Cmd", "command": "Cmd", "win": "Cmd", "meta": "Cmd", "super": "Cmd",
}
# Canonical display + comparison order.
_MOD_ORDER = ["Ctrl", "Alt", "Shift", "Cmd"]

# Named keys: lowercased spelling -> canonical token.
_NAMED_KEYS = {
    "space": "Space",
    "left": "Left", "right": "Right", "up": "Up", "down": "Down",
    "home": "Home", "end": "End",
    "pageup": "PageUp", "pgup": "PageUp",
    "pagedown": "PageDown", "pgdn": "PageDown",
    "insert": "Insert", "ins": "Insert",
    "delete": "Delete", "del": "Delete",
    "backspace": "Backspace", "back": "Backspace",
    "enter": "Enter", "return": "Enter",
    "tab": "Tab",
    "escape": "Escape", "esc": "Escape",
    # Punctuation spellings that some callers may pass.
    "comma": ",", "period": ".", "dot": ".",
    "slash": "/", "minus": "-", "dash": "-",
    "equals": "=", "equal": "=", "plus": "+",
    "semicolon": ";", "quote": "'",
    "leftbracket": "[", "rightbracket": "]",
    "backslash": "\\", "backtick": "`", "grave": "`",
}


def _normalize_key(token: str) -> Optional[str]:
    """Return the canonical key token, or None if it is not a usable key."""
    if token is None:
        return None
    raw = str(token).strip()
    if not raw:
        return None
    low = raw.lower()
    if low in _NAMED_KEYS:
        return _NAMED_KEYS[low]
    # Function keys F1..F24
    if low[0] == "f" and low[1:].isdigit():
        n = int(low[1:])
        if 1 <= n <= 24:
            return "F" + str(n)
    if len(raw) == 1:
        ch = raw
        if ch.isalpha():
            return ch.upper()
        # digit or punctuation kept literal
        return ch
    return None


def parse_accel(accel: Optional[str]) -> Optional[Tuple[Tuple[str, ...], str]]:
    """Parse an accelerator string into ``(ordered_mods, key_token)``.

    Returns None for an empty/blank string (unbound) or a malformed value.
    """
    if accel is None:
        return None
    raw = str(accel).strip()
    if not raw:
        return None

    # Special-case a literal '+' key so "Ctrl+Shift++" parses correctly.
    if raw.endswith("+") and len(raw) > 1:
        mod_part = raw[:-1].rstrip("+")
        mods_raw = [m for m in mod_part.split("+") if m.strip()]
        key_raw = "+"
    else:
        parts = raw.split("+")
        key_raw = parts[-1]
        mods_raw = parts[:-1]

    mods: List[str] = []
    for m in mods_raw:
        canon = _MOD_ALIASES.get(m.strip().lower())
        if canon is None:
            return None
        if canon not in mods:
            mods.append(canon)

    key = _normalize_key(key_raw)
    if not key:
        return None

    ordered = tuple(m for m in _MOD_ORDER if m in mods)
    return ordered, key


def format_accel(mods, key: str) -> str:
    """Build a canonical accelerator string from modifiers + a key token."""
    if not key:
        return ""
    present = set(mods or ())
    ordered = [m for m in _MOD_ORDER if m in present]
    return "+".join(ordered + [str(key)])


def normalize_accel(accel: Optional[str]) -> str:
    """Return the canonical form of an accelerator string, or "" if unbound/invalid."""
    parsed = parse_accel(accel)
    if parsed is None:
        return ""
    mods, key = parsed
    return format_accel(mods, key)


# --------------------------------------------------------------------------
# Binding resolution (defaults + user overrides)
# --------------------------------------------------------------------------

def default_bindings() -> "OrderedDict[str, str]":
    return OrderedDict((c.id, normalize_accel(c.default)) for c in COMMANDS)


def resolve_bindings(overrides: Optional[Dict[str, object]]) -> "OrderedDict[str, str]":
    """Merge user overrides over the defaults.

    An override value may be a string (custom binding), "" or None (explicitly
    unbound). Unknown ids in `overrides` are ignored. Result maps every known
    command id -> canonical accel string ("" meaning unbound).
    """
    ov = overrides if isinstance(overrides, dict) else {}
    out: "OrderedDict[str, str]" = OrderedDict()
    for c in COMMANDS:
        if c.id in ov:
            out[c.id] = normalize_accel(ov.get(c.id))
        else:
            out[c.id] = normalize_accel(c.default)
    return out


def find_conflicts(bindings: Dict[str, str]) -> "OrderedDict[str, List[str]]":
    """Return accel -> [command_ids] for any accel bound to more than one command."""
    by_accel: "OrderedDict[str, List[str]]" = OrderedDict()
    for cmd_id, accel in (bindings or {}).items():
        norm = normalize_accel(accel)
        if not norm:
            continue
        by_accel.setdefault(norm, []).append(cmd_id)
    return OrderedDict((a, ids) for a, ids in by_accel.items() if len(ids) > 1)


def invert_bindings(bindings: Dict[str, str]) -> Dict[str, str]:
    """Map canonical accel -> command_id (last write wins on conflicts)."""
    out: Dict[str, str] = {}
    for cmd_id, accel in (bindings or {}).items():
        norm = normalize_accel(accel)
        if norm:
            out[norm] = cmd_id
    return out
