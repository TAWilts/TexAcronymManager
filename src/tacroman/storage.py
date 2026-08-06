"""Atomic JSON persistence for the acronym database and app settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .i18n import translate
from .model import Acronym

SCHEMA_VERSION = 1


def atomic_write_text(path: Path, content: str) -> None:
    """Replace a text file atomically, which is friendlier to sync clients."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def _atomic_json_write(path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def load_database(path: Path, *, language: str = "en") -> list[Acronym]:
    """Load entries from ``path``; a non-existing database is simply empty."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(translate(language, "database_invalid_json", error=error)) from error

    if isinstance(raw, list):  # Graceful support for early/manual databases.
        records = raw
    elif isinstance(raw, dict) and isinstance(raw.get("acronyms"), list):
        records = raw["acronyms"]
    else:
        raise ValueError(translate(language, "database_invalid_shape"))

    if not all(isinstance(record, dict) for record in records):
        raise ValueError(translate(language, "database_invalid_entry"))
    return [Acronym.from_dict(record) for record in records]


def save_database(path: Path, entries: list[Acronym]) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "acronyms": [entry.to_dict() for entry in entries],
    }
    _atomic_json_write(path, payload)


def load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(path: Path, settings: dict[str, Any]) -> None:
    _atomic_json_write(path, settings)
