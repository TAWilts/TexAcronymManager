"""Small, dependency-free user-interface translation helpers."""

from __future__ import annotations

from collections.abc import Mapping
import re


DEFAULT_LANGUAGE = "de"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("de", "en")


def normalize_language(value: str | None) -> str:
    """Return a supported language code, falling back to German."""
    return value if value in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


_MESSAGES: dict[str, Mapping[str, str]] = {
    "app_title": {
        "de": "TAcroMan – TeX Acronym Manager",
        "en": "TAcroMan – TeX Acronym Manager",
    },
    "tab_acronyms": {"de": "Akronyme", "en": "Acronyms"},
    "tab_language": {"de": "Sprache", "en": "Language"},
    "language_heading": {"de": "Sprache der Benutzeroberfläche", "en": "Interface language"},
    "language_description": {
        "de": "Wähle die Sprache für Menüs, Hinweise und Dialoge. Die Einstellung wird für diese Datenbank gespeichert.",
        "en": "Choose the language for menus, validation feedback, and dialogs. The setting is saved for this database.",
    },
    "language_changed": {"de": "Sprache wurde auf Deutsch umgestellt.", "en": "Language changed to English."},
    "menu_file": {"de": "Datei", "en": "File"},
    "menu_open_database": {"de": "Datenbank öffnen…", "en": "Open database…"},
    "menu_new_database": {"de": "Neue Datenbank…", "en": "New database…"},
    "menu_import_tex": {"de": "TeX-Datei importieren…", "en": "Import TeX file…"},
    "menu_write_output": {"de": "Ausgabedatei schreiben", "en": "Write output file"},
    "menu_exit": {"de": "Beenden", "en": "Exit"},
    "menu_profiles": {"de": "Ausgabeprofile", "en": "Output profiles"},
    "menu_edit_profile": {"de": "Aktives Format bearbeiten…", "en": "Edit active format…"},
    "menu_select_profile_file": {"de": "Profildatei auswählen…", "en": "Choose profile file…"},
    "menu_help": {"de": "Hilfe", "en": "Help"},
    "menu_about": {"de": "Über TAcroMan", "en": "About TAcroMan"},
    "database_label": {"de": "Datenbank (JSON):", "en": "Database (JSON):"},
    "open": {"de": "Öffnen…", "en": "Open…"},
    "new": {"de": "Neu…", "en": "New…"},
    "output_label": {"de": "Generierte Datei:", "en": "Generated file:"},
    "target": {"de": "Ziel…", "en": "Target…"},
    "write_now": {"de": "Jetzt schreiben", "en": "Write now"},
    "output_format": {"de": "Ausgabeformat:", "en": "Output format:"},
    "edit_format": {"de": "Format bearbeiten…", "en": "Edit format…"},
    "edit_acronym": {"de": "Akronym bearbeiten", "en": "Edit acronym"},
    "search": {"de": "Suchen:", "en": "Search:"},
    "short": {"de": "Kürzel", "en": "Short form"},
    "long": {"de": "Langform", "en": "Long form"},
    "category": {"de": "Kategorie", "en": "Category"},
    "new_entry": {"de": "Neu", "en": "New"},
    "delete": {"de": "Löschen", "en": "Delete"},
    "preview": {"de": "Vorschau", "en": "Preview"},
    "select_to_edit": {"de": "Auswahl zum Bearbeiten", "en": "Select an entry to edit"},
    "short_required": {"de": "Kürzel *", "en": "Short form *"},
    "long_required": {"de": "Langform *", "en": "Long form *"},
    "category_optional": {"de": "Kategorie (optional)", "en": "Category (optional)"},
    "note_optional": {
        "de": "Notiz (optional, wird nur von passenden Profilen ausgegeben)",
        "en": "Note (optional; rendered only by profiles that use it)",
    },
    "add_acronym": {"de": "Akronym hinzufügen", "en": "Add acronym"},
    "save_changes": {"de": "Änderungen speichern", "en": "Save changes"},
    "clear": {"de": "Leeren", "en": "Clear"},
    "copy_usage": {"de": "LaTeX-Aufruf kopieren", "en": "Copy LaTeX command"},
    "ready": {"de": "Bereit für ein neues Akronym.", "en": "Ready for a new acronym."},
    "format_valid": {"de": "Formatprüfung: in Ordnung.", "en": "Format check: looks good."},
    "entries_loaded": {"de": "{count} Einträge geladen.", "en": "Loaded {count} entries."},
    "duplicate_live": {"de": "Existiert bereits: {entries}", "en": "Already exists: {entries}"},
    "similar_live": {"de": "Ähnliche Einträge: {entries}", "en": "Similar entries: {entries}"},
    "duplicate_error": {
        "de": "Dieses Kürzel oder diese Langform existiert bereits:\n\n{entries}",
        "en": "This short form or long form already exists:\n\n{entries}",
    },
    "similar_confirm": {
        "de": "Möglicherweise ähnliche Einträge gefunden:\n\n{entries}\n\nTrotzdem speichern?",
        "en": "Potentially similar entries were found:\n\n{entries}\n\nSave anyway?",
    },
    "format_confirm": {
        "de": "Format-Hinweis:\n\n{warnings}\n\nTrotzdem speichern?",
        "en": "Formatting note:\n\n{warnings}\n\nSave anyway?",
    },
    "entry_added": {"de": "Akronym hinzugefügt. Du kannst direkt das nächste eingeben.", "en": "Acronym added. You can enter the next one right away."},
    "entry_updated": {"de": "Akronym aktualisiert. Du kannst direkt das nächste eingeben.", "en": "Acronym updated. You can enter the next one right away."},
    "select_entry_first": {"de": "Bitte zuerst einen Eintrag auswählen.", "en": "Please select an entry first."},
    "confirm_delete": {"de": "{short} wirklich löschen?", "en": "Delete {short}?"},
    "file_write_failed": {"de": "Datei konnte nicht geschrieben werden:\n{error}", "en": "The file could not be written:\n{error}"},
    "profile_warning": {"de": "Profil prüfen:\n\n{warnings}", "en": "Check profile:\n\n{warnings}"},
    "output_written": {"de": "{count} Einträge geschrieben:\n{path}", "en": "Wrote {count} entries:\n{path}"},
    "output_status_written": {"de": "Geschrieben: {path}", "en": "Written: {path}"},
    "output_failed": {"de": "Schreiben fehlgeschlagen.", "en": "Writing failed."},
    "open_database_title": {"de": "Akronymdatenbank öffnen", "en": "Open acronym database"},
    "new_database_title": {"de": "Neue Akronymdatenbank anlegen", "en": "Create acronym database"},
    "new_database_status": {"de": "Neue Datenbank angelegt: {path}", "en": "Created new database: {path}"},
    "database_create_failed": {"de": "Datenbank konnte nicht angelegt werden:\n{error}", "en": "The database could not be created:\n{error}"},
    "choose_output_title": {"de": "Generierte Ausgabe speichern als", "en": "Save generated output as"},
    "choose_profiles_title": {"de": "Zusätzliche Ausgabeprofile laden", "en": "Load additional output profiles"},
    "import_tex_title": {"de": "TeX-Datei importieren", "en": "Import TeX file"},
    "file_read_failed": {"de": "Datei konnte nicht gelesen werden:\n{error}", "en": "The file could not be read:\n{error}"},
    "no_definitions": {"de": "Keine \\acro{…}{…}-Definitionen gefunden.", "en": "No \\acro{…}{…} definitions were found."},
    "import_choice": {
        "de": "{count} Definitionen gefunden.\n\nJa: vorhandene Datenbank ersetzen\nNein: nur neue Kürzel ergänzen\nAbbrechen: nichts ändern",
        "en": "Found {count} definitions.\n\nYes: replace the current database\nNo: add only new short forms\nCancel: make no changes",
    },
    "imported": {"de": "{count} Definitionen importiert.", "en": "Imported {count} definitions."},
    "no_acronym": {"de": "Bitte zuerst ein Akronym eingeben oder auswählen.", "en": "Please enter or select an acronym first."},
    "no_usage": {"de": "Das aktive Profil hat keinen LaTeX-Aufruf definiert.", "en": "The active profile does not define a LaTeX command."},
    "copied_usage": {"de": "In die Zwischenablage kopiert: {command}", "en": "Copied to clipboard: {command}"},
    "preview_title": {"de": "Vorschau – {name}", "en": "Preview – {name}"},
    "help_text": {
        "de": "Das Standardprofil erzeugt exakt eine acronym-Umgebung:\n"
        "\\begin{acronym} … \\acro{ADC}{analog to digital converter} … \\end{acronym}\n\n"
        "Über Ausgabeprofile kannst du weitere Formate bearbeiten oder kopieren.\n\n"
        "Erlaubte Platzhalter in Vorlagen:\n"
        "[[short]]  Kürzel\n[[long]]   Langform\n[[id]]     automatisch abgeleiteter Schlüssel\n"
        "[[category]] und [[note]]\n\n"
        "LaTeX-Klammern bleiben in den Vorlagen unverändert. Beispiel:\n"
        "\\acro{[[short]]}{[[long]]}",
        "en": "The default profile produces a standard acronym environment:\n"
        "\\begin{acronym} … \\acro{ADC}{analog to digital converter} … \\end{acronym}\n\n"
        "Use Output profiles to edit or copy other formats.\n\n"
        "Allowed template placeholders:\n"
        "[[short]]  short form\n[[long]]   long form\n[[id]]     generated identifier\n"
        "[[category]] and [[note]]\n\n"
        "LaTeX braces remain unchanged in templates. Example:\n"
        "\\acro{[[short]]}{[[long]]}",
    },
    "about_text": {
        "de": "TAcroMan verwaltet LaTeX-Akronyme aus einer JSON-Datenbank und erzeugt konfigurierbare Ausgabedateien.\n\nProjekt: https://github.com/TAWilts/TexAcronymManager",
        "en": "TAcroMan manages LaTeX acronyms from a JSON database and writes configurable output files.\n\nProject: https://github.com/TAWilts/TexAcronymManager",
    },
    "json_files": {"de": "JSON-Dateien", "en": "JSON files"},
    "tex_files": {"de": "TeX-Dateien", "en": "TeX files"},
    "csv_files": {"de": "CSV-Dateien", "en": "CSV files"},
    "all_files": {"de": "Alle Dateien", "en": "All files"},
    "profile_editor_title": {"de": "Ausgabeformat bearbeiten", "en": "Edit output format"},
    "profile": {"de": "Profil:", "en": "Profile:"},
    "copy_as_new_profile": {"de": "Als neues Profil kopieren", "en": "Copy as new profile"},
    "description": {"de": "Beschreibung:", "en": "Description:"},
    "preamble_hint": {"de": "Präambel-Hinweis:", "en": "Preamble hint:"},
    "sort": {"de": "Sortierung:", "en": "Sort order:"},
    "escaping": {"de": "Maskierung:", "en": "Escaping:"},
    "templates": {"de": "Vorlagen – Platzhalter: [[short]], [[long]], [[id]], [[category]], [[note]]", "en": "Templates – placeholders: [[short]], [[long]], [[id]], [[category]], [[note]]"},
    "profile_file": {"de": "Profildatei: {path}", "en": "Profile file: {path}"},
    "save": {"de": "Speichern", "en": "Save"},
    "close": {"de": "Schließen", "en": "Close"},
    "new_profile_title": {"de": "Neues Profil", "en": "New profile"},
    "new_profile_prompt": {"de": "ID für das neue Profil (z. B. my-format):", "en": "ID for the new profile (for example, my-format):"},
    "profile_id_exists": {"de": "Diese Profil-ID existiert bereits.", "en": "This profile ID already exists."},
    "profile_copy_name": {"de": "Kopie von {name}", "en": "Copy of {name}"},
    "profile_required": {"de": "ID, Name und entry sind erforderlich.", "en": "ID, name, and entry are required."},
    "profile_confirm": {
        "de": "Profil-Hinweise:\n\n{warnings}\n\nTrotzdem speichern?",
        "en": "Profile notes:\n\n{warnings}\n\nSave anyway?",
    },
    "profile_save_failed": {"de": "Profildatei konnte nicht gespeichert werden:\n{error}", "en": "The profile file could not be saved:\n{error}"},
    "profile_saved": {"de": "Ausgabeprofil gespeichert.", "en": "Output profile saved."},
    "error_enter_short": {"de": "Bitte ein Kürzel eingeben.", "en": "Enter a short form."},
    "error_enter_long": {"de": "Bitte eine Langform eingeben.", "en": "Enter a long form."},
    "error_short_linebreak": {"de": "Ein Kürzel darf keinen Zeilenumbruch enthalten.", "en": "A short form may not contain a line break."},
    "error_long_linebreak": {"de": "Die Langform darf keinen Zeilenumbruch enthalten.", "en": "A long form may not contain a line break."},
    "warning_short_whitespace": {"de": "Das Kürzel enthält Leerzeichen. Das ist erlaubt, aber ungewöhnlich.", "en": "The short form contains whitespace. This is allowed but unusual."},
    "warning_long_punctuation": {"de": "Die Langform endet mit Satzzeichen. In Akronymverzeichnissen wird dies meist weggelassen.", "en": "The long form ends with punctuation. This is usually omitted in acronym lists."},
    "warning_trimmed": {"de": "Führende oder nachgestellte Leerzeichen werden beim Speichern entfernt.", "en": "Leading or trailing whitespace is removed when saving."},
    "warning_short_braces": {"de": "Das Kürzel enthält geschweifte Klammern. Prüfe die erzeugte LaTeX-Ausgabe besonders sorgfältig.", "en": "The short form contains braces. Check the generated LaTeX output carefully."},
    "database_invalid_json": {"de": "Die Datenbank ist kein gültiges JSON: {error}", "en": "The database is not valid JSON: {error}"},
    "database_invalid_shape": {"de": "Die Datenbank muss ein Objekt mit dem Feld 'acronyms' enthalten.", "en": "The database must be an object with an 'acronyms' field."},
    "database_invalid_entry": {"de": "Jeder Datenbankeintrag muss ein JSON-Objekt sein.", "en": "Every database entry must be a JSON object."},
    "profile_missing_id": {"de": "Ein Ausgabeprofil braucht eine ID.", "en": "An output profile needs an ID."},
    "profile_invalid_id": {"de": "Profil-IDs dürfen nur Buchstaben, Zahlen, Punkt, Unterstrich und Bindestrich enthalten.", "en": "Profile IDs may contain only letters, numbers, dots, underscores, and hyphens."},
    "profile_missing_name": {"de": "Das Profil '{id}' braucht einen Namen.", "en": "Profile '{id}' needs a name."},
    "profile_missing_entry": {"de": "Das Profil '{id}' braucht eine Eintragsvorlage.", "en": "Profile '{id}' needs an entry template."},
    "profile_invalid_sort": {"de": "sort_by muss short, long, identifier, category oder none sein.", "en": "sort_by must be short, long, identifier, category, or none."},
    "profile_invalid_escape": {"de": "escape_mode muss none, latex oder csv sein.", "en": "escape_mode must be none, latex, or csv."},
    "profile_invalid_json": {"de": "Die Profildatei ist kein gültiges JSON: {error}", "en": "The profile file is not valid JSON: {error}"},
    "profile_invalid_shape": {"de": "Die Profildatei muss eine JSON-Liste sein.", "en": "The profile file must be a JSON list."},
    "profile_unknown_tokens": {"de": "Unbekannte Platzhalter in {field}: {tokens}", "en": "Unknown placeholders in {field}: {tokens}"},
    "profile_missing_short": {"de": "Die Eintragsvorlage enthält weder [[short]] noch [[id]].", "en": "The entry template contains neither [[short]] nor [[id]]."},
}

_INTERPOLATION_FIELD = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def translate(language: str, key: str, /, **values: object) -> str:
    """Return a translated UI string and interpolate named values."""
    message = _MESSAGES.get(key)
    if message is None:
        return key
    template = message.get(normalize_language(language), message["en"])
    return _INTERPOLATION_FIELD.sub(
        lambda match: str(values.get(match.group(1), match.group(0))),
        template,
    )
