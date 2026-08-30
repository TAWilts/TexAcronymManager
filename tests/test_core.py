from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tacroman.i18n import translate
from tacroman.importing import parse_acronym_package, read_tex_file
from tacroman.model import CommandEntry, command_map, comparison_matches, similarity_matches, validate_entry
from tacroman.profiles import load_profiles, normalise_profile
from tacroman.rendering import preview_diff, render, values_for_entry
from tacroman.storage import load_database, save_database


class TAcroManTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = {str(profile["id"]): profile for profile in load_profiles()}
        self.acronym_profile = self.profiles["acronym-package"]
        self.commands = command_map(self.acronym_profile)

    def test_default_profile_matches_acronym_environment(self) -> None:
        entries = [
            CommandEntry("acronym", {"short": "AOA", "long": "angle of arrival"}),
            CommandEntry("acronym", {"short": "ADC", "long": "analog to digital converter"}),
        ]
        self.assertEqual(
            render(entries, self.acronym_profile),
            "\\begin{acronym}\n"
            "\\acro{ADC}{analog to digital converter}\n"
            "\\acro{AOA}{angle of arrival}\n\\end{acronym}\n",
        )

    def test_complete_acronym_profile_matches_user_snippet(self) -> None:
        profile = self.profiles["acronym-complete-snippet"]
        entries = [CommandEntry("acronym", {"short": "ADC", "long": "analog to digital converter"})]
        self.assertEqual(
            render(entries, profile),
            "\\usepackage[printonlyused]{acronym}\n\n"
            "\\begin{acronym}\n"
            "\\acro{ADC}{analog to digital converter}\n"
            "\\end{acronym}\n",
        )

    def test_builtin_plural_uses_optional_field_wrapper(self) -> None:
        entries = [
            CommandEntry("acronym", {"short": "AUV", "long": "autonomous underwater vehicle"}),
            CommandEntry(
                "acroplural",
                {"key": "AUV", "short_plural": "AUVs", "long_plural": "autonomous underwater vehicles"},
            ),
        ]
        self.assertEqual(
            render(entries, self.acronym_profile),
            "\\begin{acronym}\n"
            "\\acro{AUV}{autonomous underwater vehicle}\n"
            "\\acroplural{AUV}[AUVs]{autonomous underwater vehicles}\n"
            "\\end{acronym}\n",
        )

    def test_render_can_preserve_the_supplied_table_order(self) -> None:
        entries = [
            CommandEntry(
                "acroplural",
                {"key": "AUV", "short_plural": "AUVs", "long_plural": "autonomous underwater vehicles"},
            ),
            CommandEntry("acronym", {"short": "DVL", "long": "Doppler velocity log"}),
            CommandEntry("acronym", {"short": "ADC", "long": "analog to digital converter"}),
        ]

        self.assertEqual(
            render(entries, self.acronym_profile, preserve_input_order=True),
            "\\begin{acronym}\n"
            "\\acroplural{AUV}[AUVs]{autonomous underwater vehicles}\n"
            "\\acro{DVL}{Doppler velocity log}\n"
            "\\acro{ADC}{analog to digital converter}\n\\end{acronym}\n",
        )

    def test_custom_commands_are_not_acronym_specific(self) -> None:
        profile = normalise_profile(
            {
                "id": "macros",
                "name": "Macros",
                "header": "",
                "footer": "\n",
                "separator": "\n",
                "sort_by": "name",
                "escape_mode": "none",
                "commands": [
                    {
                        "id": "define",
                        "label": "Definition",
                        "template": "\\newcommand{\\[[name]]}{[[body]]}",
                        "fields": [
                            {"id": "name", "required": True, "comparison_group": "macro-name"},
                            {"id": "body", "required": True},
                        ],
                    },
                    {
                        "id": "operator",
                        "label": "Operator",
                        "template": "\\DeclareMathOperator{\\[[name]]}{[[body]]}",
                        "fields": [
                            {"id": "name", "required": True, "comparison_group": "macro-name"},
                            {"id": "body", "required": True},
                        ],
                    },
                ],
            }
        )
        self.assertEqual(
            render([CommandEntry("define", {"name": "AUV", "body": "vehicle"})], profile),
            "\\newcommand{\\AUV}{vehicle}\n",
        )

    def test_same_command_comparison_key_blocks_saving(self) -> None:
        existing = [CommandEntry("acronym", {"short": "AUV", "long": "autonomous underwater vehicle"})]
        candidate = CommandEntry("acronym", {"short": "auv", "long": "another definition"})
        same, other = comparison_matches(candidate, self.commands["acronym"], existing, self.commands)
        self.assertEqual([match.entry.value("short") for match in same], ["AUV"])
        self.assertEqual(other, [])

    def test_cross_command_comparison_key_is_only_a_warning(self) -> None:
        existing = [CommandEntry("acronym", {"short": "AUV", "long": "autonomous underwater vehicle"})]
        candidate = CommandEntry("acroplural", {"key": "AUV", "long_plural": "autonomous underwater vehicles"})
        same, other = comparison_matches(candidate, self.commands["acroplural"], existing, self.commands)
        self.assertEqual(same, [])
        self.assertEqual([match.entry.command_id for match in other], ["acronym"])

    def test_different_comparison_groups_do_not_cross_check(self) -> None:
        profile = normalise_profile(
            {
                "id": "groups",
                "name": "Groups",
                "commands": [
                    {"id": "first", "template": "[[key]]", "fields": [{"id": "key", "comparison_group": "one"}]},
                    {"id": "second", "template": "[[key]]", "fields": [{"id": "key", "comparison_group": "two"}]},
                ],
            }
        )
        commands = command_map(profile)
        same, other = comparison_matches(
            CommandEntry("second", {"key": "AUV"}),
            commands["second"],
            [CommandEntry("first", {"key": "AUV"})],
            commands,
        )
        self.assertEqual(same, [])
        self.assertEqual(other, [])

    def test_similarity_is_non_blocking_and_profile_controlled(self) -> None:
        existing = [CommandEntry("acronym", {"short": "AUV", "long": "autonomous underwater vehicle"})]
        candidate = CommandEntry("acronym", {"short": "UUV", "long": "autonomous underwater vehicles"})
        matches = similarity_matches(candidate, self.commands["acronym"], existing, self.commands)
        self.assertTrue(any(match.matched_field_id == "long" for match in matches))

    def test_equal_long_form_is_a_warning_not_a_duplicate_error(self) -> None:
        existing = [CommandEntry("acronym", {"short": "AUV", "long": "autonomous underwater vehicle"})]
        candidate = CommandEntry("acronym", {"short": "UUV", "long": "autonomous underwater vehicle"})
        same, other = comparison_matches(candidate, self.commands["acronym"], existing, self.commands)
        hints = similarity_matches(candidate, self.commands["acronym"], existing, self.commands)
        self.assertEqual(same, [])
        self.assertEqual(other, [])
        self.assertTrue(any(match.matched_field_id == "long" and match.score == 1.0 for match in hints))

    def test_generic_validation_uses_declared_fields_only(self) -> None:
        command = {
            "id": "comment",
            "fields": [
                {"id": "title", "label": "Title", "required": True},
                {"id": "body", "label": "Body", "multiline": True},
            ],
        }
        errors, warnings = validate_entry(CommandEntry("comment", {"title": "", "body": "a\nb"}), command)
        self.assertEqual(len(errors), 1)
        self.assertEqual(warnings, [])

    def test_values_keep_latex_backslashes_when_wrapped(self) -> None:
        command = {
            "id": "x",
            "fields": [{"id": "value", "output_template": "[[[value]]]"}],
        }
        self.assertEqual(
            values_for_entry(CommandEntry("x", {"value": r"\textit{AUV}"}), command)["value"],
            r"[\textit{AUV}]",
        )

    def test_preview_diff_marks_changed_lines_and_keeps_removed_ones_visible(self) -> None:
        previous = "header\nold line\nfooter\n"
        current = "header\nnew line\nfooter\n"

        self.assertEqual(
            [(line.change, line.text) for line in preview_diff(previous, current)],
            [
                ("unchanged", "header\n"),
                ("removed", "old line\n"),
                ("added", "new line\n"),
                ("unchanged", "footer\n"),
            ],
        )

    def test_first_preview_has_no_change_markers(self) -> None:
        self.assertEqual(
            [(line.change, line.text) for line in preview_diff(None, "one\ntwo\n")],
            [("unchanged", "one\n"), ("unchanged", "two\n")],
        )

    def test_legacy_database_loads_and_new_save_migrates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "acronyms.json"
            path.write_text(
                json.dumps({"schema_version": 1, "acronyms": [{"short": "DVL", "long": "Doppler velocity log"}]}),
                encoding="utf-8",
            )
            loaded = load_database(path)
            self.assertEqual(loaded[0].command_id, "acronym")
            self.assertEqual(loaded[0].value("short"), "DVL")
            save_database(path, loaded)
            migrated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], 2)
            self.assertEqual(migrated["entries"][0]["values"]["long"], "Doppler velocity log")

    def test_generic_database_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "entries.json"
            original = [CommandEntry("macro", {"name": "AUV", "body": "vehicle"})]
            save_database(path, original)
            loaded = load_database(path)
            self.assertEqual(loaded[0].command_id, "macro")
            self.assertEqual(loaded[0].value("body"), "vehicle")

    def test_legacy_profile_loads_as_one_generic_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profiles.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "id": "legacy",
                            "name": "Legacy",
                            "entry": "\\acro{[[short]]}{[[long]]}",
                            "sort_by": "short",
                            "escape_mode": "none",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            profile = next(item for item in load_profiles(path) if item["id"] == "legacy")
            self.assertEqual(profile["commands"][0]["id"], "acronym")
            self.assertEqual(profile["commands"][0]["template"], "\\acro{[[short]]}{[[long]]}")

    def test_invalid_field_output_template_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalise_profile(
                {
                    "id": "invalid",
                    "name": "Invalid",
                    "commands": [
                        {
                            "id": "thing",
                            "template": "[[value]]",
                            "fields": [{"id": "value", "output_template": "wrapped"}],
                        }
                    ],
                }
            )

    def test_import_handles_nested_latex_braces(self) -> None:
        source = "\\acro{USBL}{ultra-short baseline}\\n\\acro{AUV}{autonomous \\textit{underwater} vehicle}"
        imported = parse_acronym_package(source)
        self.assertEqual(
            [(item.short, item.long) for item in imported],
            [("USBL", "ultra-short baseline"), ("AUV", "autonomous \\textit{underwater} vehicle")],
        )

    def test_tex_reader_accepts_utf8_with_bom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "acronyms.tex"
            path.write_bytes("\ufeff\\acro{AUV}{autonomous underwater vehicle}".encode("utf-8"))
            self.assertEqual(read_tex_file(path), "\\acro{AUV}{autonomous underwater vehicle}")

    def test_language_menu_is_translated(self) -> None:
        self.assertEqual(translate("de", "menu_language"), "Sprache")
        self.assertEqual(translate("en", "menu_language"), "Language")

if __name__ == "__main__":
    unittest.main()
