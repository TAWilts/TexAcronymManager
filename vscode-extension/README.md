# TAcroMan for Visual Studio Code

This directory contains the Visual Studio Code extension that belongs to the
same repository as the TAcroMan desktop application. It runs alongside LaTeX
Workshop and uses normal VS Code language APIs; LaTeX Workshop itself is not
modified.

The shared interface is the TAcroMan JSON database (`acronyms.json`). The
Python/Tkinter desktop app remains responsible for maintaining that database,
while the extension reads it for editor assistance.

## Features

### Acronym completion

Completion is offered inside configured LaTeX commands such as `\ac{...}` and
`\acp{...}`. Matching searches across the short form, long form and all other
string fields stored for an entry.

For example, both of these inputs can suggest `AUV`:

```tex
\ac{AUV
\ac{autonomous under
```

Selecting the item inserts only the key, so the surrounding command stays
intact.

### Plain-text completion

TAcroMan can also suggest acronym commands while normal prose is being typed.
Both the short form and the long form are searched. For example:

```tex
This is an AU
This is an autonomous under
```

can both suggest `AUV — autonomous underwater vehicle`. Accepting the
suggestion replaces the text typed so far with:

```tex
\ac{AUV}
```

Plural short/long forms use the configured plural command, e.g. `AUVs` can
become `\acp{AUV}`. Suggestions start after two matching characters and are
not offered in comments, acronym definitions, existing acronym commands, or
configured non-prose arguments such as `\cite{...}` and `\ref{...}`.

If suggestions are not displayed automatically, use VS Code's **Trigger
Suggest** command (`Ctrl+Space`).

### Plain-text diagnostics and Quick Fixes

Known acronyms written directly in prose are marked as a lightweight Hint.
The Quick Fix replaces them with the configured LaTeX command:

```tex
The AUV uses a DVL for navigation.
```

becomes, after applying the fixes:

```tex
The \ac{AUV} uses a \ac{DVL} for navigation.
```

Plural forms use the plural command:

```tex
Two AUVs cooperate.
```

can be changed to:

```tex
Two \acp{AUV} cooperate.
```

An explicit `short_plural` from the TAcroMan database is preferred. If none is
stored, a simple trailing `s` can optionally be inferred.

The scanner deliberately ignores:

- text after an unescaped LaTeX `%` comment marker;
- existing acronym commands such as `\ac{AUV}` and `\acp{AUV}`;
- acronym definition lines such as `\acro{...}` and `\newacronym{...}`;
- the first argument of common non-prose commands such as `\cite`, `\ref`,
  `\label`, `\url`, `\input` and `\include`.

The ignored-command list is configurable.

### Database handling

- Detects `acronyms.json` in the workspace automatically.
- Supports current TAcroMan schema v2 and older raw-list / `{ "acronyms": [] }`
  database formats.
- Merges records with the same key, for example singular `acronym` and plural
  `acroplural` records.
- Reloads after database changes.
- Provides **TAcroMan: Select Database**, **TAcroMan: Reload Database**, and
  **TAcroMan: Open TAcroMan**.

## Development

From this directory:

```bash
npm install
npm test
```

Then open `vscode-extension/` as the VS Code workspace and press **F5**. The
included `.vscode/launch.json` starts an Extension Development Host.

To create a VSIX package:

```bash
npm run package
```

Generated `node_modules/`, `out/` and `*.vsix` files are ignored by Git.

## Settings

### `tacroman.databasePath`

Optional explicit database path. Relative paths are resolved against the
workspace folder. With the usual TAcroMan/Overleaf layout:

```json
{
  "tacroman.databasePath": "metadata/acronyms.json"
}
```

### `tacroman.latexCommands`

Commands that receive acronym completion. Command names are written without a
leading backslash.

### `tacroman.plainTextCompletion`

Enables or disables acronym suggestions while typing short/long forms in normal LaTeX prose. Default: `true`.

### `tacroman.plainTextDiagnostics`

Enables or disables plain-text acronym hints and Quick Fixes. Default: `true`.

### `tacroman.quickFixSingularCommand`

Command used for singular replacements. Default: `ac`.

### `tacroman.quickFixPluralCommand`

Command used for plural replacements. Default: `acp`.

### `tacroman.inferPlainTextPlurals`

If enabled, the scanner also recognizes a simple plural formed by appending
`s` when no explicit `short_plural` exists. Default: `true`.

### `tacroman.ignoredArgumentCommands`

Commands whose first braced argument should not be scanned for plain-text
acronyms.

### `tacroman.executablePath`

Executable used by **TAcroMan: Open TAcroMan**. The default is `tacroman`, which
works when the Python package/Windows executable is available on `PATH`.

### `tacroman.launchArguments`

Optional arguments inserted before `--database <path>` when launching the
desktop application.
