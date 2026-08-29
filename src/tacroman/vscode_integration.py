"""Shared per-user state for the desktop app and editor integrations."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

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
    database_path: str | Path | None = None,
    output_path: str | Path | None = None,
    *,
    output_mode: str | None = None,
    profiles_path: str | Path | None = None,
    selected_profile_id: str | None = None,
    language: str | None = None,
    render_profile: dict[str, object] | None = None,
    state_path: Path | None = None,
) -> None:
    """Merge the active frontend state into the shared per-user file."""
    try:
        target = state_path or shared_state_path()
        payload: dict[str, Any] = read_shared_state(target)
        payload.pop("last_database_path", None)
        payload["version"] = 1
        payload["launcher"] = detect_editor_launcher()

        if database_path is not None and str(database_path).strip():
            resolved = str(Path(database_path).expanduser().resolve())
            payload["databasePath"] = resolved
        if output_path is not None and str(output_path).strip():
            payload["outputPath"] = str(Path(output_path).expanduser().resolve())
        if output_mode in {"project", "database", "custom"}:
            payload["outputMode"] = output_mode
        if profiles_path is not None and str(profiles_path).strip():
            payload["profilesPath"] = str(Path(profiles_path).expanduser().resolve())
        if selected_profile_id:
            payload["selectedProfileId"] = selected_profile_id
        if language:
            payload["language"] = language
        if render_profile is not None:
            payload["renderProfile"] = render_profile

        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    except (OSError, UnicodeError, ValueError, TypeError):
        return
