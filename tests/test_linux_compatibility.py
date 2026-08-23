from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tacroman.vscode_integration import detect_editor_launcher, vscode_integration_state_path


class LinuxCompatibilityTests(unittest.TestCase):
    def test_xdg_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("tacroman.vscode_integration.sys.platform", "linux"):
                with patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}, clear=False):
                    self.assertEqual(
                        vscode_integration_state_path(),
                        Path(directory) / "tacroman" / "vscode-integration.json",
                    )

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
