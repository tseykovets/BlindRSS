"""gettext internationalization plumbing (issue #44).

Verifies the identity fallback (no catalogs -> English passthrough, the state
every existing user is in), real catalog loading via a hand-built .mo file,
and catalog discovery for the Settings language dropdown.
"""
import os
import struct
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import i18n


def _write_mo(path, mapping):
    """Write a minimal little-endian .mo file for the given msgid->msgstr map."""
    keys = sorted(mapping)
    offsets = []
    ids = b""
    strs = b""
    for key in keys:
        id_bytes = key.encode("utf-8")
        str_bytes = mapping[key].encode("utf-8")
        offsets.append((len(ids), len(id_bytes), len(strs), len(str_bytes)))
        ids += id_bytes + b"\x00"
        strs += str_bytes + b"\x00"

    n = len(keys)
    keystart = 7 * 4 + 16 * n
    valuestart = keystart + len(ids)
    koffsets = []
    voffsets = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]
    output = struct.pack("Iiiiiii", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
    output += struct.pack(f"{len(koffsets)}i", *koffsets)
    output += struct.pack(f"{len(voffsets)}i", *voffsets)
    output += ids + strs
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(output)


@pytest.fixture(autouse=True)
def _restore_default_translation():
    yield
    i18n.setup("en")


def test_identity_fallback_without_catalogs():
    i18n.setup("auto")
    assert i18n._("All Articles") == "All Articles"
    assert i18n._('Mark all items in "{feed}" as read?') == 'Mark all items in "{feed}" as read?'
    assert i18n.ngettext("one item", "many items", 1) == "one item"
    assert i18n.ngettext("one item", "many items", 3) == "many items"


def test_unknown_language_falls_back_to_english():
    i18n.setup("zz_XX")
    assert i18n._("All Articles") == "All Articles"


def test_loads_real_catalog_from_locale_dir(tmp_path, monkeypatch):
    mo_path = tmp_path / "xx" / "LC_MESSAGES" / "blindrss.mo"
    _write_mo(str(mo_path), {"All Articles": "Todos los articulos"})
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(tmp_path))

    i18n.setup("xx")
    assert i18n._("All Articles") == "Todos los articulos"
    # Untranslated strings still pass through.
    assert i18n._("Favorites") == "Favorites"

    assert i18n.available_languages() == ["xx"]


def test_available_languages_empty_when_no_catalogs(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(tmp_path))
    assert i18n.available_languages() == []
