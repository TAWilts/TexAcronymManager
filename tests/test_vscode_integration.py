from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from tacroman.vscode_integration import detect_editor_launcher


class VSCodeIntegrationTests(unittest.TestCase):
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
