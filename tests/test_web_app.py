from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from tacroman.model import CommandEntry
from tacroman.web_app import DesktopWebApi, WebAppController, build_desktop_html
from tacroman.workspace import (
    MANIFEST_FILENAME,
    create_workspace,
    join_workspace,
    load_workspace,
    save_local_entries,
)


class WebAppTests(unittest.TestCase):
    def test_desktop_document_embeds_the_shared_frontend(self) -> None:
        document = build_desktop_html()
        self.assertIn("<style>", document)
        self.assertIn("const queuedDesktopMessages", document)
        self.assertIn('id="desktop-menubar"', document)
        self.assertIn('id="conflict-dialog"', document)
        self.assertIn('id="rename-participant"', document)
        self.assertIn('role="tooltip"', document)
        self.assertIn('menu.addEventListener("toggle"', document)
        self.assertNotIn("{{STYLE_URI}}", document)
        self.assertNotIn("{{SCRIPT_URI}}", document)
        self.assertNotIn("Content-Security-Policy", document)

    def test_controller_creates_first_workspace_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "shared"
            output = root / "paper" / "entries.tex"
            messages: list[dict[str, object]] = []
            controller = WebAppController(
                workspace,
                output,
                state_path=root / "home" / "TAcroMan" / "state.json",
                emit=messages.append,
            )
            controller.handle_message({"type": "ready"})
            self.assertTrue((workspace / MANIFEST_FILENAME).is_file())
            self.assertEqual(len(list(workspace.glob("*.tacroman.json"))), 1)
            self.assertTrue(output.is_file())
            snapshot = messages[-1]["snapshot"]
            assert isinstance(snapshot, dict)
            self.assertEqual(snapshot["hostKind"], "desktop")
            self.assertEqual(snapshot["workspacePath"], str(workspace.resolve()))
            self.assertTrue(snapshot["owner"])
            self.assertEqual(snapshot["conflicts"], [])

    def test_controller_saves_deletes_and_renders_only_local_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = WebAppController(root / "shared", root / "entries.tex", state_path=root / "state.json")
            revision = str(controller.snapshot()["revision"])
            controller.handle_message({
                "type": "saveEntry",
                "revision": revision,
                "entry": {
                    "commandId": "acronym",
                    "values": {"short": "AUV", "long": "autonomous underwater vehicle"},
                },
            })
            current = load_workspace(root / "shared", controller.installation_id)
            self.assertEqual([entry.value("short") for entry in current.local_entries], ["AUV"])
            self.assertIn("\\acro{AUV}{autonomous underwater vehicle}", (root / "entries.tex").read_text(encoding="utf-8"))
            controller.handle_message({
                "type": "deleteEntry",
                "revision": current.revision,
                "uid": current.local_entries[0].uid,
            })
            self.assertEqual(load_workspace(root / "shared", controller.installation_id).local_entries, ())

    def test_conflicting_foreign_change_blocks_output_and_stale_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            messages: list[dict[str, object]] = []
            output = root / "entries.tex"
            controller = WebAppController(root / "shared", output, state_path=root / "state.json", emit=messages.append)
            initial = controller.snapshot()
            controller.handle_message({
                "type": "saveEntry",
                "revision": initial["revision"],
                "entry": {"commandId": "acronym", "values": {"short": "AUV", "long": "vehicle"}},
            })
            good_output = output.read_bytes()
            second_id = str(uuid4())
            second = join_workspace(root / "shared", second_id, display_name="Alex")
            save_local_entries(root / "shared", second_id, second.revision, [
                CommandEntry("acronym", {"short": "AUV", "long": "different"})
            ])
            controller.poll_once()
            conflicted = controller.snapshot()
            self.assertTrue(conflicted["exportBlocked"])
            self.assertEqual(len(conflicted["conflicts"]), 1)
            self.assertEqual(output.read_bytes(), good_output)
            variants = conflicted["conflicts"][0]["variants"]
            local = next(variant for variant in variants if variant["editable"])
            foreign = next(variant for variant in variants if not variant["editable"])
            controller.handle_message({
                "type": "saveEntry",
                "revision": conflicted["revision"],
                "entry": {
                    "uid": local["uid"],
                    "commandId": foreign["commandId"],
                    "values": foreign["values"],
                },
            })
            resolved = controller.snapshot()
            self.assertFalse(resolved["exportBlocked"])
            self.assertFalse(resolved["conflicts"])
            self.assertIn("different", output.read_text(encoding="utf-8"))
            controller.handle_message({
                "type": "saveEntry",
                "revision": initial["revision"],
                "entry": {"commandId": "acronym", "values": {"short": "DVL", "long": "log"}},
            })
            self.assertEqual(messages[-2]["type"], "error")
            self.assertEqual(messages[-1]["reason"], "external")

    def test_new_local_change_that_would_create_conflict_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            messages: list[dict[str, object]] = []
            controller = WebAppController(
                root / "shared",
                root / "entries.tex",
                state_path=root / "state.json",
                emit=messages.append,
            )
            foreign_id = str(uuid4())
            foreign = join_workspace(root / "shared", foreign_id, display_name="Alex")
            save_local_entries(root / "shared", foreign_id, foreign.revision, [
                CommandEntry("acronym", {"short": "AUV", "long": "foreign value"})
            ])
            controller.poll_once()
            current = controller.snapshot()
            controller.handle_message({
                "type": "saveEntry",
                "revision": current["revision"],
                "entry": {"commandId": "acronym", "values": {"short": "AUV", "long": "local value"}},
            })
            self.assertEqual(messages[-1]["type"], "error")
            self.assertFalse(load_workspace(root / "shared", controller.installation_id).local_entries)

    def test_native_callbacks_select_and_create_workspace_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            selected_output = root / "selected.tex"
            controller = WebAppController(
                first,
                root / "first.tex",
                state_path=root / "state.json",
                choose_database=lambda _current: second,
                choose_output=lambda _current: selected_output,
            )
            create_workspace(second, controller.installation_id, controller.active_profile)
            controller.handle_message({"type": "selectDatabase"})
            controller.handle_message({"type": "selectOutput"})
            snapshot = controller.snapshot()
            self.assertEqual(snapshot["workspacePath"], str(second.resolve()))
            self.assertEqual(snapshot["outputPath"], str(selected_output.resolve()))

    def test_imports_tex_and_legacy_database_without_modifying_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            imported_tex = root / "existing.tex"
            imported_tex.write_text("\\acro{AUV}{autonomous underwater vehicle}\n", encoding="utf-8")
            legacy = root / "legacy.json"
            legacy.write_text(json.dumps({
                "schema_version": 2,
                "entries": [{
                    "uid": "legacy-dvl",
                    "command_id": "acronym",
                    "values": {"short": "DVL", "long": "Doppler velocity log"},
                }],
            }), encoding="utf-8")
            original = legacy.read_bytes()
            messages: list[dict[str, object]] = []
            controller = WebAppController(
                root / "shared",
                root / "entries.tex",
                state_path=root / "state.json",
                emit=messages.append,
                choose_import_tex=lambda _current: imported_tex,
                choose_import_database=lambda _current: legacy,
            )
            controller.handle_message({"type": "importTex", "mode": "merge", "revision": controller.snapshot()["revision"]})
            controller.handle_message({"type": "importDatabase", "revision": controller.snapshot()["revision"]})
            preview = messages[-1]
            self.assertEqual(preview["type"], "importPreview")
            self.assertEqual(preview["importedCount"], 1)
            controller.handle_message({
                "type": "commitDatabaseImport",
                "token": preview["token"],
                "revision": preview["revision"],
            })
            entries = load_workspace(root / "shared", controller.installation_id).local_entries
            self.assertEqual([entry.value("short") for entry in entries], ["AUV", "DVL"])
            self.assertEqual(legacy.read_bytes(), original)

    def test_profile_editor_writes_active_profile_to_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            messages: list[dict[str, object]] = []
            controller = WebAppController(root / "shared", root / "entries.tex", state_path=root / "state.json", emit=messages.append)
            profile = json.loads(json.dumps(controller.active_profile))
            profile["name"] = "Edited Web Profile"
            controller.handle_message({
                "type": "saveProfile",
                "originalId": profile["id"],
                "profile": profile,
                "revision": controller.snapshot()["revision"],
            })
            manifest = json.loads((root / "shared" / MANIFEST_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(manifest["profile"]["name"], "Edited Web Profile")
            self.assertEqual(messages[-2]["type"], "profileEditor")
            self.assertEqual(messages[-1]["type"], "snapshot")

    def test_citation_and_reference_tools_still_use_workspace_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_bib = root / "old.bib"
            new_bib = root / "new.bib"
            tex = root / "chapter.tex"
            old_bib.write_text('@article{OldKey, title={A Study}, year={2024}}', encoding="utf-8")
            new_bib.write_text('@article{NewKey, title={A Study}, year={2024}}', encoding="utf-8")
            tex.write_text("See \\cite{OldKey}.", encoding="utf-8")
            messages: list[dict[str, object]] = []
            controller = WebAppController(
                root / "shared",
                root / "entries.tex",
                state_path=root / "state.json",
                emit=messages.append,
                choose_tool_paths=lambda target, _current: [root] if target == "auditProject" else [tex],
            )
            controller.handle_message({"type": "analyseCitations", "oldBib": str(old_bib), "newBib": str(new_bib)})
            self.assertEqual(messages[-1]["type"], "citationAnalysis")
            controller.handle_message({
                "type": "applyCitationMigration",
                "mapping": {"OldKey": "NewKey"},
                "paths": [str(tex)],
                "backup": True,
            })
            self.assertIn("\\cite{NewKey}", tex.read_text(encoding="utf-8"))
            controller.handle_message({"type": "auditReferences", "project": str(root), "reference": str(new_bib)})
            self.assertEqual(messages[-1]["type"], "referenceAudit")

    def test_polling_applies_workspace_selection_from_other_frontend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.json"
            first = root / "first"
            second = root / "second"
            messages: list[dict[str, object]] = []
            controller = WebAppController(first, root / "entries.tex", state_path=state_path, emit=messages.append)
            create_workspace(second, controller.installation_id, controller.active_profile)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["workspacePath"] = str(second.resolve())
            state_path.write_text(json.dumps(state), encoding="utf-8")
            self.assertTrue(controller.poll_once())
            self.assertEqual(controller.snapshot()["workspacePath"], str(second.resolve()))
            self.assertEqual(messages[-1]["reason"], "external")

    def test_pywebview_adapter_forwards_workspace_snapshot(self) -> None:
        class FakeWindow:
            def __init__(self) -> None:
                self.scripts: list[str] = []

            def run_js(self, script: str) -> None:
                self.scripts.append(script)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api = DesktopWebApi(
                WebAppController,
                workspace_path=root / "shared",
                output_path=root / "entries.tex",
                state_path=root / "state.json",
            )
            window = FakeWindow()
            api._attach_window(window)
            api.post_message('{"type":"ready"}')
            self.assertFalse(hasattr(api, "window"))
            self.assertFalse(hasattr(api, "controller"))
            self.assertEqual([name for name in dir(api) if not name.startswith("_")], ["post_message"])
            self.assertIn('"workspacePath":', window.scripts[0])


if __name__ == "__main__":
    unittest.main()
