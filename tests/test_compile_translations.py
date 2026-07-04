import gettext
from pathlib import Path

from tools import compile_translations


def test_compile_catalog_writes_loadable_mo(tmp_path):
    catalog_dir = tmp_path / "locale" / "ru" / "LC_MESSAGES"
    catalog_dir.mkdir(parents=True)
    po = catalog_dir / "blindrss.po"
    po.write_text(
        'msgid ""\n'
        'msgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n'
        "\n"
        'msgid "All Articles"\n'
        'msgstr "Все статьи"\n'
        "\n"
        'msgid "{count} item"\n'
        'msgid_plural "{count} items"\n'
        'msgstr[0] "{count} элемент"\n'
        'msgstr[1] "{count} элементов"\n',
        encoding="utf-8",
    )

    mo = compile_translations.compile_catalog(po)

    with mo.open("rb") as fh:
        translations = gettext.GNUTranslations(fh)
    assert translations.gettext("All Articles") == "Все статьи"
    assert translations.ngettext("{count} item", "{count} items", 2) == "{count} элементов"


def test_iter_catalogs_finds_blindrss_po_only(tmp_path):
    good = tmp_path / "ru" / "LC_MESSAGES" / "blindrss.po"
    good.parent.mkdir(parents=True)
    good.write_text('msgid ""\nmsgstr ""\n', encoding="utf-8")
    other = tmp_path / "ru" / "LC_MESSAGES" / "other.po"
    other.write_text('msgid ""\nmsgstr ""\n', encoding="utf-8")

    assert compile_translations.iter_catalogs(tmp_path) == [good]


def test_repository_russian_catalog_has_readable_cyrillic():
    catalog = Path("locale/ru/LC_MESSAGES/blindrss.po")
    messages = compile_translations.read_po(catalog)

    assert messages["All Articles"] == "Все статьи"
    assert "Ð" not in messages["All Articles"]
