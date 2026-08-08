"""Render generic command entries from profile-defined templates."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from difflib import SequenceMatcher
from io import StringIO
import re
from typing import Callable, Literal

from .i18n import translate
from .model import Acronym, CommandEntry, acronym_to_entry, command_fields, command_map, make_identifier


TOKEN_PATTERN = re.compile(r"\[\[([A-Za-z][A-Za-z0-9_]*)\]\]")
VALUE_TOKEN_PATTERN = re.compile(r"\[\[value\]\]")
SPECIAL_TOKENS = {"id", "command"}


@dataclass(frozen=True)
class PreviewLine:
    """One display line in a preview, optionally annotated with its change type."""

    text: str
    change: Literal["unchanged", "added", "removed"]


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


def _replace_tokens(template: str, values: dict[str, str]) -> str:
    return TOKEN_PATTERN.sub(lambda match: values.get(match.group(1), match.group(0)), template)


def _identifier_seed(entry: CommandEntry, command: dict[str, object]) -> str:
    for field_id in ("short", "key"):
        if entry.value(field_id).strip():
            return entry.value(field_id).strip()
    for field in command_fields(command):
        value = entry.value(str(field["id"])).strip()
        if value:
            return value
    return entry.command_id


def values_for_entry(
    entry: CommandEntry,
    command: dict[str, object],
    *,
    escape_mode: str = "none",
) -> dict[str, str]:
    """Resolve field values and optional field-specific output wrappers."""
    escape = _escape_function(escape_mode)
    values: dict[str, str] = {}
    for field in command_fields(command):
        field_id = str(field["id"])
        raw_value = entry.value(field_id).strip()
        if not raw_value:
            values[field_id] = ""
            continue
        output_template = str(field.get("output_template", "[[value]]"))
        values[field_id] = VALUE_TOKEN_PATTERN.sub(lambda _match: escape(raw_value), output_template)

    explicit_identifier = entry.value("id").strip()
    values["id"] = escape(explicit_identifier or make_identifier(_identifier_seed(entry, command)))
    values["command"] = escape(entry.command_id)
    return values


def profile_template_warnings(profile: dict[str, object], *, language: str = "en") -> list[str]:
    """Return non-blocking messages for unknown placeholders in a profile."""
    warnings: list[str] = []
    for command in profile.get("commands", []):
        if not isinstance(command, dict):
            continue
        command_id = str(command.get("id", "?"))
        allowed = {str(field["id"]) for field in command_fields(command)} | SPECIAL_TOKENS
        for template_key in ("template", "usage_template"):
            unknown = set(TOKEN_PATTERN.findall(str(command.get(template_key, "")))) - allowed
            if unknown:
                warnings.append(
                    translate(
                        language,
                        "profile_unknown_command_tokens",
                        command=command_id,
                        field=template_key,
                        tokens=", ".join(sorted(unknown)),
                    )
                )
        for field in command_fields(command):
            output_template = str(field.get("output_template", "[[value]]"))
            if "[[value]]" not in output_template:
                warnings.append(
                    translate(language, "profile_invalid_field_output_template", field=str(field["id"]))
                )
    return warnings


def _sort_key(entry: CommandEntry, command: dict[str, object], profile: dict[str, object]) -> str:
    sort_by = str(command.get("sort_by") or profile.get("sort_by") or "none")
    if sort_by == "none":
        return ""
    if sort_by == "identifier":  # 0.2.x spelling retained for old profiles.
        sort_by = "id"
    return values_for_entry(entry, command, escape_mode="none").get(sort_by, "").casefold()


def _as_command_entries(entries: list[CommandEntry | Acronym]) -> list[CommandEntry]:
    return [acronym_to_entry(entry) if isinstance(entry, Acronym) else entry for entry in entries]


def rendered_entries(
    entries: list[CommandEntry | Acronym],
    profile: dict[str, object],
    *,
    preserve_input_order: bool = False,
) -> list[CommandEntry]:
    """Return exactly the entries rendered by the active profile, in order.

    ``preserve_input_order`` is used by the desktop app when the user has
    chosen a column order in the entry table. It intentionally bypasses the
    profile's command grouping and ``sort_by`` settings while still omitting
    entries whose command type is not part of the active profile.
    """
    command_entries = _as_command_entries(entries)
    if preserve_input_order:
        known_command_ids = {
            str(command["id"])
            for command in profile.get("commands", [])
            if isinstance(command, dict)
        }
        return [entry for entry in command_entries if entry.command_id in known_command_ids]

    result: list[CommandEntry] = []
    for command in profile.get("commands", []):
        if not isinstance(command, dict):
            continue
        command_id = str(command["id"])
        group = [entry for entry in command_entries if entry.command_id == command_id]
        if str(command.get("sort_by") or profile.get("sort_by") or "none") != "none":
            group.sort(key=lambda entry: _sort_key(entry, command, profile))
        result.extend(group)
    return result


def render(
    entries: list[CommandEntry | Acronym],
    profile: dict[str, object],
    *,
    preserve_input_order: bool = False,
) -> str:
    """Render an output file exclusively from the active profile definition."""
    commands = command_map(profile)
    mode = str(profile.get("escape_mode", "none"))
    rendered_lines: list[str] = []
    for entry in rendered_entries(entries, profile, preserve_input_order=preserve_input_order):
        command = commands[entry.command_id]
        values = values_for_entry(entry, command, escape_mode=mode)
        rendered_lines.append(_replace_tokens(str(command["template"]), values))
    return "".join(
        (
            str(profile.get("header", "")),
            str(profile.get("separator", "\n")).join(rendered_lines),
            str(profile.get("footer", "")),
        )
    )


def preview_diff(previous: str | None, current: str) -> list[PreviewLine]:
    """Return a line-oriented preview diff, keeping removed lines visible.

    The first preview has no comparison baseline, so every line is unchanged.
    Removed lines are display-only; callers should copy ``current`` rather than
    reconstructing it from this result.
    """
    current_lines = current.splitlines(keepends=True)
    if previous is None:
        return [PreviewLine(line, "unchanged") for line in current_lines]

    previous_lines = previous.splitlines(keepends=True)
    result: list[PreviewLine] = []
    matcher = SequenceMatcher(None, previous_lines, current_lines, autojunk=False)
    for change, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if change == "equal":
            result.extend(PreviewLine(line, "unchanged") for line in current_lines[new_start:new_end])
        if change in {"delete", "replace"}:
            result.extend(PreviewLine(line, "removed") for line in previous_lines[old_start:old_end])
        if change in {"insert", "replace"}:
            result.extend(PreviewLine(line, "added") for line in current_lines[new_start:new_end])
    return result


def usage_for(entry: CommandEntry, profile: dict[str, object]) -> str:
    """Return the command-specific usage snippet, if the profile defines one."""
    command = command_map(profile).get(entry.command_id)
    if command is None:
        return ""
    template = str(command.get("usage_template") or profile.get("usage_template") or "")
    if not template:
        return ""
    return _replace_tokens(template, values_for_entry(entry, command, escape_mode="none"))
