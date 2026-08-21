from pathlib import Path
import tempfile
import unittest

from tacroman.reference_audit import audit_project, discover_reference_files, find_citation_occurrences
from tacroman.reference_audit_dialog import _initial_project_directory, _row_matches_search


BIB = r'''
@article{smithSLAM2024,
  title = {Underwater {SLAM} with Sonar},
  author = {Smith, Jane and Miller, John},
  year = {2024}
}

@inproceedings{unusedAUV2023,
  title = {An Unused AUV Paper},
  author = {Doe, Alex},
  year = {2023}
}

@article{camera2022,
  title = {Optical Localization Underwater},
  author = {Roe, Robin},
  year = {2022}
}
'''


class ReferenceAuditTests(unittest.TestCase):
    def test_find_citations_ignores_comments_and_reports_line_excerpt(self) -> None:
        text = "Intro\n% \\cite{unusedAUV2023}\nResult \\cite[see]{smithSLAM2024,camera2022}.\n"
        found, nocite_all = find_citation_occurrences(text, Path("chapter.tex"))
        self.assertFalse(nocite_all)
        self.assertEqual([item.key for item in found], ["smithSLAM2024", "camera2022"])
        self.assertEqual([item.line for item in found], [3, 3])
        self.assertTrue(all(item.key in item.excerpt for item in found))

    def test_multicite_commands_are_scanned(self) -> None:
        text = r"\parencites[see][]{smithSLAM2024}[and][]{camera2022}"
        found, _ = find_citation_occurrences(text)
        self.assertEqual([item.key for item in found], ["smithSLAM2024", "camera2022"])

    def test_nocite_star_marks_all_as_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            refs = root / "refs.bib"
            refs.write_text(BIB, encoding="utf-8")
            (root / "main.tex").write_text(r"\nocite{*}", encoding="utf-8")
            report = audit_project(root, refs)
            self.assertEqual(report.unused, ())

    def test_audit_reports_unused_used_occurrences_and_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            refs = root / "refs.bib"
            refs.write_text(BIB, encoding="utf-8")
            (root / "main.tex").write_text(
                "\\cite{smithSLAM2024}\n\\input{chapter}\n",
                encoding="utf-8",
            )
            (root / "chapter.tex").write_text(
                "Again \\textcite{smithSLAM2024}; then \\cite{missingKey}.\n",
                encoding="utf-8",
            )
            # Generated files must not make unused entries appear cited.
            build = root / "build"
            build.mkdir()
            (build / "generated.tex").write_text(r"\cite{unusedAUV2023}", encoding="utf-8")

            report = audit_project(root, refs)
            self.assertEqual([item.key for item in report.unused], ["camera2022", "unusedAUV2023"])
            self.assertEqual([item.key for item in report.occurrences], ["missingKey", "smithSLAM2024", "smithSLAM2024"])
            self.assertEqual(report.unknown_keys, ("missingKey",))
            self.assertEqual(report.used_keys, ("smithSLAM2024",))
            smith = next(item for item in report.occurrences if item.key == "smithSLAM2024")
            self.assertIn("Underwater SLAM with Sonar", smith.title)
            self.assertIn("Smith, Jane", smith.author)

    def test_discover_reference_files_only_returns_files_with_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "refs.bib").write_text(BIB, encoding="utf-8")
            (root / "notes.tex").write_text("No bibliography here.", encoding="utf-8")
            (root / "embedded.tex").write_text("@article{key, title={Title}}", encoding="utf-8")
            found = discover_reference_files(root)
            self.assertEqual([path.name for path in found], ["refs.bib", "embedded.tex"])

    def test_default_excerpt_radius_is_fifty_characters_each_side(self) -> None:
        prefix = "A" * 80
        suffix = "B" * 80
        text = prefix + r"\cite{smithSLAM2024}" + suffix
        found, _ = find_citation_occurrences(text)
        self.assertEqual(len(found), 1)
        excerpt = found[0].excerpt
        shorter, _ = find_citation_occurrences(text, excerpt_radius=20)
        self.assertGreater(len(excerpt), len(shorter[0].excerpt))
        self.assertGreaterEqual(len(excerpt), 100)

    def test_initial_project_directory_uses_generated_file_parent(self) -> None:
        class Variable:
            def get(self) -> str:
                return "/tmp/dissertation/acronyms.tex"

        class App:
            output_path_var = Variable()

        self.assertEqual(Path(_initial_project_directory(App())), Path("/tmp/dissertation"))

    def test_reference_audit_search_matches_terms_across_any_columns(self) -> None:
        row = ("chapter/navigation.tex", 42, "smithSLAM2024", "Underwater SLAM", "Jane Smith", "sonar excerpt")
        self.assertTrue(_row_matches_search(row, "slam sonar"))
        self.assertTrue(_row_matches_search(row, "SMITH 42"))
        self.assertFalse(_row_matches_search(row, "slam optical"))
        self.assertTrue(_row_matches_search(row, ""))


if __name__ == "__main__":
    unittest.main()
