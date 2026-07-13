"""gettext internationalization plumbing (issue #44).

Verifies the identity fallback (no catalogs -> English passthrough, the state
every existing user is in), real catalog loading via a hand-built .mo file,
and catalog discovery for the Settings language dropdown.
"""
import os
import struct
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import i18n
from core import utils
from tools import compile_translations, extract_strings


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


def test_russian_relative_date_plural_forms(tmp_path, monkeypatch):
    messages = compile_translations.read_po(
        Path("locale/ru/LC_MESSAGES/blindrss.po")
    )
    mo_path = tmp_path / "ru" / "LC_MESSAGES" / "blindrss.mo"
    compile_translations.write_mo(messages, mo_path)
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(tmp_path))
    i18n.setup("ru")

    now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    assert utils.humanize_article_date("2026-07-12 11:59:00", now) == "1 минуту назад"
    assert utils.humanize_article_date("2026-07-12 11:58:00", now) == "2 минуты назад"
    assert utils.humanize_article_date("2026-07-12 11:55:00", now) == "5 минут назад"
    assert utils.humanize_article_date("2026-07-12 07:00:00", now) == "5 часов назад"
    assert i18n._("Date:") == "Дата:"
    assert i18n._("Articles loaded: {count}.").format(count=1) == "Загружено статей: 1."


def test_russian_ui_plural_forms(tmp_path, monkeypatch):
    messages = compile_translations.read_po(
        Path("locale/ru/LC_MESSAGES/blindrss.po")
    )
    mo_path = tmp_path / "ru" / "LC_MESSAGES" / "blindrss.mo"
    compile_translations.write_mo(messages, mo_path)
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(tmp_path))
    i18n.setup("ru")

    singular = "Could not delete article."
    plural = "Could not delete {n} articles."
    forms = messages[f"{singular}\0{plural}"].split("\0")

    assert len(forms) == 3
    assert i18n.ngettext(singular, plural, 1) == forms[0]
    assert i18n.ngettext(singular, plural, 2) == forms[1]
    assert i18n.ngettext(singular, plural, 5) == forms[2]


def test_extractor_resolves_deferred_module_string_constants(tmp_path):
    source = tmp_path / "deferred.py"
    source.write_text(
        'MEDIA_LABEL = "Contains audio"\n'
        "def label():\n"
        "    return _(MEDIA_LABEL)\n",
        encoding="utf-8",
    )
    messages = OrderedDict()

    extract_strings._collect(str(source), messages)

    assert ("Contains audio", None) in messages


def test_repository_pot_matches_current_source(tmp_path, monkeypatch):
    generated = tmp_path / "blindrss.pot"
    monkeypatch.setattr(extract_strings, "POT_PATH", str(generated))

    extract_strings.main()

    assert generated.read_text(encoding="utf-8") == Path(
        "locale/blindrss.pot"
    ).read_text(encoding="utf-8")
