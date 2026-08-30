"""Native desktop host for the shared TAcroMan web frontend."""

from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
import threading
from typing import Any, Callable

from .i18n import DEFAULT_LANGUAGE, normalize_language
from .model import CommandEntry, command_map, comparison_matches, validate_entry
from .profiles import load_profiles
from .rendering import render
from .storage import atomic_write_text, load_database, save_database
from .vscode_integration import read_shared_state, shared_state_path, write_vscode_integration_state


APP_NAME = "TAcroMan"
PROFILE_FILENAME = "tacroman-render-profiles.json"
MessageEmitter = Callable[[dict[str, object]], None]
PathChooser = Callable[[Path], Path | None]


class DatabaseConflictError(ValueError):
    """Raised when another frontend changed the database before a mutation."""


def _default_database_path() -> Path:
    return Path.home() / APP_NAME / "entries.json"


def _resolved_path(value: object) -> Path | None:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        return None
    try:
        return Path(value).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def _database_revision(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _editor_profile(profile: dict[str, object]) -> dict[str, object]:
    commands: list[dict[str, object]] = []
    for raw_command in profile.get("commands", []):
        if not isinstance(raw_command, dict):
            continue
        fields: list[dict[str, object]] = []
        for raw_field in raw_command.get("fields", []):
            if not isinstance(raw_field, dict) or not str(raw_field.get("id", "")).strip():
                continue
            field_id = str(raw_field["id"])
            field: dict[str, object] = {
                "id": field_id,
                "label": str(raw_field.get("label") or field_id),
                "required": raw_field.get("required") is True,
                "multiline": raw_field.get("multiline") is True,
            }
            comparison_group = str(raw_field.get("comparison_group", "")).strip()
            if comparison_group:
                field["comparisonGroup"] = comparison_group
            fields.append(field)
        command_id = str(raw_command.get("id", "")).strip()
        if command_id and fields:
            commands.append(
                {
                    "id": command_id,
                    "label": str(raw_command.get("label") or command_id),
                    "description": str(raw_command.get("description") or ""),
                    "fields": fields,
                }
            )
    return {
        "id": str(profile.get("id") or "profile"),
        "name": str(profile.get("name") or APP_NAME),
        "commands": commands,
    }


def build_desktop_html() -> str:
    """Embed the shared frontend in one self-contained desktop document."""
    assets = files("tacroman.web_ui")
    template = assets.joinpath("index.html").read_text(encoding="utf-8")
    stylesheet = assets.joinpath("app.css").read_text(encoding="utf-8")
    script = assets.joinpath("app.js").read_text(encoding="utf-8")
    template = template.replace(
        '  <meta http-equiv="Content-Security-Policy" content="{{CSP}}">\n',
        "",
    )
    template = template.replace(
        '  <link rel="stylesheet" href="{{STYLE_URI}}">',
        f"  <style>\n{stylesheet}\n  </style>",
    )
    return template.replace(
        '  <script nonce="{{NONCE}}" src="{{SCRIPT_URI}}"></script>',
        f"  <script>\n{script}\n  </script>",
    )


class WebAppController:
    """GUI-independent message and persistence controller for the web UI."""

    def __init__(
        self,
        database_path: Path | None = None,
        output_path: Path | None = None,
        profiles_path: Path | None = None,
        *,
        state_path: Path | None = None,
        emit: MessageEmitter | None = None,
        choose_database: PathChooser | None = None,
        choose_output: PathChooser | None = None,
    ) -> None:
        self.state_path = (state_path or shared_state_path()).expanduser().resolve()
        self.emit = emit or (lambda _message: None)
        self.choose_database = choose_database
        self.choose_output = choose_output
        self._lock = threading.RLock()

        state = read_shared_state(self.state_path)
        stored_database = _resolved_path(state.get("databasePath"))
        self.database_path = (database_path or stored_database or _default_database_path()).expanduser().resolve()
        if not self.database_path.exists():
            save_database(self.database_path, [])

        shared_matches_database = stored_database == self.database_path
        stored_output = _resolved_path(state.get("outputPath")) if shared_matches_database else None
        self.output_path = (output_path or stored_output or self.database_path.with_suffix(".tex")).expanduser().resolve()
        stored_mode = str(state.get("outputMode", ""))
        self.output_mode = (
            stored_mode
            if shared_matches_database and stored_mode in {"project", "database", "custom"}
            else ("custom" if output_path is not None else "database")
        )
        stored_profiles = _resolved_path(state.get("profilesPath")) if shared_matches_database else None
        self.profiles_path = (
            profiles_path or stored_profiles or self.database_path.parent / PROFILE_FILENAME
        ).expanduser().resolve()
        self.language = normalize_language(str(state.get("language") or DEFAULT_LANGUAGE))
        self.selected_profile_id = str(state.get("selectedProfileId") or "acronym-package")
        self.profiles: list[dict[str, object]] = []
        self._load_profiles()
        self._known_database_revision = _database_revision(self.database_path)
        self._write_output(self._entries())
        self._publish_state()

    @property
    def active_profile(self) -> dict[str, object]:
        return next(
            (profile for profile in self.profiles if str(profile["id"]) == self.selected_profile_id),
            self.profiles[0],
        )

    def _load_profiles(self) -> None:
        self.profiles = load_profiles(self.profiles_path, language=self.language)
        if not self.profiles:
            raise ValueError("No usable TAcroMan profiles were found.")
        profile_ids = {str(profile["id"]) for profile in self.profiles}
        if self.selected_profile_id not in profile_ids:
            self.selected_profile_id = str(self.profiles[0]["id"])

    def _publish_state(self) -> None:
        write_vscode_integration_state(
            self.database_path,
            self.output_path,
            output_mode=self.output_mode,
            profiles_path=self.profiles_path,
            selected_profile_id=self.selected_profile_id,
            language=self.language,
            render_profile=self.active_profile,
            state_path=self.state_path,
        )
        self._known_state_signature = _file_signature(self.state_path)

    def _entries(self) -> list[CommandEntry]:
        return load_database(self.database_path, language=self.language)

    def _write_output(self, entries: list[CommandEntry]) -> None:
        atomic_write_text(self.output_path, render(entries, self.active_profile))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            entries = self._entries()
            revision = _database_revision(self.database_path)
            self._known_database_revision = revision
            return {
                "hostKind": "desktop",
                "databasePath": str(self.database_path),
                "outputPath": str(self.output_path),
                "revision": revision,
                "entries": [
                    {
                        "uid": entry.uid,
                        "commandId": entry.command_id,
                        "values": dict(entry.values),
                    }
                    for entry in entries
                ],
                "profile": _editor_profile(self.active_profile),
                "profiles": [
                    {"id": str(profile["id"]), "name": str(profile.get("name") or profile["id"])}
                    for profile in self.profiles
                ],
            }

    def _send_snapshot(self, reason: str) -> None:
        self.emit({"type": "snapshot", "reason": reason, "snapshot": self.snapshot()})

    def _send_error(self, error: object) -> None:
        self.emit({"type": "error", "message": str(error)})

    def _ensure_revision(self, expected: object) -> None:
        if not isinstance(expected, str) or _database_revision(self.database_path) != expected:
            raise DatabaseConflictError(
                "The database changed outside this editor. Reload it before saving again."
            )

    def _save_entry(self, message: dict[str, object]) -> None:
        raw_entry = message.get("entry")
        if not isinstance(raw_entry, dict):
            raise ValueError("The entry request is invalid.")
        command_id = str(raw_entry.get("commandId", "")).strip()
        raw_values = raw_entry.get("values")
        if not command_id or not isinstance(raw_values, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in raw_values.items()
        ):
            raise ValueError("The entry request is invalid.")

        self._ensure_revision(message.get("revision"))
        entries = self._entries()
        raw_uid = raw_entry.get("uid")
        candidate = CommandEntry(
            command_id=command_id,
            values=dict(raw_values),
            uid=str(raw_uid) if isinstance(raw_uid, str) and raw_uid else CommandEntry(command_id).uid,
        )
        commands = command_map(self.active_profile)
        command = commands.get(command_id)
        if command is None:
            raise ValueError(f"Unknown command type: {command_id}")
        errors, _warnings = validate_entry(candidate, command, language=self.language)
        duplicates, _cross_command = comparison_matches(
            candidate,
            command,
            entries,
            commands,
            ignore_uid=candidate.uid,
        )
        if duplicates:
            errors.append("An entry with the same key already exists for this command type.")
        if errors:
            raise ValueError("\n".join(dict.fromkeys(errors)))

        index = next((index for index, entry in enumerate(entries) if entry.uid == candidate.uid), None)
        if index is None:
            entries.append(candidate)
        else:
            entries[index] = candidate
        save_database(self.database_path, entries)
        self._known_database_revision = _database_revision(self.database_path)
        self._write_output(entries)
        self._publish_state()

    def _delete_entry(self, message: dict[str, object]) -> None:
        uid = message.get("uid")
        if not isinstance(uid, str) or not uid:
            raise ValueError("The delete request is invalid.")
        self._ensure_revision(message.get("revision"))
        entries = self._entries()
        remaining = [entry for entry in entries if entry.uid != uid]
        if len(entries) == len(remaining):
            raise ValueError("The selected entry no longer exists.")
        save_database(self.database_path, remaining)
        self._known_database_revision = _database_revision(self.database_path)
        self._write_output(remaining)
        self._publish_state()

    def _select_database(self) -> None:
        if self.choose_database is None:
            return
        selected = self.choose_database(self.database_path)
        if selected is None:
            return
        self.database_path = selected.expanduser().resolve()
        if not self.database_path.exists():
            save_database(self.database_path, [])
        if self.output_mode == "database":
            self.output_path = self.database_path.with_suffix(".tex")
        self.profiles_path = self.database_path.parent / PROFILE_FILENAME
        self._load_profiles()
        self._known_database_revision = _database_revision(self.database_path)
        self._publish_state()

    def _select_output(self) -> None:
        if self.choose_output is None:
            return
        selected = self.choose_output(self.output_path)
        if selected is None:
            return
        self.output_path = selected.expanduser().resolve()
        self.output_mode = "custom"
        self._write_output(self._entries())
        self._publish_state()

    def _select_profile(self, message: dict[str, object]) -> None:
        profile_id = message.get("profileId")
        if not isinstance(profile_id, str) or profile_id not in {
            str(profile["id"]) for profile in self.profiles
        }:
            raise ValueError("The selected profile is not available.")
        self.selected_profile_id = profile_id
        self._write_output(self._entries())
        self._publish_state()

    def handle_message(self, raw: str | dict[str, object]) -> None:
        with self._lock:
            try:
                message = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(message, dict) or not isinstance(message.get("type"), str):
                    raise ValueError("The TAcroMan desktop host received an invalid request.")
                message_type = str(message["type"])
                if message_type == "ready":
                    self._send_snapshot("initial")
                    return
                if message_type == "saveEntry":
                    self._save_entry(message)
                    self._send_snapshot("mutation")
                    return
                if message_type == "deleteEntry":
                    self._delete_entry(message)
                    self._send_snapshot("mutation")
                    return
                if message_type == "selectDatabase":
                    self._select_database()
                    self._send_snapshot("selection")
                    return
                if message_type == "selectOutput":
                    self._select_output()
                    self._send_snapshot("selection")
                    return
                if message_type == "selectProfile":
                    self._select_profile(message)
                    self._send_snapshot("selection")
                    return
                if message_type == "openDesktop":
                    return
                raise ValueError("The TAcroMan desktop host received an unknown request.")
            except DatabaseConflictError as error:
                self._send_error(error)
                self._send_snapshot("external")
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_error(error)

    def poll_once(self) -> bool:
        """Publish an external snapshot when shared state or database content changed."""
        with self._lock:
            changed = False
            state_signature = _file_signature(self.state_path)
            if state_signature != self._known_state_signature:
                state = read_shared_state(self.state_path)
                database = _resolved_path(state.get("databasePath"))
                output = _resolved_path(state.get("outputPath"))
                profiles = _resolved_path(state.get("profilesPath"))
                if database and database != self.database_path:
                    self.database_path = database
                    if not self.database_path.exists():
                        save_database(self.database_path, [])
                    changed = True
                if output and output != self.output_path:
                    self.output_path = output
                    changed = True
                output_mode = state.get("outputMode")
                if output_mode in {"project", "database", "custom"} and output_mode != self.output_mode:
                    self.output_mode = str(output_mode)
                    changed = True
                if profiles and profiles != self.profiles_path:
                    self.profiles_path = profiles
                    changed = True
                language = normalize_language(str(state.get("language") or self.language))
                if language != self.language:
                    self.language = language
                    changed = True
                profile_id = state.get("selectedProfileId")
                if isinstance(profile_id, str) and profile_id != self.selected_profile_id:
                    self.selected_profile_id = profile_id
                    changed = True
                self._load_profiles()
                self._known_state_signature = state_signature

            revision = _database_revision(self.database_path)
            if revision != self._known_database_revision:
                self._known_database_revision = revision
                changed = True
            if changed:
                self._send_snapshot("external")
            return changed


class DesktopWebApi:
    """pywebview adapter around the GUI-independent controller."""

    def __init__(self, controller_factory: Callable[..., WebAppController], **controller_args: object) -> None:
        self.window: Any | None = None
        self._stopped = threading.Event()
        self.controller = controller_factory(
            emit=self._emit,
            choose_database=self._choose_database,
            choose_output=self._choose_output,
            **controller_args,
        )

    def post_message(self, raw: str) -> None:
        self.controller.handle_message(raw)

    def _emit(self, message: dict[str, object]) -> None:
        if self.window is None:
            return
        payload = json.dumps(message, ensure_ascii=False).replace("</", "<\\/")
        self.window.run_js(f"window.postMessage({payload}, '*');")

    def _choose_database(self, current: Path) -> Path | None:
        if self.window is None:
            return None
        import webview

        selected = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=str(current.parent),
            allow_multiple=False,
            file_types=("TAcroMan database (*.json)", "All files (*.*)"),
        )
        return Path(selected[0]) if selected else None

    def _choose_output(self, current: Path) -> Path | None:
        if self.window is None:
            return None
        import webview

        selected = self.window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=str(current.parent),
            save_filename=current.name,
            file_types=("TeX file (*.tex)", "All files (*.*)"),
        )
        return Path(selected[0]) if selected else None

    def watch(self) -> None:
        while not self._stopped.wait(0.75):
            try:
                self.controller.poll_once()
            except (OSError, UnicodeError, ValueError, TypeError) as error:
                self._emit({"type": "error", "message": str(error)})

    def stop(self) -> None:
        self._stopped.set()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage profile-defined LaTeX command entries.")
    parser.add_argument("--database", type=Path, help="Path to the JSON command database.")
    parser.add_argument("--output", type=Path, help="Path of the generated output file.")
    parser.add_argument("--profiles", type=Path, help="Optional JSON file with command-definition profiles.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        import webview
    except ImportError as error:
        raise SystemExit(
            "TAcroMan's web desktop requires pywebview. Reinstall TAcroMan with its current dependencies."
        ) from error

    api = DesktopWebApi(
        WebAppController,
        database_path=args.database,
        output_path=args.output,
        profiles_path=args.profiles,
    )
    window = webview.create_window(
        APP_NAME,
        html=build_desktop_html(),
        js_api=api,
        width=1220,
        height=760,
        min_size=(760, 520),
        background_color="#111827",
    )
    api.window = window
    window.events.closed += api.stop
    webview.start(api.watch)
