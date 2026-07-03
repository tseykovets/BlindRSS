# BlindRSS Translations

BlindRSS uses gettext for interface internationalization (issue #44). English
source strings are the message keys; when no catalog matches the selected
language, the interface stays in English.

## Layout

```
locale/
  blindrss.pot                     <- template, regenerated from source
  <lang>/LC_MESSAGES/blindrss.po   <- editable translation
  <lang>/LC_MESSAGES/blindrss.mo   <- compiled catalog the app loads
```

## Adding or updating a translation

1. Regenerate the template after string changes:

   ```
   python tools/extract_strings.py
   ```

2. Start a new language (example: Russian):

   ```
   msginit -i locale/blindrss.pot -o locale/ru/LC_MESSAGES/blindrss.po -l ru
   ```

   or update an existing one:

   ```
   msgmerge -U locale/ru/LC_MESSAGES/blindrss.po locale/blindrss.pot
   ```

3. Translate the `msgstr` entries (any PO editor works, e.g. Poedit — which is
   screen-reader accessible — or a plain text editor).

4. Compile:

   ```
   msgfmt locale/ru/LC_MESSAGES/blindrss.po -o locale/ru/LC_MESSAGES/blindrss.mo
   ```

5. Restart BlindRSS. The language is selected in Settings > General >
   "Interface language" ("Automatic" follows the OS locale), or via the
   `"language"` key in config.json.

Compiled `.mo` files present at build time are bundled automatically by
`main.spec` / `portable.spec`.

Notes for translators:

- Keep `{placeholder}` tokens exactly as written; they are substituted at
  runtime (e.g. `Unread: {count}`).
- An `&` marks the menu access key (e.g. `&File`); place it before whichever
  letter works best in your language.
- Trailing `...` means the item opens a dialog; keep it.
