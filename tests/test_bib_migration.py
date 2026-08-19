from pathlib import Path
import tempfile
import unittest

from tacroman.bib_migration import (
    build_key_migration,
    migrate_tex_files,
    parse_bibtex,
    replace_citation_keys,
)


OLD_BIB = r'''
@article{Smith2019,
  title = {Underwater {SLAM} with Sonar},
  author = {Smith, Jane},
  year = {2019},
  doi = {10.1000/example.1}
}

@inproceedings{OldOnlyTitle,
  title = {A Robust Method for AUV Navigation},
  year = {2020}
}

@article{AlreadyGood,
  title = {Keep This Key},
  year = {2021}
}
'''

NEW_BIB = r'''
@article{smithUnderwaterSLAM2019,
  title = {Underwater SLAM with Sonar},
  author = {Smith, Jane},
  date = {2019},
  doi = {https://doi.org/10.1000/example.1}
}

@inproceedings{millerRobustMethodAUV2020,
  title = {A Robust Method for {AUV} Navigation},
  date = {2020-05}
}

@article{AlreadyGood,
  title = {Keep This Key},
  date = {2021}
}
'''


class BibMigrationTests(unittest.TestCase):
    def test_parse_bibtex_handles_nested_braces(self) -> None:
        entries = parse_bibtex(OLD_BIB)
        self.assertEqual([entry.key for entry in entries], ["Smith2019", "OldOnlyTitle", "AlreadyGood"])
        self.assertEqual(entries[0].field("doi"), "10.1000/example.1")
        self.assertIn("{SLAM}", entries[0].field("title"))

    def test_build_mapping_prefers_doi_and_title_year(self) -> None:
        report = build_key_migration(OLD_BIB, NEW_BIB)
        self.assertEqual(report.mapping["Smith2019"], "smithUnderwaterSLAM2019")
        self.assertEqual(report.mapping["OldOnlyTitle"], "millerRobustMethodAUV2020")
        self.assertNotIn("AlreadyGood", report.mapping)
        self.assertEqual(report.changed_count, 2)
        self.assertEqual(report.unchanged_count, 1)

    def test_ids_alias_is_supported(self) -> None:
        old = '@article{LegacyKey, title={Some Paper}, year={2022}}'
        new = '@article{betterKey2022, title={Changed Metadata}, date={2022}, ids={LegacyKey}}'
        report = build_key_migration(old, new)
        self.assertEqual(report.mapping, {"LegacyKey": "betterKey2022"})
        self.assertEqual(report.matches[0].method, "ids")

    def test_ambiguous_title_is_not_mapped(self) -> None:
        old = '@article{old, title={Same Title}}'
        new = '@article{one, title={Same Title}}\n@article{two, title={Same Title}}'
        report = build_key_migration(old, new)
        self.assertEqual(report.mapping, {})
        self.assertEqual(report.ambiguous_count, 1)

    def test_replace_citation_keys_only_changes_citations(self) -> None:
        tex = r'''Text \cite{Smith2019, AlreadyGood}.
Another \parencite[see][p.~4]{OldOnlyTitle}.
The literal key Smith2019 must stay.
% \cite{Smith2019} commented out
Escaped percent \% and citation \citet{Smith2019}.
'''
        migrated, count = replace_citation_keys(
            tex,
            {
                "Smith2019": "smithUnderwaterSLAM2019",
                "OldOnlyTitle": "millerRobustMethodAUV2020",
            },
        )
        self.assertEqual(count, 3)
        self.assertIn(r"\cite{smithUnderwaterSLAM2019, AlreadyGood}", migrated)
        self.assertIn(r"\parencite[see][p.~4]{millerRobustMethodAUV2020}", migrated)
        self.assertIn("The literal key Smith2019 must stay.", migrated)
        self.assertIn(r"% \cite{Smith2019} commented out", migrated)
        self.assertIn(r"\citet{smithUnderwaterSLAM2019}", migrated)

    def test_migrate_files_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chapter.tex"
            path.write_text(r"See \cite{oldKey}.", encoding="utf-8")
            result = migrate_tex_files([path], {"oldKey": "newKey"}, backup=True)
            self.assertEqual(result.replacements, 1)
            self.assertEqual(result.files_changed, 1)
            self.assertEqual(path.read_text(encoding="utf-8"), r"See \cite{newKey}.")
            self.assertEqual((Path(str(path) + ".bak")).read_text(encoding="utf-8"), r"See \cite{oldKey}.")


if __name__ == "__main__":
    unittest.main()
