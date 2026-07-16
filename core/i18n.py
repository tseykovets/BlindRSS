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

# BCP-47 code of the catalog currently installed; see current_language().
_active_language = "en"


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

            # Note: do not name this local "windll" -- PyInstaller's ctypes
            # bytecode scanner treats `windll.X` as loading "X.dll" and warns
            # "Library GetUserDefaultUILanguage.dll required via ctypes not
            # found" at build time.
            kernel32 = ctypes.windll.kernel32
            lcid = kernel32.GetUserDefaultUILanguage()
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
    _remember_active_language(languages)


def _remember_active_language(languages: list) -> None:
    """Record the catalog language that actually loaded (see current_language)."""
    global _active_language
    resolved = ""
    # A real catalog reports its own language; NullTranslations (no catalog for
    # any requested language) has no info(), which is itself the answer: the
    # untranslated English source strings are what the user sees.
    try:
        info = _translation.info()
        resolved = str(info.get("language") or "").strip()
    except Exception:
        resolved = ""
    if not resolved:
        resolved = "en" if isinstance(_translation, gettext.NullTranslations) else ""
    if not resolved:
        resolved = str(languages[0]) if languages else "en"
    _active_language = resolved.replace("_", "-")


def current_language() -> str:
    """BCP-47 code of the UI language in effect (e.g. "ru", "pt-BR", "en").

    This is what the app is actually speaking, not what was requested: "auto"
    resolves to the OS locale, and a language with no catalog resolves to "en"
    because English source strings are the fallback. Used as the document
    language for the rich reader (issue #72) -- assistive tech needs to know
    which synthesizer and Braille table to use.
    """
    return _active_language or "en"


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
