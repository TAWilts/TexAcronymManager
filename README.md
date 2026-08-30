# TAcroMan

TAcroMan is a desktop application and VS Code extension for maintaining
profile-defined LaTeX command entries. Both frontends use the same web
interface, JSON database, profiles, and generated output. TAcroMan started as a
TeX acronym manager; the name remains, but the data model no longer hard-codes
an acronym package or any relationship between commands.

<img width="610" height="404" alt="Screenshot 2026-08-08 102512" src="https://github.com/user-attachments/assets/adc97f9e-85b3-4c49-b395-5175b0a8d51d" />


The JSON database is the source of truth. A selected JSON profile defines
independent command types, their fields, comparison rules, and the generated
TeX output. The project is available at
[TAWilts/TexAcronymManager](https://github.com/TAWilts/TexAcronymManager).

The Web desktop menu exposes the complete former menu structure. Database
creation, TeX import, output, profile-file, language, and help actions run in
the Web application. Profile editing, citation-key migration, and reference
auditing currently open directly as targeted classic tool windows. The full
former Tkinter interface remains available as `tacroman-tk` during this final
dialog migration.

## Development transparency

TAcroMan was developed in an iterative collaboration with **ChatGPT 5.6 Terra
Max** by OpenAI. ChatGPT substantially drafted the application code, tests, and
documentation. The repository owner directs the project and remains responsible
for reviewing, maintaining, and releasing the software.

## Features

- Generic, profile-defined command types rendered as editor tabs.
- Fields generated directly from each command definition.
- Live duplicate handling: same comparison key in the **same command type** is
  a blocking error; the same key in a **different command type** is a
  non-blocking warning.
- No hard-coded parent, primary, supplement, or package semantics.
- Optional similarity hints, search, required-field checks, and configurable
  field warnings.
- Atomic JSON/output writes suitable for Dropbox/Overleaf synchronization.
- Import of existing \acro{SHORT}{long form} definitions.
- Built-in profiles for acronym, acro, glossaries-extra, and CSV.

## Command-definition profiles

Each profile contains a "commands" list. Its items are fully independent
command types. This is a shortened example from the built-in
"acronym-package" profile:

~~~json
{
  "id": "acronym-package",
  "header": "\\begin{acronym}\n",
  "footer": "\n\\end{acronym}\n",
  "separator": "\n",
  "commands": [
    {
      "id": "acronym",
      "label": "Acronym",
      "template": "\\acro{[[short]]}{[[long]]}",
      "usage_template": "\\ac{[[short]]}",
      "fields": [
        {
          "id": "short",
          "label": "Short form",
          "required": true,
          "comparison_group": "acronym-key"
        },
        {
          "id": "long",
          "label": "Long form",
          "required": true,
          "similarity_group": "long-form"
        }
      ]
    },
    {
      "id": "acroplural",
      "label": "Plural definition",
      "template": "\\acroplural{[[key]]}[[short_plural]]{[[long_plural]]}",
      "fields": [
        {
          "id": "key",
          "label": "Acronym key",
          "required": true,
          "comparison_group": "acronym-key"
        },
        {
          "id": "short_plural",
          "label": "Short plural",
          "output_template": "[[[value]]]"
        },
        {
          "id": "long_plural",
          "label": "Long plural",
          "required": true
        }
      ]
    }
  ]
}
~~~

The "acronym" and "acroplural" command IDs above are only profile data.
Entering AUV as "short" for an "acronym" entry and as "key" for an
"acroplural" entry produces a warning because both fields share
"comparison_group": "acronym-key"; both entries may still be saved. A second
"acronym" entry with the same "short" value is blocked.

### Field options

| Property | Meaning |
| --- | --- |
| id | Required machine-readable field ID, used as a placeholder. |
| label | Text shown beside the field. |
| required | Blocks saving when the field is empty. |
| multiline | Renders a multi-line text field and permits line breaks. |
| comparison_group | Enables exact duplicate checks with matching groups. |
| similarity_group | Enables non-blocking similarity hints with matching groups. |
| case_sensitive | Uses case-sensitive comparison for this field. |
| output_template | Wraps a non-empty value; it must include [[value]]. |

Templates may use every field ID declared by their own command, plus [[id]]
(a generated identifier unless an id field is present) and [[command]]. An
optional short plural with output template "[[[value]]]" renders as [AUVs];
when empty, it renders as nothing.

Use **Profiles → Edit active profile… → Command schema** to edit these JSON
definitions or clone a built-in profile before customizing it.

## Backward compatibility

TAcroMan 0.3 loads all databases created by 0.1/0.2:

~~~json
{
  "schema_version": 1,
  "acronyms": [
    {"short": "AUV", "long": "autonomous underwater vehicle"}
  ]
}
~~~

On the next save it migrates them to the generic v2 structure:

~~~json
{
  "schema_version": 2,
  "entries": [
    {
      "command_id": "acronym",
      "values": {
        "short": "AUV",
        "long": "autonomous underwater vehicle"
      }
    }
  ]
}
~~~

Legacy render-profile files with a single top-level "entry" template are also
loaded automatically as a profile containing one generic "acronym" command.

Generic exporting is profile-driven. TeX importing is deliberately narrower:
the built-in importer currently understands the established
\acro{SHORT}{long form} syntax only. Other command formats can still be
created and edited through the generic database/UI, while their import parsers
can be added separately when needed.

## Use with the acronym package

For a typical Overleaf project, create the database and output file in the
synchronized project folder:

~~~text
metadata/
├── acronyms.json     # maintained by TAcroMan
└── acronyms.tex      # generated by TAcroMan
~~~

Keep the package line in the preamble:

~~~tex
\usepackage[printonlyused]{acronym}
~~~

Then place the generated environment where the acronym list should appear:

~~~tex
\input{metadata/acronyms}
~~~

For the first migration, select **File → Import TeX file…** and choose either
the existing acronym file or the main .tex file containing the definitions.

## Start

Requirements: Python 3.10 or later. The installation pulls in pywebview; on
Windows its Chromium renderer uses the Microsoft Edge WebView2 Runtime.

On Windows, extract the ZIP archive and double-click start_windows.bat.
Alternatively, run:

~~~bash
python run.py
~~~

To install the project in editable mode during development:

~~~bash
python -m pip install -e .
tacroman --database /path/to/entries.json --output /path/to/commands.tex
~~~

To open the legacy Tkinter interface during the remaining migration:

~~~bash
tacroman-tk --database /path/to/entries.json --output /path/to/commands.tex
~~~

## Tests

~~~bash
python -m unittest discover -s tests -v
~~~

## Project layout

~~~text
src/tacroman/
  web_app.py      Native pywebview host for the shared frontend
  app.py          Legacy Tkinter UI during feature migration
  i18n.py         German and English user-interface texts
  importing.py    Targeted TeX import helpers
  model.py        Generic entries, validation, and comparison logic
  profiles.py     Profile-schema loading and migration
  rendering.py    Profile-based output generation
  storage.py      Atomic JSON and text persistence
  vscode_integration.py  Shared state in ~/TAcroMan/state.json
  web_ui/         Host-independent Webview frontend assets
~~~

## Visual Studio Code extension

The repository also contains an experimental editor integration in
`vscode-extension/`. It is a separate TypeScript package but deliberately lives
in the same Git repository as the Python desktop application, so releases and
schema changes can be maintained together.

The extension reads the same `acronyms.json` database and provides:

- completion inside LaTeX acronym commands such as `\ac{...}` and `\acp{...}`;
- lookup by short form and long form;
- lightweight diagnostics for known acronyms written as plain text;
- Quick Fixes such as `AUV` -> `\ac{AUV}` and `AUVs` -> `\acp{AUV}`;
- an integrated manager for adding, editing, deleting, and filtering entries;
- commands for database/output selection, live reload, and optionally launching
  the separate desktop application.

The desktop app and extension use `~/TAcroMan/state.json` as their single
authoritative source for shared paths and frontend state. They do not import
paths from older application files, VS Code settings, or workspace discovery.
On a genuine first run, both frontends use `~/TAcroMan/entries.json`; generated
`entries.tex` defaults to the current VS Code project folder and stays up to
date whenever the JSON database changes.

**Open TAcroMan** opens the integrated Webview manager and therefore works
without a desktop installation. The desktop command launches the same shared
interface in a native pywebview window. Its restored menu opens the remaining
profile and bibliography dialogs directly as classic tool windows. The full
Tkinter application remains available as `tacroman-tk` during their migration.

It runs alongside LaTeX Workshop and does not patch or depend on LaTeX
Workshop internals. For development and packaging instructions, see
`vscode-extension/README.md`.

## Linux

TAcroMan uses pywebview with GTK/WebKit2GTK on Linux. A source
installation can be prepared with:

```bash
bash install-linux.sh
bash run-tacroman.sh
```

On Debian/Ubuntu the native dependencies are `python3-gi`, `python3-gi-cairo`,
`gir1.2-gtk-3.0`, and `gir1.2-webkit2-4.1`. The VS Code bridge uses
`~/TAcroMan/state.json` and detects the `tacroman` launcher inside a virtual
environment. The legacy Tkinter command additionally needs `python3-tk`.
