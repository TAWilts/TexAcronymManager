from __future__ import annotations

from pathlib import Path
import re
import unittest


class ReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.workflow = (cls.root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_published_release_builds_windows_and_linux(self) -> None:
        self.assertIn("release:\n    types: [published]", self.workflow)
        self.assertIn("runs-on: windows-latest", self.workflow)
        self.assertIn("runs-on: ubuntu-22.04", self.workflow)
        self.assertIn("python -m PyInstaller", self.workflow)
        self.assertIn(".venv-build/bin/python -m PyInstaller", self.workflow)
        self.assertIn("webview.platforms.gtk", self.workflow)

    def test_release_assets_wait_for_both_platform_builds(self) -> None:
        self.assertIn("needs: [validate, build-windows, build-linux]", self.workflow)
        self.assertIn("actions/download-artifact@v5", self.workflow)
        self.assertIn("sha256sum TAcroMan-* > SHA256SUMS.txt", self.workflow)
        self.assertIn('gh release upload "$RELEASE_TAG" package/* --clobber', self.workflow)
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertIn("permissions:\n      contents: write", self.workflow)
        self.assertNotIn("gh release create", self.workflow)

    def test_release_tag_must_match_both_python_versions(self) -> None:
        project = (self.root / "pyproject.toml").read_text(encoding="utf-8")
        package = (self.root / "src" / "tacroman" / "__init__.py").read_text(encoding="utf-8")

        self.assertIn("project=tomllib.loads", self.workflow)
        self.assertIn("actual=tacroman.__version__", self.workflow)
        project_version = re.search(r'(?m)^version\s*=\s*"([^"]+)"$', project)
        package_version = re.search(r'(?m)^__version__\s*=\s*"([^"]+)"$', package)
        self.assertIsNotNone(project_version)
        self.assertIsNotNone(package_version)
        assert project_version is not None and package_version is not None
        self.assertEqual(project_version.group(1), package_version.group(1))


if __name__ == "__main__":
    unittest.main()
