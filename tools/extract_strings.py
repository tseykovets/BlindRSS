"""Generate locale/blindrss.pot from _("...") calls in the source tree (issue #44).

Walks gui/, core/, and main.py with the ast module (no external tooling
needed), collects string literals passed to ``_()`` and ``ngettext()``, and
writes a gettext POT template translators can start a new language from:

    python tools/extract_strings.py
    msginit -i locale/blindrss.pot -o locale/ru/LC_MESSAGES/blindrss.po -l ru
    ... translate ...
    msgfmt locale/ru/LC_MESSAGES/blindrss.po -o locale/ru/LC_MESSAGES/blindrss.mo
"""

import ast
import os
import sys
from collections import OrderedDict

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCAN_TARGETS = ["main.py", "gui", "core", "providers"]
POT_PATH = os.path.join(REPO_ROOT, "locale", "blindrss.pot")


def _iter_python_files():
    for target in SCAN_TARGETS:
        path = os.path.join(REPO_ROOT, target)
        if os.path.isfile(path):
            yield path
            continue
        for dirpath, _dirnames, filenames in os.walk(path):
            for name in filenames:
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)


def _collect(path, messages):
    with open(path, "r", encoding="utf-8-sig") as fh:
        source = fh.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        print(f"WARNING: skipping {path}: {exc}", file=sys.stderr)
        return
    rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name == "_" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                messages.setdefault((arg.value, None), []).append(f"{rel}:{node.lineno}")
        elif name == "ngettext" and len(node.args) >= 2:
            one, many = node.args[0], node.args[1]
            if (
                isinstance(one, ast.Constant) and isinstance(one.value, str)
                and isinstance(many, ast.Constant) and isinstance(many.value, str)
            ):
                messages.setdefault((one.value, many.value), []).append(f"{rel}:{node.lineno}")


def _po_escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def main():
    messages = OrderedDict()
    for path in sorted(_iter_python_files()):
        _collect(path, messages)

    os.makedirs(os.path.dirname(POT_PATH), exist_ok=True)
    with open(POT_PATH, "w", encoding="utf-8", newline="\n") as out:
        out.write(
            'msgid ""\n'
            'msgstr ""\n'
            '"Project-Id-Version: BlindRSS\\n"\n'
            '"MIME-Version: 1.0\\n"\n'
            '"Content-Type: text/plain; charset=UTF-8\\n"\n'
            '"Content-Transfer-Encoding: 8bit\\n"\n'
            '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n'
        )
        for (singular, plural), locations in messages.items():
            out.write("\n")
            for loc in locations[:4]:
                out.write(f"#: {loc}\n")
            out.write(f'msgid "{_po_escape(singular)}"\n')
            if plural is None:
                out.write('msgstr ""\n')
            else:
                out.write(f'msgid_plural "{_po_escape(plural)}"\n')
                out.write('msgstr[0] ""\n')
                out.write('msgstr[1] ""\n')

    print(f"Wrote {len(messages)} messages to {POT_PATH}")


if __name__ == "__main__":
    main()
