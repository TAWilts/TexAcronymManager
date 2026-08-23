# TAcroMan for Visual Studio Code

**Write LaTeX without manually managing every acronym command.**

TAcroMan adds acronym-aware IntelliSense, plain-text detection, interactive
replacement, and direct access to the TAcroMan acronym database while you write.
It works alongside LaTeX Workshop and uses normal Visual Studio Code extension
APIs — LaTeX Workshop itself is not modified.

<!--
Add the demo GIF as:
  vscode-extension/assets/tacroman-demo.gif

Then rerun apply_tacroman_marketplace_prep.py to insert it here automatically.
-->

## Highlights

### 1. Complete acronym commands

Start typing inside a configured acronym command:

```tex
\ac{AU
```

TAcroMan searches the active database and suggests matching entries such as:

```tex
\ac{AUV}
```

Matching uses the acronym key, short form, long form, and other searchable
database fields.

### 2. Turn a plain acronym into LaTeX

Type a known short form directly in prose:

```tex
The AUV navigates autonomously.
```

TAcroMan can suggest and replace it with:

```tex
The \ac{AUV} navigates autonomously.
```

Plural forms can use the configured plural command, for example:

```tex
AUVs  ->  \acp{AUV}
```

### 3. Search by the long form

You do not need to remember the acronym key. Start typing the expansion:

```tex
autonomous under...
```

and TAcroMan can suggest:

```tex
\ac{AUV}
```

This also works through standard VS Code IntelliSense (`Ctrl+Space`).

### 4. Manage acronyms without leaving VS Code

The dedicated TAcroMan view in the Secondary Side Bar shows the active database
and its acronym entries.

From the same view you can:

- search the acronym database;
- reload or select a database;
- insert singular or plural acronym commands;
- launch the TAcroMan desktop application;
- add, edit, or delete acronym entries in the desktop manager.

The extension uses the database currently selected by the desktop application
by default. An explicit `tacroman.databasePath` remains available as an override.

### 5. Check the current file for acronyms

**TAcroMan: Check Current File for Acronyms** scans the active LaTeX document for
known short and long forms.

Each occurrence is reviewed individually, so you can choose whether to replace
it, skip it, or stop the scan. This is useful when integrating older text,
papers, or manually written sections into a consistent acronym workflow.

The scanner avoids common non-prose contexts including existing acronym
commands, comments, definitions, citations, references, labels, and verbatim
content.

### Live database updates

Changes to the active `acronyms.json` are watched automatically. When TAcroMan
saves the database, completions and the acronym browser update without requiring
a manual reload.

## Example workflow

```tex
The autonomous underwater vehicle communicates with two AUVs.
```

TAcroMan can help turn this into:

```tex
The \ac{AUV} communicates with two \acp{AUV}.
```

without requiring you to remember the acronym key first.

## Getting started

1. Install the extension from the Visual Studio Marketplace.
2. Open a LaTeX project.
3. Open the **TAcroMan** view in the Secondary Side Bar.
4. Select an existing `acronyms.json`, or launch the TAcroMan desktop application
   and manage the database there.
5. Start typing `\ac{...}`, a known short form, or a known long form.

TAcroMan is designed to work alongside **LaTeX Workshop**. LaTeX Workshop is not
a required internal dependency and is not modified by this extension.

## Database integration

The desktop application and VS Code extension share the TAcroMan JSON database.

Database resolution follows this order:

1. explicit VS Code setting `tacroman.databasePath`;
2. database currently selected in the TAcroMan desktop application;
3. previously selected/workspace database;
4. workspace discovery.

The selected JSON file is watched for changes, including when it lives outside
the current VS Code workspace.

## Commands

| Command | Purpose |
| --- | --- |
| `TAcroMan: Check Current File for Acronyms` | Interactively review known acronym occurrences |
| `TAcroMan: Open TAcroMan` | Launch the desktop acronym manager |
| `TAcroMan: Select Database` | Choose the JSON database |
| `TAcroMan: Reload Database` | Force a database reload |
| `TAcroMan: Insert \ac{...}` | Insert the selected acronym |
| `TAcroMan: Insert \acp{...}` | Insert the selected acronym in plural form |

## Settings

<details>
<summary><strong>Show extension settings</strong></summary>

### `tacroman.databasePath`

Optional explicit path to the TAcroMan JSON database. When empty, the extension
uses the database published by the desktop TAcroMan application and then falls
back to workspace discovery.

### `tacroman.latexCommands`

LaTeX commands for which completion should be offered inside the first braced
argument.

### `tacroman.plainTextCompletion`

Offer completions while typing known short or long forms directly in LaTeX
prose.

### `tacroman.plainTextDiagnostics`

Detect known acronyms written as plain text and offer Quick Fixes.

### `tacroman.quickFixSingularCommand`

Command used for singular replacements. Default: `ac`.

### `tacroman.quickFixPluralCommand`

Command used for plural replacements. Default: `acp`.

### `tacroman.inferPlainTextPlurals`

Recognize simple plural forms when an explicit plural is not stored.

### `tacroman.ignoredArgumentCommands`

Commands whose first braced argument should not be scanned as prose.

### `tacroman.executablePath`

Optional explicit desktop executable. Leave empty to use the launcher published
by TAcroMan automatically.

### `tacroman.launchArguments`

Additional arguments passed when launching the desktop application.

</details>

## Desktop application

The VS Code extension is part of the same repository as the TAcroMan desktop
application:

https://github.com/TAWilts/TexAcronymManager

The desktop application provides the full database editor and LaTeX output
generation workflow. The extension focuses on using that database efficiently
while writing.

## Feedback and issues

Bug reports, feature requests, and reproducible examples are welcome:

https://github.com/TAWilts/TexAcronymManager/issues

## Development

From the repository root on Windows:

```powershell
.\build-vscode-extension.cmd
```

The build script installs Node dependencies, runs the extension tests, and
creates the VSIX package.

From `vscode-extension/` directly:

```bash
npm install
npm test
npm run package
```

## License

MIT
