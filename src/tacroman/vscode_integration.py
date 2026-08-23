"""Small, stable bridge between the desktop app and editor integrations.

The VS Code extension should not need to know the internal format/location of
TAcroMan's regular settings. Instead the desktop app publishes just the pieces
an editor needs to a tiny integration-state file in the user's config folder.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from .storage import atomic_write_text


def vscode_integration_state_path() -> Path:
    """Return the cross-platform per-user integration-state path."""
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "TAcroMan" / "vscode-integration.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "TAcroMan" / "vscode-integration.json"
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "tacroman" / "vscode-integration.json"


def detect_editor_launcher(
    *,
    executable: str | Path | None = None,
    argv0: str | Path | None = None,
    platform: str | None = None,
    frozen: bool | None = None,
) -> dict[str, object]:
    """Return a launcher that can start this TAcroMan installation again.

    Preference order:
    1. A frozen/bundled executable (e.g. a future packaged TAcroMan build).
    2. The ``tacroman`` console launcher next to the active Python interpreter.
       Editable/venv installations created with ``pip install -e .`` normally
       provide exactly this launcher.
    3. The executable/script that launched the current process, when usable.
    4. ``python -m tacroman`` as a portable fallback.
    """
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


def write_vscode_integration_state(database_path: str | Path) -> None:
    """Publish the active database and launcher for editor integrations.

    This is deliberately best-effort. Integration metadata must never make
    normal TAcroMan usage fail because a config directory is not writable.
    """
    try:
        payload: dict[str, object] = {
            "launcher": detect_editor_launcher(),
        }

        raw = str(database_path).strip()
        if raw:
            payload["databasePath"] = str(Path(raw).expanduser().resolve())

        target = vscode_integration_state_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            target,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
    except (OSError, UnicodeError, ValueError):
        return
