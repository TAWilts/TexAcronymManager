"""Stable bridge from desktop TAcroMan to editor integrations."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from .storage import atomic_write_text


def vscode_integration_state_path() -> Path:
    """Return the per-user state file used by the VS Code extension."""
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "TAcroMan" / "vscode-integration.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "TAcroMan" / "vscode-integration.json"
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "tacroman" / "vscode-integration.json"


def write_vscode_integration_state(database_path: str | Path) -> None:
    """Publish the currently selected database path, best-effort."""
    raw = str(database_path).strip()
    if not raw:
        return

    try:
        database = str(Path(raw).expanduser().resolve())
        target = vscode_integration_state_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            target,
            json.dumps({"databasePath": database}, ensure_ascii=False, indent=2) + "\n",
        )
    except (OSError, UnicodeError, ValueError):
        return
