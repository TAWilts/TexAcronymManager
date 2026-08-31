"""Shared per-user state for the desktop app and editor integrations."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any
from uuid import UUID, uuid4

from .storage import atomic_write_text, load_settings


STATE_FILENAME = "state.json"


def tacroman_user_directory(*, home: Path | None = None) -> Path:
    """Return the directory shared by every TAcroMan frontend."""
    return (home or Path.home()).expanduser() / "TAcroMan"


def shared_state_path(*, home: Path | None = None) -> Path:
    return tacroman_user_directory(home=home) / STATE_FILENAME


def vscode_integration_state_path() -> Path:
    """Compatibility alias for integrations importing the former function."""
    return shared_state_path()


def read_shared_state(path: Path | None = None) -> dict[str, Any]:
    """Read the one shared state file in the TAcroMan user directory."""
    return load_settings(path or shared_state_path())


def ensure_installation_id(path: Path | None = None) -> str:
    """Return the stable installation UUID shared by both local frontends."""
    target = path or shared_state_path()
    state = read_shared_state(target)
    value = state.get("installationId")
    if isinstance(value, str):
        try:
            return str(UUID(value))
        except ValueError:
            pass
    installation_id = str(uuid4())
    state["version"] = 2
    state["installationId"] = installation_id
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return installation_id


def clear_legacy_database_path(path: Path | None = None) -> None:
    target = path or shared_state_path()
    state = read_shared_state(target)
    state.pop("legacyDatabasePath", None)
    state.pop("databasePath", None)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def detect_editor_launcher(
    *,
    executable: str | Path | None = None,
    argv0: str | Path | None = None,
    platform: str | None = None,
    frozen: bool | None = None,
) -> dict[str, object]:
    """Return a launcher that can start this TAcroMan installation again."""
    python = Path(executable or sys.executable).expanduser().resolve()
    current_platform = platform or sys.platform
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)

    if is_frozen:
        return {"executable": str(python), "args": []}

    launcher_name = "tacroman.exe" if current_platform == "win32" else "tacroman"
    sibling_launcher = python.parent / launcher_name
    if sibling_launcher.is_file():
        return {"executable": str(sibling_launcher.resolve()), "args": []}

    raw_argv0 = str(argv0 if argv0 is not None else (sys.argv[0] if sys.argv else "")).strip()
    if raw_argv0:
        invoked = Path(raw_argv0).expanduser()
        try:
            invoked = invoked.resolve()
        except OSError:
            pass

        if invoked.is_file():
            suffix = invoked.suffix.casefold()
            name = invoked.name.casefold()
            if current_platform == "win32" and suffix in {".exe", ".cmd", ".bat"}:
                return {"executable": str(invoked), "args": []}
            if suffix == ".py" and name != "__main__.py":
                return {"executable": str(python), "args": [str(invoked)]}
            if current_platform != "win32" and suffix != ".py":
                return {"executable": str(invoked), "args": []}

    return {"executable": str(python), "args": ["-m", "tacroman"]}


def write_vscode_integration_state(
    workspace_path: str | Path | None = None,
    output_path: str | Path | None = None,
    *,
    fragment_path: str | Path | None = None,
    installation_id: str | None = None,
    legacy_database_path: str | Path | None = None,
    output_mode: str | None = None,
    language: str | None = None,
    state_path: Path | None = None,
) -> None:
    """Merge the active frontend state into the shared per-user file."""
    try:
        target = state_path or shared_state_path()
        payload: dict[str, Any] = read_shared_state(target)
        payload.pop("last_database_path", None)
        payload.pop("profilesPath", None)
        payload.pop("selectedProfileId", None)
        payload.pop("renderProfile", None)
        payload["version"] = 2
        payload["launcher"] = detect_editor_launcher()

        if workspace_path is not None and str(workspace_path).strip():
            payload["workspacePath"] = str(Path(workspace_path).expanduser().resolve())
            payload.pop("databasePath", None)
        if fragment_path is not None and str(fragment_path).strip():
            payload["fragmentPath"] = str(Path(fragment_path).expanduser().resolve())
        if installation_id:
            payload["installationId"] = str(UUID(installation_id))
        if legacy_database_path is not None and str(legacy_database_path).strip():
            payload["legacyDatabasePath"] = str(Path(legacy_database_path).expanduser().resolve())
        if output_path is not None and str(output_path).strip():
            payload["outputPath"] = str(Path(output_path).expanduser().resolve())
        if output_mode in {"project", "database", "custom"}:
            payload["outputMode"] = output_mode
        if language:
            payload["language"] = language

        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    except (OSError, UnicodeError, ValueError, TypeError):
        return
