from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tacroman.model import CommandEntry
from tacroman.storage import load_database, save_database
from tacroman.web_app import DesktopWebApi, WebAppController, build_desktop_html


class WebAppTests(unittest.TestCase):
    def test_desktop_document_embeds_the_shared_frontend(self) -> None:
        document = build_desktop_html()

        self.assertIn("<style>", document)
        self.assertIn("const queuedDesktopMessages", document)
        self.assertIn('id="desktop-menubar"', document)
        self.assertIn("height: 100vh", document)
        self.assertNotIn("{{STYLE_URI}}", document)
        self.assertNotIn("{{SCRIPT_URI}}", document)
        self.assertNotIn("Content-Security-Policy", document)

    def test_controller_creates_first_run_files_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            messages: list[dict[str, object]] = []
            database = root / "data" / "entries.json"
            output = root / "paper" / "entries.tex"
            controller = WebAppController(
                database,
                output,
                state_path=root / "home" / "TAcroMan" / "state.json",
                emit=messages.append,
            )

            controller.handle_message({"type": "ready"})

            self.assertTrue(database.is_file())
            self.assertTrue(output.is_file())
            snapshot = messages[-1]["snapshot"]
            self.assertIsInstance(snapshot, dict)
            assert isinstance(snapshot, dict)
            self.assertEqual(snapshot["hostKind"], "desktop")
            self.assertEqual(snapshot["databasePath"], str(database.resolve()))
            self.assertTrue(snapshot["profiles"])

    def test_controller_saves_deletes_and_renders_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            messages: list[dict[str, object]] = []
            database = root / "entries.json"
            output = root / "entries.tex"
            controller = WebAppController(
                database,
                output,
                state_path=root / "state.json",
                emit=messages.append,
            )
            revision = str(controller.snapshot()["revision"])

            controller.handle_message(
                {
                    "type": "saveEntry",
                    "revision": revision,
                    "entry": {
                        "commandId": "acronym",
                        "values": {"short": "AUV", "long": "autonomous underwater vehicle"},
                    },
                }
            )

            entries = load_database(database)
            self.assertEqual([(entry.value("short"), entry.value("long")) for entry in entries], [
                ("AUV", "autonomous underwater vehicle")
            ])
            self.assertIn("\\acro{AUV}{autonomous underwater vehicle}", output.read_text(encoding="utf-8"))
            mutation_snapshot = messages[-1]["snapshot"]
            assert isinstance(mutation_snapshot, dict)
            controller.handle_message(
                {
                    "type": "deleteEntry",
                    "revision": mutation_snapshot["revision"],
                    "uid": entries[0].uid,
                }
            )
            self.assertEqual(load_database(database), [])

    def test_controller_rejects_a_stale_save_without_overwriting_external_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            messages: list[dict[str, object]] = []
            database = root / "entries.json"
            controller = WebAppController(
                database,
                root / "entries.tex",
                state_path=root / "state.json",
                emit=messages.append,
            )
            stale_revision = str(controller.snapshot()["revision"])
            external = CommandEntry("acronym", {"short": "DVL", "long": "Doppler velocity log"})
            save_database(database, [external])

            controller.handle_message(
                {
                    "type": "saveEntry",
                    "revision": stale_revision,
                    "entry": {
                        "commandId": "acronym",
                        "values": {"short": "AUV", "long": "autonomous underwater vehicle"},
                    },
                }
            )

            self.assertEqual([entry.value("short") for entry in load_database(database)], ["DVL"])
            self.assertEqual(messages[-2]["type"], "error")
            self.assertEqual(messages[-1]["reason"], "external")

    def test_controller_uses_native_path_callbacks_and_switches_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.json"
            second = root / "second.json"
            selected_output = root / "selected.tex"
            save_database(first, [])
            save_database(second, [CommandEntry("acronym", {"short": "AUV", "long": "vehicle"})])
            controller = WebAppController(
                first,
                root / "first.tex",
                state_path=root / "state.json",
                choose_database=lambda _current: second,
                choose_output=lambda _current: selected_output,
            )

            controller.handle_message({"type": "selectDatabase"})
            controller.handle_message({"type": "selectOutput"})
            controller.handle_message({"type": "selectProfile", "profileId": "acro-package"})

            snapshot = controller.snapshot()
            self.assertEqual(snapshot["databasePath"], str(second.resolve()))
            self.assertEqual(snapshot["outputPath"], str(selected_output.resolve()))
            self.assertEqual(snapshot["profile"]["id"], "acro-package")
            self.assertIn("\\DeclareAcronym", selected_output.read_text(encoding="utf-8"))

    def test_controller_creates_databases_imports_tex_and_runs_classic_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.json"
            created = root / "created.json"
            imported_tex = root / "existing.tex"
            imported_tex.write_text(
                "\\acro{AUV}{autonomous underwater vehicle}\n\\acro{DVL}{Doppler velocity log}\n",
                encoding="utf-8",
            )
            launched: list[tuple[str, Path, Path, Path]] = []
            controller = WebAppController(
                first,
                root / "first.tex",
                state_path=root / "state.json",
                choose_new_database=lambda _current: created,
                choose_import_tex=lambda _current: imported_tex,
                launch_legacy_tool=lambda action, database, output, profiles: launched.append(
                    (action, database, output, profiles)
                ),
            )

            controller.handle_message({"type": "newDatabase"})
            controller.handle_message({
                "type": "importTex",
                "mode": "merge",
                "revision": controller.snapshot()["revision"],
            })
            controller.handle_message({"type": "setLanguage", "language": "de"})
            controller.handle_message({"type": "runLegacyTool", "action": "reference-audit"})

            self.assertEqual(controller.snapshot()["databasePath"], str(created.resolve()))
            self.assertEqual(controller.snapshot()["language"], "de")
            self.assertEqual([entry.value("short") for entry in load_database(created)], ["AUV", "DVL"])
            self.assertEqual(launched[0][0], "reference-audit")

    def test_polling_applies_database_selection_from_another_frontend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.json"
            second = root / "second.json"
            state_path = root / "state.json"
            save_database(first, [])
            save_database(second, [CommandEntry("acronym", {"short": "AUV", "long": "vehicle"})])
            messages: list[dict[str, object]] = []
            controller = WebAppController(first, root / "entries.tex", state_path=state_path, emit=messages.append)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["databasePath"] = str(second.resolve())
            state_path.write_text(json.dumps(state), encoding="utf-8")

            self.assertTrue(controller.poll_once())
            self.assertEqual(controller.snapshot()["databasePath"], str(second.resolve()))
            self.assertEqual(messages[-1]["reason"], "external")

    def test_pywebview_adapter_forwards_messages_to_the_shared_window_protocol(self) -> None:
        class FakeWindow:
            def __init__(self) -> None:
                self.scripts: list[str] = []

            def run_js(self, script: str) -> None:
                self.scripts.append(script)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api = DesktopWebApi(
                WebAppController,
                database_path=root / "entries.json",
                output_path=root / "entries.tex",
                state_path=root / "state.json",
            )
            window = FakeWindow()
            api._attach_window(window)

            api.post_message('{"type":"ready"}')

            self.assertFalse(hasattr(api, "window"))
            self.assertFalse(hasattr(api, "controller"))
            self.assertEqual([name for name in dir(api) if not name.startswith("_")], ["post_message"])
            self.assertEqual(len(window.scripts), 1)
            self.assertIn('window.postMessage({"type": "snapshot"', window.scripts[0])
            self.assertIn('"hostKind": "desktop"', window.scripts[0])


if __name__ == "__main__":
    unittest.main()
