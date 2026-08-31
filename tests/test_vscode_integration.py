from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from tacroman.vscode_integration import (
    detect_editor_launcher,
    ensure_installation_id,
    read_shared_state,
    write_vscode_integration_state,
)


class VSCodeIntegrationTests(unittest.TestCase):
    def test_shared_state_merges_paths_and_keeps_other_frontend_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "TAcroMan" / "state.json"
            state_path.parent.mkdir()
            state_path.write_text('{"extensionField": "kept"}', encoding="utf-8")
            workspace = root / "shared"
            fragment = workspace / "Peter_12345678.tacroman.json"
            output = root / "project" / "entries.tex"

            write_vscode_integration_state(
                workspace,
                output,
                fragment_path=fragment,
                installation_id="f3181be7-a1a4-4d4c-8e4d-f24249546e45",
                output_mode="project",
                state_path=state_path,
            )

            state = read_shared_state(state_path)
            self.assertEqual(state["workspacePath"], str(workspace.resolve()))
            self.assertEqual(state["fragmentPath"], str(fragment.resolve()))
            self.assertEqual(state["installationId"], "f3181be7-a1a4-4d4c-8e4d-f24249546e45")
            self.assertEqual(state["outputPath"], str(output.resolve()))
            self.assertEqual(state["outputMode"], "project")
            self.assertEqual(state["extensionField"], "kept")
            self.assertNotIn("last_database_path", state)
            self.assertNotIn("databasePath", state)

    def test_installation_identity_is_created_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "TAcroMan" / "state.json"
            first = ensure_installation_id(state_path)
            second = ensure_installation_id(state_path)
            self.assertEqual(first, second)

    def test_shared_state_does_not_import_legacy_path_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "TAcroMan" / "state.json"
            state_path.parent.mkdir()
            state_path.write_text(
                '{"last_database_path": "D:/legacy/entries.json"}',
                encoding="utf-8",
            )

            state = read_shared_state(state_path)

            self.assertNotIn("databasePath", state)

    def test_frozen_application_relaunches_its_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "TAcroMan.exe"
            executable.touch()
            launcher = detect_editor_launcher(
                executable=executable,
                argv0=executable,
                platform="win32",
                frozen=True,
            )
            self.assertEqual(launcher, {"executable": str(executable.resolve()), "args": []})

    def test_windows_venv_prefers_installed_tacroman_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scripts = Path(directory) / "Scripts"
            scripts.mkdir()
            python = scripts / "python.exe"
            tacroman = scripts / "tacroman.exe"
            python.touch()
            tacroman.touch()

            launcher = detect_editor_launcher(
                executable=python,
                argv0="ignored",
                platform="win32",
                frozen=False,
            )
            self.assertEqual(launcher, {"executable": str(tacroman.resolve()), "args": []})

    def test_falls_back_to_python_module_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / "python.exe"
            python.touch()
            launcher = detect_editor_launcher(
                executable=python,
                argv0="missing",
                platform="win32",
                frozen=False,
            )
            self.assertEqual(
                launcher,
                {"executable": str(python.resolve()), "args": ["-m", "tacroman"]},
            )


if __name__ == "__main__":
    unittest.main()
