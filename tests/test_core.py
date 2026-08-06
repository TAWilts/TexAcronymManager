from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tacroman.importing import parse_acronym_package, read_tex_file
from tacroman.i18n import translate
from tacroman.model import Acronym, duplicate_matches
from tacroman.profiles import load_profiles
from tacroman.rendering import render
from tacroman.storage import load_database, save_database


class TAcroManTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = {profile["id"]: profile for profile in load_profiles()}

    def test_default_profile_matches_acronym_environment(self) -> None:
        entries = [
            Acronym(short="AOA", long="angle of arrival"),
            Acronym(short="ADC", long="analog to digital converter"),
        ]
        self.assertEqual(
            render(entries, self.profiles["acronym-package"]),
            "\\begin{acronym}\n"
            "\\acro{ADC}{analog to digital converter}\n"
            "\\acro{AOA}{angle of arrival}\n\\end{acronym}\n",
        )

    def test_complete_acronym_profile_matches_user_snippet(self) -> None:
        entries = [Acronym(short="ADC", long="analog to digital converter")]
        self.assertEqual(
            render(entries, self.profiles["acronym-complete-snippet"]),
            "\\usepackage[printonlyused]{acronym}\n\n"
            "\\begin{acronym}\n"
            "\\acro{ADC}{analog to digital converter}\n"
            "\\end{acronym}\n",
        )

    def test_generic_template_and_identifier(self) -> None:
        profile = {
            "entry": "item([[id]]) = [[long]]",
            "header": "BEGIN\n",
            "footer": "\nEND\n",
            "separator": "\n",
            "sort_by": "none",
            "escape_mode": "none",
        }
        self.assertEqual(render([Acronym(short="DVL-2", long="velocity log")], profile), "BEGIN\nitem(dvl_2) = velocity log\nEND\n")

    def test_import_handles_nested_latex_braces(self) -> None:
        source = "\\acro{USBL}{ultra-short baseline}\\n\\acro{AUV}{autonomous \\textit{underwater} vehicle}"
        imported = parse_acronym_package(source)
        self.assertEqual(
            [(item.short, item.long) for item in imported],
            [("USBL", "ultra-short baseline"), ("AUV", "autonomous \\textit{underwater} vehicle")],
        )

    def test_duplicate_matching_checks_short_and_long(self) -> None:
        existing = [Acronym(short="AUV", long="autonomous underwater vehicle")]
        exact, similar = duplicate_matches(Acronym(short="auv", long="other"), existing)
        self.assertEqual(exact[0].short, "AUV")
        self.assertEqual(similar, [])

    def test_duplicate_matching_detects_short_form_before_long_form_is_entered(self) -> None:
        existing = [Acronym(short="AUV", long="autonomous underwater vehicle")]
        exact, similar = duplicate_matches(Acronym(short="AUV", long=""), existing)
        self.assertEqual([entry.short for entry in exact], ["AUV"])
        self.assertEqual(similar, [])

    def test_tex_reader_accepts_utf8_with_bom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "acronyms.tex"
            path.write_bytes("\ufeff\\acro{AUV}{autonomous underwater vehicle}".encode("utf-8"))
            self.assertEqual(read_tex_file(path), "\\acro{AUV}{autonomous underwater vehicle}")

    def test_translation_keeps_latex_braces_literal(self) -> None:
        no_definitions = translate("en", "no_definitions")
        help_text = translate("en", "help_text")
        self.assertIn(r"\acro{…}{…}", no_definitions)
        self.assertIn(r"\acro{[[short]]}{[[long]]}", help_text)

    def test_language_menu_is_translated(self) -> None:
        self.assertEqual(translate("de", "menu_language"), "Sprache")
        self.assertEqual(translate("en", "menu_language"), "Language")

    def test_database_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "acronyms.json"
            original = [Acronym(short="DVL", long="Doppler velocity log")]
            save_database(path, original)
            loaded = load_database(path)
            self.assertEqual(loaded[0].short, "DVL")
            self.assertEqual(loaded[0].long, "Doppler velocity log")


if __name__ == "__main__":
    unittest.main()
