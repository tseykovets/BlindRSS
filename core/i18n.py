"""Interface internationalization via gettext (issue #44).

English source strings are the message keys (gettext convention), so with no
translation catalog installed every ``_()`` call returns its argument and the
app behaves exactly as before. Translations live in
``locale/<lang>/LC_MESSAGES/blindrss.mo``; ``tools/extract_strings.py``
regenerates the ``blindrss.pot`` template translators start from.

Usage in application code::

    from core.i18n import _
    label = _("All Articles")

``setup()`` must run before GUI modules build their menus/labels (main.py does
this right after loading config). The selected language comes from the
``"language"`` config key: ``"auto"`` (default) follows the OS locale, any
other value is a language code such as ``"ru"`` or ``"pt_BR"``.
"""

import gettext
import locale
import logging
import os
import sys

log = logging.getLogger(__name__)

DOMAIN = "blindrss"

_translation = gettext.NullTranslations()


def locale_dir() -> str:
    """Directory holding <lang>/LC_MESSAGES/blindrss.mo, source tree or frozen."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "locale")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locale")


def _system_languages() -> list:
    languages = []
    for env_key in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(env_key)
        if value:
            languages.extend(part for part in value.split(":") if part)
            break
    try:
        system_locale = locale.getlocale()[0]
        if system_locale:
            languages.append(system_locale)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            windll = ctypes.windll.kernel32
            lcid = windll.GetUserDefaultUILanguage()
            name = locale.windows_locale.get(lcid)
            if name:
                languages.append(name)
        except Exception:
            pass
    return languages


def setup(language: str = "auto") -> None:
    """Install the translation catalog for ``language`` ("auto" = OS locale)."""
    global _translation
    language = str(language or "auto").strip()
    if language.lower() in ("", "auto"):
        languages = _system_languages()
    else:
        languages = [language]

    try:
        _translation = gettext.translation(
            DOMAIN, localedir=locale_dir(), languages=languages, fallback=True
        )
    except Exception:
        log.debug("Failed to load translations for %r", languages, exc_info=True)
        _translation = gettext.NullTranslations()


def _(message: str) -> str:
    """Translate ``message`` using the installed catalog (identity fallback)."""
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Plural-aware translation (identity English fallback)."""
    return _translation.ngettext(singular, plural, n)


def available_languages() -> list:
    """Language codes that have a compiled catalog on disk (for Settings)."""
    found = []
    base = locale_dir()
    try:
        for entry in sorted(os.listdir(base)):
            mo = os.path.join(base, entry, "LC_MESSAGES", DOMAIN + ".mo")
            if os.path.isfile(mo):
                found.append(entry)
    except OSError:
        pass
    return found
