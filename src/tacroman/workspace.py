"""Multi-user TAcroMan workspaces composed from one fragment per installation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import string
import unicodedata
from uuid import UUID, uuid4

from .model import CommandEntry, command_fields, command_map, normalise_for_comparison
from .profiles import normalise_profile
from .storage import SCHEMA_VERSION, atomic_write_text, load_database


MANIFEST_FILENAME = ".tacroman-workspace.json"
FRAGMENT_GLOB = "*.tacroman.json"
WORKSPACE_FORMAT = "tacroman-workspace"
FRAGMENT_FORMAT = "tacroman-fragment"
FORMAT_VERSION = 1


class WorkspaceError(ValueError):
    """Raised when a workspace cannot be loaded without losing data."""


class WorkspaceConflictError(WorkspaceError):
    """Raised when a mutation is based on a stale workspace revision."""


@dataclass(frozen=True, slots=True)
class FragmentOwner:
    installation_id: str
    display_name: str
    created_at: str
    suffix: str

    def to_dict(self) -> dict[str, str]:
        return {
            "installation_id": self.installation_id,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "suffix": self.suffix,
        }


@dataclass(frozen=True, slots=True)
class EntrySource:
    entry: CommandEntry
    owner: FragmentOwner
    fragment_path: Path
    entry_index: int

    @property
    def marker(self) -> str:
        return f"{self.fragment_path.name}\0{self.entry_index:08d}\0{self.entry.uid}"


@dataclass(frozen=True, slots=True)
class MergedEntry:
    entry: CommandEntry
    sources: tuple[EntrySource, ...]
    local_uid: str | None


@dataclass(frozen=True, slots=True)
class WorkspaceConflict:
    conflict_id: str
    label: str
    variants: tuple[EntrySource, ...]
    local_uids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    workspace_path: Path
    workspace_id: str
    workspace_name: str
    created_at: str
    profile: dict[str, object]
    manifest_revision: str
    revision: str
    local_fragment_path: Path
    local_owner: FragmentOwner
    local_entries: tuple[CommandEntry, ...]
    merged_entries: tuple[MergedEntry, ...]
    conflicts: tuple[WorkspaceConflict, ...]
    fragment_count: int

    @property
    def entries(self) -> list[CommandEntry]:
        return [item.entry for item in self.merged_entries]

    @property
    def export_blocked(self) -> bool:
        return bool(self.conflicts)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _valid_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise WorkspaceError(f"{label} is missing.")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as error:
        raise WorkspaceError(f"{label} is not a valid UUID.") from error


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WorkspaceError(f"{label} must be a JSON object.")
    return value


def _utc_timestamp(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise WorkspaceError(f"{label} is not a UTC ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise WorkspaceError(f"{label} is not a UTC ISO timestamp.") from error
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise WorkspaceError(f"{label} is not a UTC ISO timestamp.")
    return value


def _read_json(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise WorkspaceError(f"Could not read {path.name}: {error}") from error
    try:
        raw = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise WorkspaceError(f"{path.name} is not valid UTF-8 JSON: {error}") from error
    return _object(raw, path.name), content


def _validate_marker(raw: dict[str, object], expected: str, path: Path) -> None:
    if raw.get("format") != expected or raw.get("format_version") != FORMAT_VERSION:
        raise WorkspaceError(f"{path.name} is not a supported {expected} file.")


def _manifest(path: Path) -> tuple[dict[str, object], bytes]:
    raw, content = _read_json(path)
    _validate_marker(raw, WORKSPACE_FORMAT, path)
    _valid_uuid(raw.get("workspace_id"), "workspace_id")
    if not isinstance(raw.get("name"), str) or not str(raw["name"]).strip():
        raise WorkspaceError(f"{path.name} does not contain a workspace name.")
    _utc_timestamp(raw.get("created_at"), "created_at")
    profile = raw.get("profile")
    if not isinstance(profile, dict) or not isinstance(profile.get("commands"), list):
        raise WorkspaceError(f"{path.name} does not contain a usable profile.")
    try:
        normalise_profile(profile)
    except (TypeError, ValueError) as error:
        raise WorkspaceError(f"{path.name} does not contain a valid render profile: {error}") from error
    return raw, content


def _owner(raw: object, path: Path) -> FragmentOwner:
    value = _object(raw, f"{path.name}.owner")
    installation_id = _valid_uuid(value.get("installation_id"), "owner.installation_id")
    display_name = str(value.get("display_name") or "").strip()
    created_at = _utc_timestamp(value.get("created_at"), "owner.created_at")
    suffix = str(value.get("suffix") or "").strip()
    if not display_name or not created_at or not re.fullmatch(r"[A-Za-z0-9]{8}", suffix):
        raise WorkspaceError(f"{path.name} contains invalid owner metadata.")
    return FragmentOwner(installation_id, display_name, created_at, suffix)


def _fragment(path: Path, workspace_id: str) -> tuple[FragmentOwner, list[CommandEntry], bytes]:
    raw, content = _read_json(path)
    _validate_marker(raw, FRAGMENT_FORMAT, path)
    if _valid_uuid(raw.get("workspace_id"), "workspace_id") != workspace_id:
        raise WorkspaceError(f"{path.name} belongs to another TAcroMan workspace.")
    owner = _owner(raw.get("owner"), path)
    if path.name != fragment_filename(owner):
        raise WorkspaceError(f"{path.name} does not match its owner metadata.")
    payload = _object(raw.get("payload"), f"{path.name}.payload")
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(payload.get("entries"), list):
        raise WorkspaceError(f"{path.name} does not contain a supported entry payload.")
    records = payload["entries"]
    seen_uids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise WorkspaceError(f"{path.name} contains an invalid entry.")
        uid = record.get("uid")
        command_id = record.get("command_id")
        values = record.get("values")
        if (
            not isinstance(uid, str) or not uid
            or not isinstance(command_id, str) or not command_id
            or not isinstance(values, dict)
            or not all(isinstance(key, str) and isinstance(value, str) for key, value in values.items())
        ):
            raise WorkspaceError(f"{path.name} contains an invalid schema-v2 entry.")
        if uid in seen_uids:
            raise WorkspaceError(f"{path.name} contains the duplicate UID {uid}.")
        seen_uids.add(uid)
    return owner, [CommandEntry.from_dict(record) for record in records], content


def _entry_values(entry: CommandEntry) -> tuple[str, tuple[tuple[str, str], ...]]:
    values = tuple(sorted((key, value.replace("\r\n", "\n").replace("\r", "\n")) for key, value in entry.values.items()))
    return entry.command_id, values


def _same_identity(
    left: CommandEntry,
    right: CommandEntry,
    commands: dict[str, dict[str, object]],
) -> bool:
    if left.uid == right.uid:
        return True
    if left.command_id != right.command_id:
        return False
    command = commands.get(left.command_id)
    if command is None:
        return False
    fields = command_fields(command)
    for left_field in fields:
        group = str(left_field.get("comparison_group") or "").strip()
        left_value = left.value(str(left_field["id"])).strip()
        if not group or not left_value:
            continue
        for right_field in fields:
            if str(right_field.get("comparison_group") or "").strip() != group:
                continue
            right_value = right.value(str(right_field["id"])).strip()
            if not right_value:
                continue
            case_sensitive = bool(left_field.get("case_sensitive")) and bool(right_field.get("case_sensitive"))
            if normalise_for_comparison(left_value, case_sensitive=case_sensitive) == normalise_for_comparison(
                right_value, case_sensitive=case_sensitive
            ):
                return True
    return False


def _primary_label(entry: CommandEntry, profile: dict[str, object]) -> str:
    command = command_map(profile).get(entry.command_id)
    if command:
        compared = [
            entry.value(str(item["id"])).strip()
            for item in command_fields(command)
            if str(item.get("comparison_group") or "").strip()
        ]
        first = next((value for value in compared if value), "")
        if first:
            return first
        for item in command_fields(command):
            value = entry.value(str(item["id"])).strip()
            if value:
                return value
    return entry.uid


def _merge_sources(
    sources: list[EntrySource],
    profile: dict[str, object],
    installation_id: str,
) -> tuple[tuple[MergedEntry, ...], tuple[WorkspaceConflict, ...]]:
    commands = command_map(profile)
    parents = list(range(len(sources)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        first, second = find(left), find(right)
        if first != second:
            parents[second] = first

    for left in range(len(sources)):
        for right in range(left + 1, len(sources)):
            if _same_identity(sources[left].entry, sources[right].entry, commands):
                union(left, right)

    clusters: dict[int, list[EntrySource]] = {}
    for index, source in enumerate(sources):
        clusters.setdefault(find(index), []).append(source)

    merged: list[MergedEntry] = []
    conflicts: list[WorkspaceConflict] = []
    ordered_clusters = sorted(
        clusters.values(),
        key=lambda cluster: min(source.marker.encode("utf-8") for source in cluster),
    )
    for cluster in ordered_clusters:
        ordered = sorted(cluster, key=lambda source: source.marker.encode("utf-8"))
        variants: dict[tuple[str, tuple[tuple[str, str], ...]], list[EntrySource]] = {}
        for source in ordered:
            variants.setdefault(_entry_values(source.entry), []).append(source)
        local_uids = tuple(
            source.entry.uid for source in ordered if source.owner.installation_id == installation_id
        )
        if len(variants) == 1:
            representative = ordered[0].entry
            merged.append(
                MergedEntry(
                    representative,
                    tuple(ordered),
                    local_uids[0] if local_uids else None,
                )
            )
            continue
        label = _primary_label(ordered[0].entry, profile)
        digest = sha256(
            "\0".join(source.marker for source in ordered).encode("utf-8")
        ).hexdigest()[:16]
        conflicts.append(WorkspaceConflict(digest, label, tuple(ordered), local_uids))

    return tuple(merged), tuple(conflicts)


def preview_local_entries(
    snapshot: WorkspaceSnapshot,
    local_entries: list[CommandEntry],
) -> tuple[tuple[MergedEntry, ...], tuple[WorkspaceConflict, ...]]:
    """Merge a proposed local fragment without writing any workspace file."""
    foreign: dict[str, EntrySource] = {}
    for item in snapshot.merged_entries:
        for source in item.sources:
            if source.owner.installation_id != snapshot.local_owner.installation_id:
                foreign[source.marker] = source
    for conflict in snapshot.conflicts:
        for source in conflict.variants:
            if source.owner.installation_id != snapshot.local_owner.installation_id:
                foreign[source.marker] = source
    local_sources = [
        EntrySource(entry, snapshot.local_owner, snapshot.local_fragment_path, index)
        for index, entry in enumerate(local_entries)
    ]
    return _merge_sources([*foreign.values(), *local_sources], snapshot.profile, snapshot.local_owner.installation_id)


def load_workspace(workspace_path: Path, installation_id: str) -> WorkspaceSnapshot:
    root = workspace_path.expanduser().resolve()
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise WorkspaceError(f"{MANIFEST_FILENAME} was not found in {root}.")
    manifest, manifest_content = _manifest(manifest_path)
    workspace_id = _valid_uuid(manifest.get("workspace_id"), "workspace_id")
    profile = dict(_object(manifest.get("profile"), "profile"))
    fragments = sorted(root.glob(FRAGMENT_GLOB), key=lambda item: item.name.encode("utf-8"))
    if not fragments:
        raise WorkspaceError("The workspace does not contain a participant fragment.")

    owners: set[str] = set()
    all_sources: list[EntrySource] = []
    local_fragment: Path | None = None
    local_owner: FragmentOwner | None = None
    local_entries: list[CommandEntry] = []
    revision_parts = [MANIFEST_FILENAME.encode("utf-8"), manifest_content]
    for fragment_path in fragments:
        owner, entries, content = _fragment(fragment_path, workspace_id)
        if owner.installation_id in owners:
            raise WorkspaceError(f"Installation {owner.display_name} owns more than one fragment.")
        owners.add(owner.installation_id)
        revision_parts.extend([fragment_path.name.encode("utf-8"), content])
        if owner.installation_id == installation_id:
            local_fragment, local_owner, local_entries = fragment_path, owner, entries
        all_sources.extend(
            EntrySource(entry, owner, fragment_path, index)
            for index, entry in enumerate(entries)
        )
    if local_fragment is None or local_owner is None:
        raise WorkspaceError("This installation does not own a fragment in the workspace.")

    merged, conflicts = _merge_sources(all_sources, profile, installation_id)
    return WorkspaceSnapshot(
        root,
        workspace_id,
        str(manifest.get("name") or root.name),
        str(manifest.get("created_at") or ""),
        profile,
        sha256(manifest_content).hexdigest(),
        sha256(b"\0".join(revision_parts)).hexdigest(),
        local_fragment,
        local_owner,
        tuple(local_entries),
        merged,
        conflicts,
        len(fragments),
    )


def _safe_display_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    return normalized[:48] or "user"


def default_display_name() -> str:
    try:
        return _safe_display_name(getpass.getuser())
    except (OSError, KeyError):
        return "user"


def _base62_digest(value: bytes, length: int = 8) -> str:
    alphabet = string.digits + string.ascii_uppercase + string.ascii_lowercase
    number = int.from_bytes(sha256(value).digest(), "big")
    result = ""
    for _ in range(length):
        number, remainder = divmod(number, len(alphabet))
        result += alphabet[remainder]
    return result


def new_owner(installation_id: str, display_name: str | None = None) -> FragmentOwner:
    created_at = utc_now()
    name = _safe_display_name(display_name or default_display_name())
    seed = f"{name}\0{created_at}\0{secrets.token_hex(16)}".encode("utf-8")
    return FragmentOwner(_valid_uuid(installation_id, "installation_id"), name, created_at, _base62_digest(seed))


def fragment_filename(owner: FragmentOwner) -> str:
    return f"{_safe_display_name(owner.display_name)}_{owner.suffix}.tacroman.json"


def _fragment_payload(workspace_id: str, owner: FragmentOwner, entries: list[CommandEntry]) -> dict[str, object]:
    return {
        "format": FRAGMENT_FORMAT,
        "format_version": FORMAT_VERSION,
        "workspace_id": workspace_id,
        "owner": owner.to_dict(),
        "payload": {
            "schema_version": SCHEMA_VERSION,
            "entries": [entry.to_dict() for entry in entries],
        },
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def create_workspace(
    workspace_path: Path,
    installation_id: str,
    profile: dict[str, object],
    *,
    name: str | None = None,
    display_name: str | None = None,
) -> WorkspaceSnapshot:
    root = workspace_path.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / MANIFEST_FILENAME
    if manifest_path.exists() or any(root.glob(FRAGMENT_GLOB)):
        raise WorkspaceError("The selected folder already contains a TAcroMan workspace or fragments.")
    workspace_id = str(uuid4())
    manifest = {
        "format": WORKSPACE_FORMAT,
        "format_version": FORMAT_VERSION,
        "workspace_id": workspace_id,
        "name": str(name or root.name or "TAcroMan"),
        "created_at": utc_now(),
        "profile": profile,
    }
    owner = new_owner(installation_id, display_name)
    fragment_path = root / fragment_filename(owner)
    _write_json(manifest_path, manifest)
    _write_json(fragment_path, _fragment_payload(workspace_id, owner, []))
    return load_workspace(root, installation_id)


def join_workspace(
    workspace_path: Path,
    installation_id: str,
    *,
    display_name: str | None = None,
) -> WorkspaceSnapshot:
    root = workspace_path.expanduser().resolve()
    manifest, _content = _manifest(root / MANIFEST_FILENAME)
    workspace_id = _valid_uuid(manifest.get("workspace_id"), "workspace_id")
    matching: list[Path] = []
    for path in sorted(root.glob(FRAGMENT_GLOB), key=lambda item: item.name.encode("utf-8")):
        owner, _entries, _raw = _fragment(path, workspace_id)
        if owner.installation_id == installation_id:
            matching.append(path)
    if len(matching) > 1:
        raise WorkspaceError("This installation owns more than one fragment.")
    if not matching:
        owner = new_owner(installation_id, display_name)
        target = root / fragment_filename(owner)
        while target.exists():
            owner = new_owner(installation_id, display_name)
            target = root / fragment_filename(owner)
        _write_json(target, _fragment_payload(workspace_id, owner, []))
    return load_workspace(root, installation_id)


def save_local_entries(
    workspace_path: Path,
    installation_id: str,
    expected_revision: str,
    entries: list[CommandEntry],
) -> WorkspaceSnapshot:
    current = load_workspace(workspace_path, installation_id)
    if current.revision != expected_revision:
        raise WorkspaceConflictError("The workspace changed outside this editor. Reload it before saving again.")
    _write_json(
        current.local_fragment_path,
        _fragment_payload(current.workspace_id, current.local_owner, entries),
    )
    return load_workspace(workspace_path, installation_id)


def save_workspace_profile(
    workspace_path: Path,
    installation_id: str,
    expected_revision: str,
    profile: dict[str, object],
) -> WorkspaceSnapshot:
    current = load_workspace(workspace_path, installation_id)
    if current.revision != expected_revision:
        raise WorkspaceConflictError("The workspace changed outside this editor. Reload it before saving again.")
    manifest_path = current.workspace_path / MANIFEST_FILENAME
    manifest, _content = _manifest(manifest_path)
    manifest["profile"] = profile
    _write_json(manifest_path, manifest)
    return load_workspace(workspace_path, installation_id)


def rename_participant(
    workspace_path: Path,
    installation_id: str,
    expected_revision: str,
    display_name: str,
) -> WorkspaceSnapshot:
    current = load_workspace(workspace_path, installation_id)
    if current.revision != expected_revision:
        raise WorkspaceConflictError("The workspace changed outside this editor. Reload it before renaming.")
    owner = FragmentOwner(
        current.local_owner.installation_id,
        _safe_display_name(display_name),
        current.local_owner.created_at,
        current.local_owner.suffix,
    )
    target = current.workspace_path / fragment_filename(owner)
    same_target = os.path.normcase(str(target)) == os.path.normcase(str(current.local_fragment_path))
    if not same_target and target.exists():
        raise WorkspaceError(f"{target.name} already exists.")
    _write_json(current.local_fragment_path, _fragment_payload(current.workspace_id, owner, list(current.local_entries)))
    if target.name != current.local_fragment_path.name:
        os.replace(current.local_fragment_path, target)
    return load_workspace(workspace_path, installation_id)


def import_legacy_database(
    workspace_path: Path,
    installation_id: str,
    expected_revision: str,
    database_path: Path,
) -> WorkspaceSnapshot:
    current = load_workspace(workspace_path, installation_id)
    imported = load_database(database_path)
    by_uid = {entry.uid: entry for entry in current.local_entries}
    for entry in imported:
        by_uid[entry.uid] = entry
    return save_local_entries(workspace_path, installation_id, expected_revision, list(by_uid.values()))


def write_output_if_changed(path: Path, content: str) -> bool:
    try:
        if path.read_text(encoding="utf-8") == content:
            return False
    except FileNotFoundError:
        pass
    atomic_write_text(path, content)
    return True
