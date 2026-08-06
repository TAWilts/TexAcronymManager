"""Render entries using a profile without requiring a template dependency."""

from __future__ import annotations

import csv
from io import StringIO
import re
from typing import Callable

from .i18n import translate
from .model import Acronym

TOKEN_PATTERN = re.compile(r"\[\[([a-z_]+)\]\]")
ALLOWED_TOKENS = {"short", "long", "id", "category", "note"}

_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(value: str) -> str:
    return "".join(_LATEX_ESCAPES.get(character, character) for character in value)


def csv_escape(value: str) -> str:
    stream = StringIO()
    csv.writer(stream, lineterminator="").writerow([value])
    return stream.getvalue()


def _escape_function(mode: str) -> Callable[[str], str]:
    return {"none": lambda value: value, "latex": latex_escape, "csv": csv_escape}[mode]


def profile_template_warnings(profile: dict[str, str], *, language: str = "en") -> list[str]:
    warnings: list[str] = []
    for field in ("header", "entry", "footer", "separator", "usage_template"):
        unknown = set(TOKEN_PATTERN.findall(profile.get(field, ""))) - ALLOWED_TOKENS
        if unknown:
            warnings.append(translate(language, "profile_unknown_tokens", field=field, tokens=", ".join(sorted(unknown))))
    if "[[short]]" not in profile.get("entry", "") and "[[id]]" not in profile.get("entry", ""):
        warnings.append(translate(language, "profile_missing_short"))
    return warnings


def _replace_tokens(template: str, values: dict[str, str]) -> str:
    return TOKEN_PATTERN.sub(lambda match: values.get(match.group(1), match.group(0)), template)


def render(entries: list[Acronym], profile: dict[str, str]) -> str:
    """Render an output file.  No text is added that the profile did not ask for."""
    mode = profile.get("escape_mode", "none")
    escape = _escape_function(mode)
    sort_by = profile.get("sort_by", "short")
    ordered = list(entries)
    if sort_by != "none":
        ordered.sort(key=lambda entry: getattr(entry, sort_by).casefold())

    rendered_entries: list[str] = []
    for acronym in ordered:
        values = {
            "short": escape(acronym.short.strip()),
            "long": escape(acronym.long.strip()),
            "id": escape(acronym.identifier),
            "category": escape(acronym.category.strip()),
            "note": escape(acronym.note.strip()),
        }
        rendered_entries.append(_replace_tokens(profile["entry"], values))

    return "".join(
        (
            _replace_tokens(profile.get("header", ""), {}),
            profile.get("separator", "\n").join(rendered_entries),
            _replace_tokens(profile.get("footer", ""), {}),
        )
    )


def usage_for(acronym: Acronym, profile: dict[str, str]) -> str:
    values = {
        "short": acronym.short.strip(),
        "long": acronym.long.strip(),
        "id": acronym.identifier,
        "category": acronym.category.strip(),
        "note": acronym.note.strip(),
    }
    return _replace_tokens(profile.get("usage_template", ""), values)
