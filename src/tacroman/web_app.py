"""Native desktop host for the shared TAcroMan web frontend."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
import threading
from typing import Any, Callable

from .bib_migration import build_key_migration, migrate_tex_files
from .i18n import DEFAULT_LANGUAGE, normalize_language
from .importing import parse_acronym_package, read_tex_file
from .model import CommandEntry, acronym_to_entry, command_map, comparison_matches, validate_entry
from .profiles import load_profiles, normalise_profile, save_profiles
from .reference_audit import audit_project, discover_reference_files
from .rendering import render
from .storage import atomic_write_text, load_database, save_database
from .vscode_integration import read_shared_state, shared_state_path, write_vscode_integration_state


APP_NAME = "TAcroMan"
PROFILE_FILENAME = "tacroman-render-profiles.json"
MessageEmitter = Callable[[dict[str, object]], None]
PathChooser = Callable[[Path], Path | None]
ToolPathChooser = Callable[[str, Path], list[Path]]
CloseCallback = Callable[[], None]


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
        choose_new_database: PathChooser | None = None,
        choose_import_tex: PathChooser | None = None,
        choose_profiles: PathChooser | None = None,
        choose_tool_paths: ToolPathChooser | None = None,
        close_app: CloseCallback | None = None,
    ) -> None:
        self.state_path = (state_path or shared_state_path()).expanduser().resolve()
        self.emit = emit or (lambda _message: None)
        self.choose_database = choose_database
        self.choose_output = choose_output
        self.choose_new_database = choose_new_database
        self.choose_import_tex = choose_import_tex
        self.choose_profiles = choose_profiles
        self.choose_tool_paths = choose_tool_paths
        self.close_app = close_app
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
                "profilesPath": str(self.profiles_path),
                "language": self.language,
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

    def _new_database(self) -> None:
        if self.choose_new_database is None:
            return
        selected = self.choose_new_database(self.database_path)
        if selected is None:
            return
        self.database_path = selected.expanduser().resolve()
        self.output_path = self.database_path.with_suffix(".tex")
        self.output_mode = "database"
        self.profiles_path = self.database_path.parent / PROFILE_FILENAME
        self.selected_profile_id = "acronym-package"
        self._load_profiles()
        save_database(self.database_path, [])
        self._known_database_revision = _database_revision(self.database_path)
        self._write_output([])
        self._publish_state()

    def _import_tex(self, message: dict[str, object]) -> None:
        if self.choose_import_tex is None:
            return
        self._ensure_revision(message.get("revision"))
        if "acronym" not in command_map(self.active_profile):
            raise ValueError("The active profile does not support acronym-package imports.")
        selected = self.choose_import_tex(self.database_path)
        if selected is None:
            return
        imported = [acronym_to_entry(item) for item in parse_acronym_package(read_tex_file(selected))]
        if not imported:
            raise ValueError("No \\acro definitions were found in the selected TeX file.")
        unique_imports: list[CommandEntry] = []
        seen: set[str] = set()
        for entry in imported:
            key = entry.value("short").casefold()
            if key not in seen:
                unique_imports.append(entry)
                seen.add(key)
        mode = message.get("mode")
        if mode not in {"merge", "replace"}:
            raise ValueError("The import mode must be merge or replace.")
        entries = self._entries()
        if mode == "replace":
            entries = unique_imports
        else:
            existing = {
                entry.value("short").casefold()
                for entry in entries
                if entry.command_id == "acronym"
            }
            entries.extend(entry for entry in unique_imports if entry.value("short").casefold() not in existing)
        save_database(self.database_path, entries)
        self._known_database_revision = _database_revision(self.database_path)
        self._write_output(entries)
        self._publish_state()

    def _select_profiles(self) -> None:
        if self.choose_profiles is None:
            return
        selected = self.choose_profiles(self.profiles_path)
        if selected is None:
            return
        previous = self.profiles_path
        self.profiles_path = selected.expanduser().resolve()
        try:
            self._load_profiles()
        except (OSError, ValueError):
            self.profiles_path = previous
            self._load_profiles()
            raise
        self._write_output(self._entries())
        self._publish_state()

    def _set_language(self, message: dict[str, object]) -> None:
        language = normalize_language(str(message.get("language") or ""))
        if language not in {"de", "en"}:
            raise ValueError("The selected language is not supported.")
        self.language = language
        self._load_profiles()
        self._write_output(self._entries())
        self._publish_state()

    def _open_profile_editor(self) -> None:
        self.emit(
            {
                "type": "profileEditor",
                "profilesPath": str(self.profiles_path),
                "selectedProfileId": self.selected_profile_id,
                "profiles": self.profiles,
            }
        )

    def _save_profile(self, message: dict[str, object]) -> None:
        raw_profile = message.get("profile")
        if not isinstance(raw_profile, dict):
            raise ValueError("The profile editor did not provide a valid profile.")
        profile = normalise_profile(raw_profile, language=self.language)
        original_id = message.get("originalId")
        original_id = original_id if isinstance(original_id, str) and original_id else None
        profile_id = str(profile["id"])
        if original_id != profile_id and any(str(item["id"]) == profile_id for item in self.profiles):
            raise ValueError(f"A profile with the ID '{profile_id}' already exists.")
        if original_id is None:
            self.profiles.append(profile)
        else:
            replaced = False
            updated: list[dict[str, object]] = []
            for item in self.profiles:
                if str(item["id"]) == original_id:
                    updated.append(profile)
                    replaced = True
                else:
                    updated.append(item)
            if not replaced:
                raise ValueError("The profile being edited no longer exists.")
            self.profiles = updated
        save_profiles(self.profiles_path, self.profiles, language=self.language)
        self.selected_profile_id = profile_id
        self._load_profiles()
        self._write_output(self._entries())
        self._publish_state()
        self._open_profile_editor()
        self._send_snapshot("selection")

    def _choose_tool_path(self, message: dict[str, object]) -> None:
        target = str(message.get("target") or "")
        allowed = {"oldBib", "newBib", "texFiles", "texFolder", "auditProject", "auditReference"}
        if target not in allowed:
            raise ValueError("The requested file selection is not supported.")
        if self.choose_tool_paths is None:
            raise ValueError("Native file selection is unavailable in this host.")
        paths = self.choose_tool_paths(target, self.database_path.parent)
        if target == "texFolder" and paths:
            paths = sorted(paths[0].rglob("*.tex"))
        clean = [path.expanduser().resolve() for path in paths]
        self.emit({"type": "toolPaths", "target": target, "paths": [str(path) for path in clean]})

    @staticmethod
    def _existing_path(raw: object, *, kind: str) -> Path:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"No {kind} was selected.")
        path = Path(raw).expanduser().resolve()
        return path

    def _analyse_citations(self, message: dict[str, object]) -> None:
        old_path = self._existing_path(message.get("oldBib"), kind="old bibliography")
        new_path = self._existing_path(message.get("newBib"), kind="new bibliography")
        if not old_path.is_file() or not new_path.is_file():
            raise ValueError("Please select an existing old and new bibliography file.")
        report = build_key_migration(
            old_path.read_text(encoding="utf-8-sig"),
            new_path.read_text(encoding="utf-8-sig"),
        )
        self.emit(
            {
                "type": "citationAnalysis",
                "matches": [asdict(item) for item in report.matches],
                "summary": {
                    "changed": report.changed_count,
                    "unchanged": report.unchanged_count,
                    "ambiguous": report.ambiguous_count,
                    "unmatched": report.unmatched_count,
                },
            }
        )

    def _apply_citation_migration(self, message: dict[str, object]) -> None:
        raw_mapping = message.get("mapping")
        raw_paths = message.get("paths")
        if not isinstance(raw_mapping, dict) or not isinstance(raw_paths, list):
            raise ValueError("The citation migration request is invalid.")
        mapping = {
            str(old).strip(): str(new).strip()
            for old, new in raw_mapping.items()
            if str(old).strip() and str(new).strip() and str(old).strip() != str(new).strip()
        }
        paths = [Path(path).expanduser().resolve() for path in raw_paths if isinstance(path, str)]
        if not mapping:
            raise ValueError("Select at least one valid citation-key mapping.")
        if not paths or any(not path.is_file() or path.suffix.casefold() != ".tex" for path in paths):
            raise ValueError("Select at least one existing TeX file.")
        result = migrate_tex_files(paths, mapping, backup=message.get("backup") is not False)
        self.emit(
            {
                "type": "citationMigrationResult",
                "filesConsidered": result.files_considered,
                "filesChanged": result.files_changed,
                "replacements": result.replacements,
                "changedFiles": [str(path) for path in result.changed_files],
            }
        )

    def _discover_references(self, message: dict[str, object]) -> None:
        project = self._existing_path(message.get("project"), kind="project directory")
        if not project.is_dir():
            raise ValueError("The selected project directory does not exist.")
        references = discover_reference_files(project)
        self.emit(
            {
                "type": "referenceFiles",
                "project": str(project),
                "paths": [str(path) for path in references],
            }
        )

    def _audit_references(self, message: dict[str, object]) -> None:
        project = self._existing_path(message.get("project"), kind="project directory")
        reference = self._existing_path(message.get("reference"), kind="reference file")
        report = audit_project(project, reference)

        def relative(path: Path) -> str:
            try:
                return str(path.relative_to(project))
            except ValueError:
                return str(path)

        self.emit(
            {
                "type": "referenceAudit",
                "bibliography": [asdict(item) for item in report.bibliography],
                "unused": [asdict(item) for item in report.unused],
                "occurrences": [
                    {
                        "path": str(item.path),
                        "relativePath": relative(item.path),
                        "line": item.line,
                        "key": item.key,
                        "title": item.title,
                        "author": item.author,
                        "excerpt": item.excerpt,
                        "defined": item.defined,
                    }
                    for item in report.occurrences
                ],
                "unknownKeys": list(report.unknown_keys),
                "sourceFiles": [str(path) for path in report.source_files],
                "usedKeys": list(report.used_keys),
            }
        )

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
                if message_type == "newDatabase":
                    self._new_database()
                    self._send_snapshot("selection")
                    return
                if message_type == "importTex":
                    self._import_tex(message)
                    self._send_snapshot("mutation")
                    return
                if message_type == "writeOutput":
                    self._write_output(self._entries())
                    self._publish_state()
                    self._send_snapshot("mutation")
                    return
                if message_type == "selectProfiles":
                    self._select_profiles()
                    self._send_snapshot("selection")
                    return
                if message_type == "setLanguage":
                    self._set_language(message)
                    self._send_snapshot("selection")
                    return
                if message_type == "openProfileEditor":
                    self._open_profile_editor()
                    return
                if message_type == "saveProfile":
                    self._save_profile(message)
                    return
                if message_type == "chooseToolPath":
                    self._choose_tool_path(message)
                    return
                if message_type == "analyseCitations":
                    self._analyse_citations(message)
                    return
                if message_type == "applyCitationMigration":
                    self._apply_citation_migration(message)
                    return
                if message_type == "discoverReferences":
                    self._discover_references(message)
                    return
                if message_type == "auditReferences":
                    self._audit_references(message)
                    return
                if message_type == "exitApp":
                    if self.close_app is not None:
                        self.close_app()
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
        # pywebview exports every public member of js_api. Keeping the native
        # Window object public makes its cyclic .NET accessibility graph part
        # of API discovery and causes recursion errors under debugpy.
        self._window: Any | None = None
        self._stopped = threading.Event()
        self._controller = controller_factory(
            emit=self._emit,
            choose_database=self._choose_database,
            choose_output=self._choose_output,
            choose_new_database=self._choose_new_database,
            choose_import_tex=self._choose_import_tex,
            choose_profiles=self._choose_profiles,
            choose_tool_paths=self._choose_tool_paths,
            close_app=self._close_app,
            **controller_args,
        )

    def post_message(self, raw: str) -> None:
        self._controller.handle_message(raw)

    def _attach_window(self, window: Any) -> None:
        self._window = window

    def _emit(self, message: dict[str, object]) -> None:
        if self._window is None:
            return
        payload = json.dumps(message, ensure_ascii=False).replace("</", "<\\/")
        self._window.run_js(f"window.postMessage({payload}, '*');")

    def _choose_database(self, current: Path) -> Path | None:
        if self._window is None:
            return None
        import webview

        selected = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=str(current.parent),
            allow_multiple=False,
            file_types=("TAcroMan database (*.json)", "All files (*.*)"),
        )
        return Path(selected[0]) if selected else None

    def _choose_output(self, current: Path) -> Path | None:
        if self._window is None:
            return None
        import webview

        selected = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=str(current.parent),
            save_filename=current.name,
            file_types=("TeX file (*.tex)", "All files (*.*)"),
        )
        return Path(selected[0]) if selected else None

    def _choose_new_database(self, current: Path) -> Path | None:
        if self._window is None:
            return None
        import webview

        selected = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=str(current.parent),
            save_filename="entries.json",
            file_types=("TAcroMan database (*.json)", "All files (*.*)"),
        )
        return Path(selected[0]) if selected else None

    def _choose_import_tex(self, current: Path) -> Path | None:
        if self._window is None:
            return None
        import webview

        selected = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=str(current.parent),
            allow_multiple=False,
            file_types=("TeX file (*.tex)", "All files (*.*)"),
        )
        return Path(selected[0]) if selected else None

    def _choose_profiles(self, current: Path) -> Path | None:
        if self._window is None:
            return None
        import webview

        selected = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=str(current.parent),
            allow_multiple=False,
            file_types=("TAcroMan profiles (*.json)", "All files (*.*)"),
        )
        return Path(selected[0]) if selected else None

    def _choose_tool_paths(self, target: str, current: Path) -> list[Path]:
        if self._window is None:
            return []
        import webview

        if target in {"texFolder", "auditProject"}:
            selected = self._window.create_file_dialog(
                webview.FileDialog.FOLDER,
                directory=str(current),
                allow_multiple=False,
            )
        elif target == "texFiles":
            selected = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                directory=str(current),
                allow_multiple=True,
                file_types=("TeX files (*.tex)", "All files (*.*)"),
            )
        else:
            selected = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                directory=str(current),
                allow_multiple=False,
                file_types=("BibTeX files (*.bib;*.bibtex)", "All files (*.*)"),
            )
        return [Path(path) for path in selected] if selected else []

    def _close_app(self) -> None:
        if self._window is not None:
            self._window.destroy()

    def _watch(self) -> None:
        while not self._stopped.wait(0.75):
            try:
                self._controller.poll_once()
            except (OSError, UnicodeError, ValueError, TypeError) as error:
                self._emit({"type": "error", "message": str(error)})

    def _stop(self) -> None:
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
    api._attach_window(window)
    window.events.closed += api._stop
    webview.start(api._watch)
