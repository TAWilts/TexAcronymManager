from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tacroman.vscode_integration import detect_editor_launcher, shared_state_path


class LinuxCompatibilityTests(unittest.TestCase):
    def test_linux_install_uses_distribution_gtk_bindings(self) -> None:
        root = Path(__file__).resolve().parents[1]
        project = (root / "pyproject.toml").read_text(encoding="utf-8")
        installer = (root / "install-linux.sh").read_text(encoding="utf-8")
        workflow = (root / ".github" / "workflows" / "linux-compatibility.yml").read_text(encoding="utf-8")

        self.assertNotIn("pywebview[gtk]", project)
        self.assertIn('"pywebview>=6.2,<7"', project)
        self.assertIn("venv --system-site-packages", installer)
        self.assertIn("venv --system-site-packages", workflow)
        self.assertIn("python3-gi", workflow)
        self.assertIn("gir1.2-webkit2-4.1", workflow)

    def test_webview_is_the_only_desktop_frontend(self) -> None:
        root = Path(__file__).resolve().parents[1]
        project = (root / "pyproject.toml").read_text(encoding="utf-8")
        workflow = (root / ".github" / "workflows" / "linux-compatibility.yml").read_text(encoding="utf-8")

        self.assertNotIn("tacroman-tk", project)
        self.assertNotIn("python3-tk", workflow)
        self.assertFalse((root / "src" / "tacroman" / "app.py").exists())
        self.assertFalse((root / "src" / "tacroman" / "reference_audit_dialog.py").exists())

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
