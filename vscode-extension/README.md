<p align="center">
  <img src="https://raw.githubusercontent.com/TAWilts/TexAcronymManager/main/vscode-extension/assets/icon.png"
       width="128"
       alt="TAcroMan logo">
</p>

<h1 align="center">TAcroMan</h1>

<p align="center">
  <strong>Smart acronym support for LaTeX in Visual Studio Code.</strong><br>
  Write first — let TAcroMan take care of the acronym commands.
</p>

<p align="center">
  <a href="https://github.com/TAWilts/TexAcronymManager">GitHub</a>
  ·
  <a href="https://github.com/TAWilts/TexAcronymManager/issues">Report an issue</a>
</p>

---

The Tex Acronym Manager (TAcroMan) helps you use acronyms consistently while writing LaTeX documents.

Instead of repeatedly looking up acronym keys or manually replacing plain text,
TAcroMan connects your acronym database directly to Visual Studio Code and provides:

- acronym-aware completion for commands such as `\ac{...}`;
- suggestions for acronyms written as plain text;
- lookup by both **short form** and **long form**;
- an integrated acronym browser in the VS Code sidebar;
- interactive scanning and replacement of acronyms in existing text;
- live synchronization when the acronym database changes.

Use **Ctrl+Space** (`Ctrl+Whitespace`) to see the suggested acronyms.

It is especially useful for theses, dissertations, papers, reports, and other
large LaTeX projects with many acronyms.

<p align="center">
  <img src="https://raw.githubusercontent.com/TAWilts/TexAcronymManager/main/vscode-extension/assets/tacroman-demo.gif"
       alt="TAcroMan feature demonstration">
</p>

## ✨ Features

### 1. Complete `\ac{...}` commands

Start typing an acronym command:

```tex
\ac{AU
```
Then press **Ctrl+Space** (`Ctrl+Whitespace`)(as it always will be...).
TAcroMan searches the active database and suggests matching acronyms:

```tex
\ac{AUV}
```

The suggestion shows the acronym together with its long form, so you can choose
the right entry without leaving the editor.

---

### 2. Convert plain acronyms to LaTeX commands

If you type an acronym directly in your text:

```tex
The AUV performs the mission autonomously.
```

TAcroMan can suggest:

```tex
The \ac{AUV} performs the mission autonomously.
```

Plural forms are supported as well:

```tex
Several AUVs were deployed.
```

can become:

```tex
Several \acp{AUV} were deployed.
```

The singular and plural commands are configurable.

---

### 3. Search by long form

Forgot the acronym itself?

Just start typing the long form:

```text
autonomous underwater...
```

TAcroMan can still find:

```tex
\ac{AUV}
```

This works through normal VS Code IntelliSense and lets you search the acronym
database by both abbreviation and meaning.

---

### 4. Manage acronyms directly from VS Code

TAcroMan adds its own view to the **Secondary Side Bar**.

There you can:

- browse all acronyms in the active database;
- search and filter the acronym list;
- see short and long forms at a glance;
- insert `\ac{...}` or `\acp{...}`;
- select or reload the active database;
- open the integrated editor to add, edit, or delete entries.

The optional desktop application can still be launched through
**TAcroMan: Open Desktop Application**.

Changes to the database are detected automatically — there is normally no need
to reload the extension manually.

---

### 5. Check an existing file for acronyms

Already have a chapter, paper, or older LaTeX file containing plain acronyms?

Use:

**TAcroMan: Check Current File for Acronyms**

TAcroMan scans the active `.tex` file for known short and long forms.

For every occurrence, you decide individually whether it should be replaced.

Example:

```tex
The autonomous underwater vehicle uses a DVL.
```

TAcroMan may suggest:

```tex
The \ac{AUV} uses a \ac{DVL}.
```

For each match you can:

- **Replace**
- **Skip**
- **Stop checking**

The scanner avoids common non-text contexts such as existing acronym commands,
comments, citations, references, labels, acronym definitions, and verbatim
content.

---

## 🚀 Getting started

### 1. Install the extension

Install **TAcroMan** from the Visual Studio Code Extensions view.

---

### 2. Create or select an acronym database

On first use, TAcroMan creates `~/TAcroMan/entries.json` and keeps the shared
UI/extension state in `~/TAcroMan/state.json`. This state file is the only
source used for remembered paths; older integration files, obsolete VS Code
path settings, and workspace database discovery are deliberately ignored.

1. Open the Command Palette with `Ctrl+Shift+P` and run
   **TAcroMan: Open TAcroMan** or click **Open TAcroMan** in the sidebar.
2. Create your first acronym entry in the integrated TAcroMan editor and save it.

The extension reloads automatically. The generated `entries.tex` defaults to
the current VS Code project folder and is updated after every database change.

**Using an existing database**

Run **TAcroMan: Select Database** from the Command Palette or use
**Select database** in the integrated editor. The separately installed desktop
application remains available through **TAcroMan: Open Desktop Application**.

### Working with multiple authors

The `acronyms.json` file is the shared source of truth for the acronym
database. If several authors work on the same project, keep this file
synchronized between their computers using a suitable method:

- **Git** is recommended. Commit and push changes to `acronyms.json`, and pull
  the latest version before editing it.
- A cloud-synchronized folder can also be used, but simultaneous edits or
  synchronization conflicts may overwrite changes. Use this option with care
  and avoid editing the database concurrently on multiple computers.

After synchronizing the file, point TAcroMan to the local copy. In the VS Code
extension, use **TAcroMan: Select Database**. In the desktop application, select the corresponding
database path in the upper-right corner or use the database-selection command.
Once the path is set, all authors can use the same acronym database.

---

### 3. Start writing

Try any of the following:

```tex
\ac{
```

```text
AUV
```

```text
autonomous underwater
```

or open the TAcroMan sidebar and browse the database directly.

---

## 🔄 Live database synchronization

The active JSON database and the shared `~/TAcroMan/state.json` file are watched automatically.

When an acronym is added, edited, or deleted in either frontend (or directly in
the JSON file), the other frontend updates automatically and regenerates the
selected output file.

This also works when the database is located outside the current VS Code
workspace.

---

## 🧭 TAcroMan sidebar

The sidebar provides quick access to the most common actions:

- **Check current file for acronyms**
- **Open TAcroMan**
- view the active database
- search/filter acronyms
- reload the database
- select another database
- insert singular or plural acronym commands

Right-click an acronym to insert it directly into the active LaTeX document.

---

## ⌨️ Commands

Open the Command Palette with `Ctrl+Shift+P` and search for **TAcroMan**.

| Command | Description |
| --- | --- |
| **TAcroMan: Check Current File for Acronyms** | Scan the active `.tex` file and review replacements interactively |
| **TAcroMan: Open TAcroMan** | Open the integrated acronym manager |
| **TAcroMan: Open Desktop Application** | Open the optional Python desktop application |
| **TAcroMan: Select Database** | Select an `acronyms.json` database |
| **TAcroMan: Reload Database** | Force the current database to reload |
| **TAcroMan: Insert `\ac{...}`** | Insert the selected acronym in singular form |
| **TAcroMan: Insert `\acp{...}`** | Insert the selected acronym in plural form |

---

## ⚙️ Configuration

For most users, the default settings should work without modification.

<details>
<summary><strong>Show advanced settings</strong></summary>

### `tacroman.latexCommands`

Defines the LaTeX commands for which acronym completion is enabled.

For example:

```json
[
  "ac",
  "acp"
]
```

---

### `tacroman.plainTextCompletion`

Enable suggestions while typing acronym short forms or long forms directly in
normal LaTeX text.

---

### `tacroman.plainTextDiagnostics`

Detect known acronyms written as plain text and offer Quick Fixes.

---

### `tacroman.quickFixSingularCommand`

LaTeX command used for singular replacements.

Default:

```text
ac
```

---

### `tacroman.quickFixPluralCommand`

LaTeX command used for plural replacements.

Default:

```text
acp
```

---

### `tacroman.inferPlainTextPlurals`

Allows TAcroMan to recognize simple plural forms even when no explicit plural is
stored in the database.

---

### `tacroman.ignoredArgumentCommands`

Defines LaTeX commands whose braced arguments should not be interpreted as
normal prose during acronym detection.

---

### `tacroman.launchArguments`

Additional arguments passed when launching the desktop application.

</details>

---

## 🖥️ TAcroMan desktop application

The VS Code extension is part of the larger
[TAcroMan project](https://github.com/TAWilts/TexAcronymManager).

The integrated editor and desktop application render the same shared web
interface and manage the same JSON database, profiles, and generated output:

```text
Integrated editor ─┐
                   ├─ acronyms.json ─ entries.tex
Desktop app ───────┘
```

The desktop host is installed with the Python `tacroman` package and uses
pywebview for its native window. Its desktop-only menu includes the former
file, profile, tool, language, and help actions. Profile editing, citation
migration, and reference auditing run entirely in the shared Web interface.

The database remains a normal JSON file, so the extension does not lock you into
a proprietary document format.

## 🧭 Roadmap

- Develop a safer cloud-based synchronization method for shared acronym
  databases.
- Suggest converting a word or phrase to an acronym command when it occurs a
  configurable number of times in the document.
- Add an online acronym check to determine whether the spelling is correct,
  whether an acronym is commonly used, and whether alternative acronyms exist.

---

## 🤝 Works alongside LaTeX Workshop

TAcroMan is designed to complement
[LaTeX Workshop](https://marketplace.visualstudio.com/items?itemName=James-Yu.latex-workshop).

It does not modify LaTeX Workshop and does not replace its LaTeX editing,
building, citation, or navigation features.

TAcroMan simply adds acronym-specific tooling on top of your normal VS Code
LaTeX workflow.

---

## 🐛 Feedback and feature requests

Found a bug or have an idea for another acronym workflow?

Please open an issue:

**https://github.com/TAWilts/TexAcronymManager/issues**

If possible, include:

- your VS Code version;
- your TAcroMan extension version;
- your operating system;
- a small LaTeX example that reproduces the issue.

---

## 👨‍💻 Development

The VS Code extension lives in the same repository as the desktop application.

To build it locally on Windows:

```powershell
.\build-vscode-extension.cmd
```

The script automatically:

1. installs/updates the Node dependencies;
2. runs the extension tests;
3. selects an unused extension version and builds the `.vsix` package.

### Package version

`VERSION` is the source of truth for the next extension package. Put the
desired release version in `vscode-extension/VERSION`, for example `0.6.9`,
then run either build command above (or `npm run package` from
`vscode-extension/`). The package build updates `package.json` to use that
version.

If `tacroman-vscode-0.6.9.vsix` already exists in `vscode-extension/`, the
build automatically increases the patch number until it finds a free version:
`0.6.9` becomes `0.6.10`, for example. It writes the selected version back to
`VERSION`, so the file always records the last packaged version.

Alternatively, from `vscode-extension/`:

```bash
npm install
npm test
npm run package
```

---

## 📄 License

TAcroMan is released under the **MIT License**.

## Linux development

The VS Code extension itself is platform-independent. Build it on Linux with:

```bash
bash build-vscode-extension.sh
```

For desktop integration, install and start TAcroMan with `bash install-linux.sh`
and `bash run-tacroman.sh`. Both frontends use `~/TAcroMan/state.json`.
