"""Configurable output profiles.

Profiles deliberately use ``[[field]]`` placeholders instead of Python's
``str.format``.  LaTeX braces can therefore be written naturally in a profile.
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
    "entry",
    "footer",
    "separator",
    "sort_by",
    "escape_mode",
    "usage_template",
)

DEFAULT_PROFILES_PATH = Path(__file__).with_name("defaults") / "profiles.json"


def _validate_profile(profile: dict[str, Any], *, language: str) -> dict[str, str]:
    clean = {field: str(profile.get(field, "")) for field in PROFILE_FIELDS}
    if not clean["id"].strip():
        raise ValueError(translate(language, "profile_missing_id"))
    if not re.fullmatch(r"[A-Za-z0-9._-]+", clean["id"]):
        raise ValueError(translate(language, "profile_invalid_id"))
    if not clean["name"].strip():
        raise ValueError(translate(language, "profile_missing_name", id=clean["id"]))
    if not clean["entry"]:
        raise ValueError(translate(language, "profile_missing_entry", id=clean["id"]))
    if clean["sort_by"] not in {"short", "long", "identifier", "category", "none"}:
        raise ValueError(translate(language, "profile_invalid_sort"))
    if clean["escape_mode"] not in {"none", "latex", "csv"}:
        raise ValueError(translate(language, "profile_invalid_escape"))
    return clean


def _load_profile_file(path: Path, *, language: str) -> list[dict[str, str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(translate(language, "profile_invalid_json", error=error)) from error
    if not isinstance(raw, list):
        raise ValueError(translate(language, "profile_invalid_shape"))
    return [_validate_profile(item, language=language) for item in raw if isinstance(item, dict)]


def load_profiles(custom_path: Path | None = None, *, language: str = "en") -> list[dict[str, str]]:
    """Load built-ins and optionally merge a user's profile file by ID."""
    defaults = _load_profile_file(DEFAULT_PROFILES_PATH, language=language)
    if custom_path is None or not custom_path.exists():
        return defaults
    custom = _load_profile_file(custom_path, language=language)
    merged = {profile["id"]: profile for profile in defaults}
    for profile in custom:
        merged[profile["id"]] = profile
    return list(merged.values())


def save_profiles(path: Path, profiles: list[dict[str, str]], *, language: str = "en") -> None:
    clean_profiles = [_validate_profile(profile, language=language) for profile in profiles]
    atomic_write_text(path, json.dumps(clean_profiles, ensure_ascii=False, indent=2) + "\n")
