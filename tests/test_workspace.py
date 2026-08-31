import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from tacroman.model import CommandEntry
from tacroman.profiles import load_profiles
from tacroman.rendering import render
from tacroman.storage import save_database
from tacroman.workspace import (
    FRAGMENT_FORMAT,
    MANIFEST_FILENAME,
    WorkspaceConflictError,
    WorkspaceError,
    create_workspace,
    fragment_filename,
    import_legacy_database,
    join_workspace,
    load_workspace,
    rename_participant,
    save_local_entries,
    write_output_if_changed,
)


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profiles(Path("missing-profiles.json"))[0]
        self.first = str(uuid4())
        self.second = str(uuid4())

    def test_create_join_and_rename_keep_stable_owner_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "shared"
            first = create_workspace(root, self.first, self.profile, display_name="Peter")
            self.assertRegex(first.local_fragment_path.name, r"^Peter_[A-Za-z0-9]{8}\.tacroman\.json$")
            suffix = first.local_owner.suffix

            joined = join_workspace(root, self.second, display_name="Alex")
            self.assertEqual(joined.fragment_count, 2)
            renamed = rename_participant(root, self.first, load_workspace(root, self.first).revision, "Peter Smith")
            self.assertEqual(renamed.local_owner.installation_id, self.first)
            self.assertEqual(renamed.local_owner.suffix, suffix)
            self.assertEqual(renamed.local_fragment_path.name, f"Peter Smith_{suffix}.tacroman.json")

    def test_identical_duplicates_merge_and_divergent_duplicates_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "shared"
            create_workspace(root, self.first, self.profile, display_name="Peter")
            join_workspace(root, self.second, display_name="Alex")
            first_snapshot = load_workspace(root, self.first)
            first_entry = CommandEntry("acronym", {"short": "AUV", "long": "vehicle"})
            save_local_entries(root, self.first, first_snapshot.revision, [first_entry])

            second_snapshot = load_workspace(root, self.second)
            same = CommandEntry("acronym", {"short": "AUV", "long": "vehicle"})
            merged = save_local_entries(root, self.second, second_snapshot.revision, [same])
            self.assertEqual(len(merged.entries), 1)
            self.assertFalse(merged.conflicts)
            self.assertEqual(len(merged.merged_entries[0].sources), 2)
            self.assertEqual(render(merged.entries, merged.profile).count("\\acro{AUV}"), 1)

            second_snapshot = load_workspace(root, self.second)
            changed = CommandEntry("acronym", {"short": "AUV", "long": "different"}, uid=same.uid)
            conflicted = save_local_entries(root, self.second, second_snapshot.revision, [changed])
            self.assertFalse(conflicted.entries)
            self.assertEqual(len(conflicted.conflicts), 1)
            self.assertTrue(conflicted.export_blocked)

    def test_foreign_fragment_is_never_modified_by_local_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "shared"
            create_workspace(root, self.first, self.profile)
            second = join_workspace(root, self.second)
            foreign_before = second.local_fragment_path.read_bytes()
            first = load_workspace(root, self.first)
            save_local_entries(root, self.first, first.revision, [
                CommandEntry("acronym", {"short": "AUV", "long": "vehicle"})
            ])
            self.assertEqual(second.local_fragment_path.read_bytes(), foreign_before)

    def test_stale_revision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "shared"
            original = create_workspace(root, self.first, self.profile)
            join_workspace(root, self.second)
            second = load_workspace(root, self.second)
            save_local_entries(root, self.second, second.revision, [
                CommandEntry("acronym", {"short": "DVL", "long": "log"})
            ])
            with self.assertRaises(WorkspaceConflictError):
                save_local_entries(root, self.first, original.revision, [])

    def test_invalid_or_wrong_workspace_fragment_blocks_loading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "shared"
            snapshot = create_workspace(root, self.first, self.profile)
            invalid = root / "broken.tacroman.json"
            invalid.write_text(json.dumps({
                "format": FRAGMENT_FORMAT,
                "format_version": 1,
                "workspace_id": str(uuid4()),
            }), encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                load_workspace(root, self.first)
            invalid.unlink()
            self.assertEqual(load_workspace(root, self.first).workspace_id, snapshot.workspace_id)

    def test_manifest_marker_and_duplicate_installation_identity_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "shared"
            snapshot = create_workspace(root, self.first, self.profile, display_name="Peter")
            manifest_path = root / MANIFEST_FILENAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["format"] = "not-tacroman"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                load_workspace(root, self.first)

            manifest["format"] = "tacroman-workspace"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            duplicate = json.loads(snapshot.local_fragment_path.read_text(encoding="utf-8"))
            duplicate["owner"]["suffix"] = "Ab12Cd34"
            (root / "Peter_Ab12Cd34.tacroman.json").write_text(json.dumps(duplicate), encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                load_workspace(root, self.first)

    def test_legacy_import_preserves_source_and_uids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "shared"
            snapshot = create_workspace(root, self.first, self.profile)
            legacy = base / "entries.json"
            entry = CommandEntry("acronym", {"short": "AUV", "long": "vehicle"})
            save_database(legacy, [entry])
            original = legacy.read_bytes()
            imported = import_legacy_database(root, self.first, snapshot.revision, legacy)
            self.assertEqual(imported.local_entries[0].uid, entry.uid)
            self.assertEqual(legacy.read_bytes(), original)

    def test_output_is_not_rewritten_when_content_is_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entries.tex"
            self.assertTrue(write_output_if_changed(path, "one"))
            first_stat = path.stat().st_mtime_ns
            self.assertFalse(write_output_if_changed(path, "one"))
            self.assertEqual(path.stat().st_mtime_ns, first_stat)

    def test_shared_contract_fixture_has_expected_merge_and_conflict(self) -> None:
        fixture = json.loads((Path(__file__).parent / "fixtures" / "workspace_contract.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".tacroman-workspace.json").write_text(
                json.dumps(fixture["manifest"]), encoding="utf-8"
            )
            for name, payload in fixture["fragments"].items():
                (root / name).write_text(json.dumps(payload), encoding="utf-8")
            snapshot = load_workspace(root, "22222222-2222-4222-8222-222222222222")
            self.assertEqual([entry.value("short") for entry in snapshot.entries], fixture["expected"]["merged_keys"])
            self.assertEqual([item.label for item in snapshot.conflicts], fixture["expected"]["conflict_labels"])
            self.assertEqual([item.conflict_id for item in snapshot.conflicts], fixture["expected"]["conflict_ids"])


if __name__ == "__main__":
    unittest.main()
