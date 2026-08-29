from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tacroman.vscode_integration import detect_editor_launcher, shared_state_path


class LinuxCompatibilityTests(unittest.TestCase):
    def test_shared_state_is_in_the_tacroman_user_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(shared_state_path(home=Path(directory)), Path(directory) / "TAcroMan" / "state.json")

    def test_venv_console_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            python = bin_dir / "python"
            launcher = bin_dir / "tacroman"
            python.touch()
            launcher.touch()
            self.assertEqual(
                detect_editor_launcher(executable=python, argv0="missing", platform="linux", frozen=False),
                {"executable": str(launcher.resolve()), "args": []},
            )


if __name__ == "__main__":
    unittest.main()
