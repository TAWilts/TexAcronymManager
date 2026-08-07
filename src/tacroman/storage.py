"""Atomic JSON persistence for generic command databases and settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .i18n import translate
from .model import Acronym, CommandEntry, acronym_to_entry


SCHEMA_VERSION = 2


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


def load_database(path: Path, *, language: str = "en") -> list[CommandEntry]:
    """Load generic v2 databases and transparently migrate v1 acronym data."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(translate(language, "database_invalid_json", error=error)) from error

    if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
        records = raw["entries"]
        if not all(isinstance(record, dict) for record in records):
            raise ValueError(translate(language, "database_invalid_entry"))
        return [CommandEntry.from_dict(record) for record in records]

    # The 0.1/0.2 formats were either a raw list or an object with ``acronyms``.
    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict) and isinstance(raw.get("acronyms"), list):
        records = raw["acronyms"]
    else:
        raise ValueError(translate(language, "database_invalid_shape"))
    if not all(isinstance(record, dict) for record in records):
        raise ValueError(translate(language, "database_invalid_entry"))
    return [acronym_to_entry(Acronym.from_dict(record)) for record in records]


def save_database(path: Path, entries: list[CommandEntry]) -> None:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "entries": [entry.to_dict() for entry in entries],
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
