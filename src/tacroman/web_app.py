"""Native desktop host for the shared TAcroMan web frontend."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from importlib.resources import files
import json
from pathlib import Path
import threading
from typing import Any, Callable
from uuid import uuid4

from .bib_migration import build_key_migration, migrate_tex_files
from .i18n import DEFAULT_LANGUAGE, normalize_language
from .importing import parse_acronym_package, read_tex_file
from .model import CommandEntry, acronym_to_entry, command_map, validate_entry
from .profiles import load_profiles, normalise_profile
from .reference_audit import audit_project, discover_reference_files
from .rendering import render
from .storage import load_database
from .vscode_integration import (
    clear_legacy_database_path,
    ensure_installation_id,
    read_shared_state,
    shared_state_path,
    write_vscode_integration_state,
)
from .workspace import (
    MANIFEST_FILENAME,
    WorkspaceConflictError,
    WorkspaceError,
    WorkspaceSnapshot,
    create_workspace,
    join_workspace,
    load_workspace,
    preview_local_entries,
    rename_participant,
    save_local_entries,
    save_workspace_profile,
    write_output_if_changed,
)


APP_NAME = "TAcroMan"
PROFILE_FILENAME = "tacroman-render-profiles.json"
MessageEmitter = Callable[[dict[str, object]], None]
PathChooser = Callable[[Path], Path | None]
ToolPathChooser = Callable[[str, Path], list[Path]]
CloseCallback = Callable[[], None]


class DatabaseConflictError(ValueError):
    """Raised when another frontend changed the database before a mutation."""


def _default_workspace_path() -> Path:
    return Path.home() / APP_NAME / "workspace"


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
        workspace_path: Path | None = None,
        output_path: Path | None = None,
        profiles_path: Path | None = None,
        *,
        database_path: Path | None = None,
        state_path: Path | None = None,
        emit: MessageEmitter | None = None,
        choose_database: PathChooser | None = None,
        choose_output: PathChooser | None = None,
        choose_new_database: PathChooser | None = None,
        choose_import_tex: PathChooser | None = None,
        choose_import_database: PathChooser | None = None,
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
        self.choose_import_database = choose_import_database
        self.choose_profiles = choose_profiles
        self.choose_tool_paths = choose_tool_paths
        self.close_app = close_app
        self._lock = threading.RLock()
        self._pending_database_import: tuple[str, Path, list[CommandEntry], str] | None = None

        state = read_shared_state(self.state_path)
        self.installation_id = ensure_installation_id(self.state_path)
        stored_workspace = _resolved_path(state.get("workspacePath"))
        self.legacy_database_path = (
            database_path
            or _resolved_path(state.get("legacyDatabasePath"))
            or _resolved_path(state.get("databasePath"))
        )
        self.workspace_path = (workspace_path or stored_workspace or _default_workspace_path()).expanduser().resolve()
        default_profiles_path = profiles_path or self.workspace_path / PROFILE_FILENAME
        profile_library = load_profiles(default_profiles_path, language=normalize_language(str(state.get("language") or DEFAULT_LANGUAGE)))
        if (self.workspace_path / MANIFEST_FILENAME).is_file():
            self._workspace = join_workspace(self.workspace_path, self.installation_id)
        else:
            self._workspace = create_workspace(self.workspace_path, self.installation_id, profile_library[0])

        stored_output = _resolved_path(state.get("outputPath"))
        self.output_path = (output_path or stored_output or self.workspace_path / "entries.tex").expanduser().resolve()
        stored_mode = str(state.get("outputMode", ""))
        self.output_mode = (
            "custom"
            if output_path is not None
            else (stored_mode if stored_mode in {"project", "database", "custom"} else "database")
        )
        if self.output_mode == "database" and output_path is None:
            self.output_path = self.workspace_path / "entries.tex"
        self.language = normalize_language(str(state.get("language") or DEFAULT_LANGUAGE))
        self.profiles_path = default_profiles_path.expanduser().resolve()
        self.profiles = load_profiles(self.profiles_path, language=self.language)
        manifest_profile_id = str(self._workspace.profile.get("id") or "workspace-profile")
        self.profiles = [
            self._workspace.profile,
            *(item for item in self.profiles if str(item.get("id")) != manifest_profile_id),
        ]
        self.selected_profile_id = manifest_profile_id
        self._known_workspace_revision = self._workspace.revision
        self._write_output(self._workspace)
        self._publish_state()

    @property
    def active_profile(self) -> dict[str, object]:
        return self._workspace.profile

    def _load_profiles(self) -> None:
        library = load_profiles(self.profiles_path, language=self.language)
        active_id = str(self._workspace.profile.get("id") or "workspace-profile")
        self.profiles = [self._workspace.profile, *(item for item in library if str(item.get("id")) != active_id)]
        self.selected_profile_id = active_id

    def _publish_state(self) -> None:
        write_vscode_integration_state(
            self.workspace_path,
            self.output_path,
            fragment_path=self._workspace.local_fragment_path,
            installation_id=self.installation_id,
            legacy_database_path=self.legacy_database_path,
            output_mode=self.output_mode,
            language=self.language,
            state_path=self.state_path,
        )
        self._known_state_signature = _file_signature(self.state_path)

    def _entries(self) -> list[CommandEntry]:
        return self._workspace.entries

    def _write_output(self, workspace: WorkspaceSnapshot | None = None) -> bool:
        current = workspace or self._workspace
        if current.export_blocked:
            return False
        return write_output_if_changed(self.output_path, render(current.entries, current.profile))

    def _refresh_workspace(self) -> WorkspaceSnapshot:
        self._workspace = load_workspace(self.workspace_path, self.installation_id)
        self._known_workspace_revision = self._workspace.revision
        self._load_profiles()
        return self._workspace

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            current = self._refresh_workspace()
            local_uids = {entry.uid for entry in current.local_entries}
            return {
                "hostKind": "desktop",
                "workspacePath": str(self.workspace_path),
                "fragmentPath": str(current.local_fragment_path),
                "outputPath": str(self.output_path),
                "language": self.language,
                "revision": current.revision,
                "exportBlocked": current.export_blocked,
                "owner": current.local_owner.to_dict(),
                "fragmentCount": current.fragment_count,
                "legacyDatabasePath": str(self.legacy_database_path) if self.legacy_database_path else None,
                "entries": [
                    {
                        "uid": item.entry.uid,
                        "localUid": item.local_uid,
                        "commandId": item.entry.command_id,
                        "values": dict(item.entry.values),
                        "editable": item.local_uid is not None,
                        "sources": [
                            {
                                "owner": source.owner.display_name,
                                "installationId": source.owner.installation_id,
                                "fragment": source.fragment_path.name,
                                "uid": source.entry.uid,
                            }
                            for source in item.sources
                        ],
                    }
                    for item in current.merged_entries
                ],
                "conflicts": [
                    {
                        "id": conflict.conflict_id,
                        "label": conflict.label,
                        "localUids": list(conflict.local_uids),
                        "variants": [
                            {
                                "uid": source.entry.uid,
                                "commandId": source.entry.command_id,
                                "values": dict(source.entry.values),
                                "owner": source.owner.display_name,
                                "installationId": source.owner.installation_id,
                                "fragment": source.fragment_path.name,
                                "editable": source.owner.installation_id == self.installation_id,
                            }
                            for source in conflict.variants
                        ],
                    }
                    for conflict in current.conflicts
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
        current = load_workspace(self.workspace_path, self.installation_id)
        if not isinstance(expected, str) or current.revision != expected:
            raise DatabaseConflictError(
                "The workspace changed outside this editor. Reload it before saving again."
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
        current = self._refresh_workspace()
        entries = list(current.local_entries)
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
        if errors:
            raise ValueError("\n".join(dict.fromkeys(errors)))

        index = next((index for index, entry in enumerate(entries) if entry.uid == candidate.uid), None)
        if index is None:
            entries.append(candidate)
        else:
            entries[index] = candidate
        _merged, proposed_conflicts = preview_local_entries(current, entries)
        existing_conflicts = {conflict.conflict_id for conflict in current.conflicts}
        if any(conflict.conflict_id not in existing_conflicts for conflict in proposed_conflicts):
            raise ValueError("This change would create a new workspace conflict.")
        self._workspace = save_local_entries(self.workspace_path, self.installation_id, current.revision, entries)
        self._known_workspace_revision = self._workspace.revision
        self._write_output(self._workspace)
        self._publish_state()

    def _delete_entry(self, message: dict[str, object]) -> None:
        uid = message.get("uid")
        if not isinstance(uid, str) or not uid:
            raise ValueError("The delete request is invalid.")
        self._ensure_revision(message.get("revision"))
        current = self._refresh_workspace()
        entries = list(current.local_entries)
        remaining = [entry for entry in entries if entry.uid != uid]
        if len(entries) == len(remaining):
            raise ValueError("The selected entry no longer exists.")
        self._workspace = save_local_entries(self.workspace_path, self.installation_id, current.revision, remaining)
        self._known_workspace_revision = self._workspace.revision
        self._write_output(self._workspace)
        self._publish_state()

    def _select_database(self) -> None:
        if self.choose_database is None:
            return
        selected = self.choose_database(self.workspace_path)
        if selected is None:
            return
        self.workspace_path = selected.expanduser().resolve()
        self._workspace = join_workspace(self.workspace_path, self.installation_id)
        if self.output_mode == "database":
            self.output_path = self.workspace_path / "entries.tex"
        self.profiles_path = self.workspace_path / PROFILE_FILENAME
        self._load_profiles()
        self._known_workspace_revision = self._workspace.revision
        self._write_output(self._workspace)
        self._publish_state()

    def _select_output(self) -> None:
        if self.choose_output is None:
            return
        selected = self.choose_output(self.output_path)
        if selected is None:
            return
        self.output_path = selected.expanduser().resolve()
        self.output_mode = "custom"
        self._write_output(self._workspace)
        self._publish_state()

    def _new_database(self) -> None:
        if self.choose_new_database is None:
            return
        selected = self.choose_new_database(self.workspace_path)
        if selected is None:
            return
        selected = selected.expanduser().resolve()
        profile = self.active_profile
        self.workspace_path = selected
        self._workspace = create_workspace(self.workspace_path, self.installation_id, profile)
        if self.output_mode == "database":
            self.output_path = self.workspace_path / "entries.tex"
        self.profiles_path = self.workspace_path / PROFILE_FILENAME
        self._load_profiles()
        self._known_workspace_revision = self._workspace.revision
        self._write_output(self._workspace)
        self._publish_state()

    def _import_tex(self, message: dict[str, object]) -> None:
        if self.choose_import_tex is None:
            return
        self._ensure_revision(message.get("revision"))
        if "acronym" not in command_map(self.active_profile):
            raise ValueError("The active profile does not support acronym-package imports.")
        selected = self.choose_import_tex(self.workspace_path)
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
        current = self._refresh_workspace()
        entries = list(current.local_entries)
        if mode == "replace":
            entries = unique_imports
        else:
            existing = {
                entry.value("short").casefold()
                for entry in entries
                if entry.command_id == "acronym"
            }
            entries.extend(entry for entry in unique_imports if entry.value("short").casefold() not in existing)
        self._workspace = save_local_entries(self.workspace_path, self.installation_id, current.revision, entries)
        self._known_workspace_revision = self._workspace.revision
        self._write_output(self._workspace)
        self._publish_state()

    def _import_database(self, message: dict[str, object]) -> None:
        if self.choose_import_database is None:
            raise ValueError("Native database selection is unavailable in this host.")
        self._ensure_revision(message.get("revision"))
        selected = self.choose_import_database(self.legacy_database_path or self.workspace_path)
        if selected is None:
            return
        selected = selected.expanduser().resolve()
        imported = load_database(selected)
        by_uid = {entry.uid: entry for entry in self._workspace.local_entries}
        for entry in imported:
            by_uid[entry.uid] = entry
        proposed = list(by_uid.values())
        merged, conflicts = preview_local_entries(self._workspace, proposed)
        current_duplicate_count = sum(max(0, len(item.sources) - 1) for item in self._workspace.merged_entries)
        proposed_duplicate_count = sum(max(0, len(item.sources) - 1) for item in merged)
        token = str(uuid4())
        self._pending_database_import = (token, selected, proposed, self._workspace.revision)
        self.emit({
            "type": "importPreview",
            "token": token,
            "path": str(selected),
            "importedCount": len(imported),
            "identicalDuplicates": max(0, proposed_duplicate_count - current_duplicate_count),
            "conflicts": [conflict.label for conflict in conflicts],
            "revision": self._workspace.revision,
        })

    def _commit_database_import(self, message: dict[str, object]) -> None:
        pending = self._pending_database_import
        token = message.get("token")
        if pending is None or not isinstance(token, str) or token != pending[0]:
            raise ValueError("The database import preview is no longer available.")
        _token, _selected, entries, revision = pending
        self._ensure_revision(message.get("revision"))
        if message.get("revision") != revision:
            raise DatabaseConflictError("The workspace changed after the import preview. Preview it again.")
        self._workspace = save_local_entries(
            self.workspace_path,
            self.installation_id,
            revision,
            entries,
        )
        self._pending_database_import = None
        self.legacy_database_path = None
        clear_legacy_database_path(self.state_path)
        self._known_workspace_revision = self._workspace.revision
        self._write_output(self._workspace)
        self._publish_state()

    def _select_profiles(self, message: dict[str, object]) -> None:
        if self.choose_profiles is None:
            return
        self._ensure_revision(message.get("revision"))
        selected = self.choose_profiles(self.profiles_path)
        if selected is None:
            return
        selected_profiles = load_profiles(selected.expanduser().resolve(), language=self.language)
        chosen = next(
            (item for item in selected_profiles if str(item.get("id")) == self.selected_profile_id),
            selected_profiles[0],
        )
        self._workspace = save_workspace_profile(
            self.workspace_path, self.installation_id, self._workspace.revision, chosen
        )
        self._known_workspace_revision = self._workspace.revision
        self._load_profiles()
        self._write_output(self._workspace)
        self._publish_state()

    def _set_language(self, message: dict[str, object]) -> None:
        language = normalize_language(str(message.get("language") or ""))
        if language not in {"de", "en"}:
            raise ValueError("The selected language is not supported.")
        self.language = language
        self._load_profiles()
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
        self._ensure_revision(message.get("revision"))
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
        self._workspace = save_workspace_profile(
            self.workspace_path, self.installation_id, self._workspace.revision, profile
        )
        self._known_workspace_revision = self._workspace.revision
        self._load_profiles()
        self._write_output(self._workspace)
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
        paths = self.choose_tool_paths(target, self.workspace_path)
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
        self._ensure_revision(message.get("revision"))
        profile_id = message.get("profileId")
        if not isinstance(profile_id, str) or profile_id not in {
            str(profile["id"]) for profile in self.profiles
        }:
            raise ValueError("The selected profile is not available.")
        selected = next(profile for profile in self.profiles if str(profile["id"]) == profile_id)
        self._workspace = save_workspace_profile(
            self.workspace_path, self.installation_id, self._workspace.revision, selected
        )
        self._known_workspace_revision = self._workspace.revision
        self._load_profiles()
        self._write_output(self._workspace)
        self._publish_state()

    def _rename_participant(self, message: dict[str, object]) -> None:
        name = str(message.get("displayName") or "").strip()
        if not name:
            raise ValueError("Enter a participant name.")
        self._ensure_revision(message.get("revision"))
        self._workspace = rename_participant(
            self.workspace_path,
            self.installation_id,
            self._workspace.revision,
            name,
        )
        self._known_workspace_revision = self._workspace.revision
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
                if message_type == "importDatabase":
                    self._import_database(message)
                    return
                if message_type == "commitDatabaseImport":
                    self._commit_database_import(message)
                    self._send_snapshot("mutation")
                    return
                if message_type == "dismissLegacySetup":
                    self.legacy_database_path = None
                    clear_legacy_database_path(self.state_path)
                    self._publish_state()
                    return
                if message_type == "writeOutput":
                    if not self._write_output(self._workspace):
                        if self._workspace.export_blocked:
                            raise ValueError("Resolve the workspace conflicts before generating output.")
                    self._publish_state()
                    self._send_snapshot("mutation")
                    return
                if message_type == "selectProfiles":
                    self._select_profiles(message)
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
                if message_type == "renameParticipant":
                    self._rename_participant(message)
                    self._send_snapshot("selection")
                    return
                if message_type == "openDesktop":
                    return
                raise ValueError("The TAcroMan desktop host received an unknown request.")
            except (DatabaseConflictError, WorkspaceConflictError) as error:
                self._send_error(error)
                self._send_snapshot("external")
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_error(error)

    def poll_once(self) -> bool:
        """Publish an external snapshot when shared state or workspace content changed."""
        with self._lock:
            changed = False
            state_signature = _file_signature(self.state_path)
            if state_signature != self._known_state_signature:
                state = read_shared_state(self.state_path)
                workspace = _resolved_path(state.get("workspacePath"))
                output = _resolved_path(state.get("outputPath"))
                if workspace and workspace != self.workspace_path:
                    self.workspace_path = workspace
                    self._workspace = join_workspace(self.workspace_path, self.installation_id)
                    changed = True
                if output and output != self.output_path:
                    self.output_path = output
                    changed = True
                output_mode = state.get("outputMode")
                if output_mode in {"project", "database", "custom"} and output_mode != self.output_mode:
                    self.output_mode = str(output_mode)
                    changed = True
                language = normalize_language(str(state.get("language") or self.language))
                if language != self.language:
                    self.language = language
                    changed = True
                self._load_profiles()
                self._known_state_signature = state_signature

            current = load_workspace(self.workspace_path, self.installation_id)
            if current.revision != self._known_workspace_revision:
                self._workspace = current
                self._known_workspace_revision = current.revision
                self._load_profiles()
                self._write_output(current)
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
        self._last_watch_error = ""
        self._controller = controller_factory(
            emit=self._emit,
            choose_database=self._choose_database,
            choose_output=self._choose_output,
            choose_new_database=self._choose_new_database,
            choose_import_tex=self._choose_import_tex,
            choose_import_database=self._choose_import_database,
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
            webview.FileDialog.FOLDER,
            directory=str(current),
            allow_multiple=False,
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
            webview.FileDialog.FOLDER,
            directory=str(current.parent if current.exists() else current.parent),
            allow_multiple=False,
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

    def _choose_import_database(self, current: Path) -> Path | None:
        if self._window is None:
            return None
        import webview

        base = current.parent if current.suffix else current
        selected = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=str(base),
            allow_multiple=False,
            file_types=("Legacy TAcroMan database (*.json)", "All files (*.*)"),
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
            last_error: Exception | None = None
            for retry_delay in (0.0, 0.25, 0.5):
                if retry_delay and self._stopped.wait(retry_delay):
                    return
                try:
                    changed = self._controller.poll_once()
                    if self._last_watch_error and not changed:
                        self._controller._send_snapshot("external")
                    self._last_watch_error = ""
                    last_error = None
                    break
                except (OSError, UnicodeError, ValueError, TypeError) as error:
                    last_error = error
            if last_error is not None:
                message = str(last_error)
                if message != self._last_watch_error:
                    self._emit({"type": "error", "message": message})
                self._last_watch_error = message

    def _stop(self) -> None:
        self._stopped.set()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage profile-defined LaTeX command entries.")
    parser.add_argument("--workspace", type=Path, help="Path to the TAcroMan workspace folder.")
    parser.add_argument("--database", type=Path, help="Legacy JSON database offered for explicit import.")
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
        workspace_path=args.workspace,
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
