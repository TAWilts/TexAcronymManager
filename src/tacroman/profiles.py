"""Load, validate, and migrate configurable command-definition profiles.

Profiles are intentionally data-driven.  The application only understands the
generic concepts below: a profile has independent commands, each command has
fields, and fields may opt into technical comparison or similarity groups.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .i18n import translate
from .storage import atomic_write_text


PROFILE_FIELDS = (
    "id",
    "name",
    "description",
    "preamble_hint",
    "header",
    "footer",
    "separator",
    "sort_by",
    "escape_mode",
    "usage_template",
    "commands",
)
LEGACY_ENTRY_FIELDS = ("short", "long", "category", "note")
DEFAULT_PROFILES_PATH = Path(__file__).with_name("defaults") / "profiles.json"
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")
_FIELD_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def _string(value: object) -> str:
    return value if isinstance(value, str) else str(value or "")


def _validate_identifier(value: str, *, language: str, kind: str) -> None:
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        key = "profile_invalid_command_id" if kind == "command" else "profile_invalid_id"
        raise ValueError(translate(language, key, id=value))


def _legacy_fields() -> list[dict[str, object]]:
    """Return a generous schema for a 0.2.x single-entry profile."""
    return [
        {"id": "short", "label": "Short form", "required": True, "comparison_group": "legacy-short"},
        {"id": "long", "label": "Long form", "required": True, "similarity_group": "legacy-long"},
        {"id": "category", "label": "Category", "required": False},
        {"id": "note", "label": "Note", "required": False, "multiline": True},
    ]


def _validate_field(field: object, *, language: str, command_id: str) -> dict[str, object]:
    if not isinstance(field, dict):
        raise ValueError(translate(language, "profile_invalid_field", command=command_id))
    clean = dict(field)
    field_id = _string(clean.get("id")).strip()
    if not field_id:
        raise ValueError(translate(language, "profile_missing_field_id", command=command_id))
    if not _FIELD_IDENTIFIER_PATTERN.fullmatch(field_id):
        raise ValueError(translate(language, "profile_invalid_field_id", field=field_id))
    clean["id"] = field_id
    clean["label"] = _string(clean.get("label") or field_id).strip()
    clean["required"] = bool(clean.get("required", False))
    clean["multiline"] = bool(clean.get("multiline", False))
    clean["comparison_group"] = _string(clean.get("comparison_group")).strip()
    clean["similarity_group"] = _string(clean.get("similarity_group")).strip()
    clean["case_sensitive"] = bool(clean.get("case_sensitive", False))
    clean["output_template"] = _string(clean.get("output_template") or "[[value]]")
    for warning_key in ("warn_whitespace", "warn_trailing_punctuation", "warn_braces"):
        clean[warning_key] = bool(clean.get(warning_key, False))
    if "[[value]]" not in clean["output_template"]:
        raise ValueError(translate(language, "profile_invalid_field_output_template", field=field_id))
    return clean


def _validate_command(command: object, *, language: str) -> dict[str, object]:
    if not isinstance(command, dict):
        raise ValueError(translate(language, "profile_invalid_command"))
    clean = dict(command)
    command_id = _string(clean.get("id")).strip()
    if not command_id:
        raise ValueError(translate(language, "profile_missing_command_id"))
    _validate_identifier(command_id, language=language, kind="command")
    clean["id"] = command_id
    clean["label"] = _string(clean.get("label") or command_id).strip()
    clean["description"] = _string(clean.get("description")).strip()
    clean["template"] = _string(clean.get("template"))
    clean["usage_template"] = _string(clean.get("usage_template"))
    clean["sort_by"] = _string(clean.get("sort_by")).strip()
    if not clean["template"]:
        raise ValueError(translate(language, "profile_missing_command_template", command=command_id))
    raw_fields = clean.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ValueError(translate(language, "profile_missing_command_fields", command=command_id))
    fields = [_validate_field(field, language=language, command_id=command_id) for field in raw_fields]
    field_ids = [str(field["id"]) for field in fields]
    if len(field_ids) != len(set(field_ids)):
        raise ValueError(translate(language, "profile_duplicate_field_id", command=command_id))
    if clean["sort_by"] and clean["sort_by"] not in {"none", *field_ids, "id"}:
        raise ValueError(translate(language, "profile_invalid_command_sort", command=command_id))
    clean["fields"] = fields
    return clean


def _legacy_command(profile: dict[str, object]) -> dict[str, object]:
    return {
        "id": "acronym",
        "label": "Acronym",
        "template": _string(profile.get("entry")),
        "usage_template": _string(profile.get("usage_template")),
        "fields": _legacy_fields(),
    }


def normalise_profile(profile: dict[str, object], *, language: str = "en") -> dict[str, object]:
    """Validate a profile and transparently adapt the 0.2.x schema.

    A legacy profile had one top-level ``entry`` template.  It becomes one
    generic command named ``acronym`` in memory, so old custom profile files
    continue to load without requiring user edits.
    """
    clean = dict(profile)
    profile_id = _string(clean.get("id")).strip()
    if not profile_id:
        raise ValueError(translate(language, "profile_missing_id"))
    _validate_identifier(profile_id, language=language, kind="profile")
    name = _string(clean.get("name")).strip()
    if not name:
        raise ValueError(translate(language, "profile_missing_name", id=profile_id))

    clean["id"] = profile_id
    clean["name"] = name
    for field in ("description", "preamble_hint", "header", "footer", "separator", "usage_template"):
        clean[field] = _string(clean.get(field))
    clean["sort_by"] = _string(clean.get("sort_by") or "short").strip()
    clean["escape_mode"] = _string(clean.get("escape_mode") or "none").strip()
    if clean["escape_mode"] not in {"none", "latex", "csv"}:
        raise ValueError(translate(language, "profile_invalid_escape"))

    raw_commands = clean.get("commands")
    if raw_commands is None:
        if not _string(clean.get("entry")):
            raise ValueError(translate(language, "profile_missing_entry", id=profile_id))
        raw_commands = [_legacy_command(clean)]
    if not isinstance(raw_commands, list) or not raw_commands:
        raise ValueError(translate(language, "profile_missing_commands", id=profile_id))
    commands = [_validate_command(command, language=language) for command in raw_commands]
    command_ids = [str(command["id"]) for command in commands]
    if len(command_ids) != len(set(command_ids)):
        raise ValueError(translate(language, "profile_duplicate_command_id", id=profile_id))
    clean["commands"] = commands
    clean["schema_version"] = max(2, int(clean.get("schema_version", 2) or 2))
    return clean


def _load_profile_file(path: Path, *, language: str) -> list[dict[str, object]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(translate(language, "profile_invalid_json", error=error)) from error
    if not isinstance(raw, list):
        raise ValueError(translate(language, "profile_invalid_shape"))
    return [normalise_profile(item, language=language) for item in raw if isinstance(item, dict)]


def load_profiles(custom_path: Path | None = None, *, language: str = "en") -> list[dict[str, object]]:
    """Load bundled profiles and optionally merge a user file by profile ID."""
    defaults = _load_profile_file(DEFAULT_PROFILES_PATH, language=language)
    if custom_path is None or not custom_path.exists():
        return defaults
    custom = _load_profile_file(custom_path, language=language)
    merged = {str(profile["id"]): profile for profile in defaults}
    for profile in custom:
        merged[str(profile["id"])] = profile
    return list(merged.values())


def save_profiles(path: Path, profiles: list[dict[str, object]], *, language: str = "en") -> None:
    clean_profiles = [normalise_profile(profile, language=language) for profile in profiles]
    atomic_write_text(path, json.dumps(clean_profiles, ensure_ascii=False, indent=2) + "\n")
