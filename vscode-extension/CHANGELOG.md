# Change Log

## 0.7.1

- Keep the entry editor stationary while the database list scrolls independently.
- Restore the desktop menu bar with database creation, TeX import, output,
  profile, bibliography, language, help, and exit actions.
- Open the existing profile editor, citation migration, and reference audit as
  targeted classic tool windows until their larger dialogs are fully ported.
- Prevent pywebview/debugpy recursion by exposing only the message bridge and
  keeping the native Window and controller objects private.

## 0.7.0

- Reuse the same HTML, CSS, and JavaScript manager in VS Code and the native
  Python desktop application.
- Add a pywebview desktop host with native database/output dialogs, atomic
  persistence, generated-output updates, and shared-state synchronization.
- Add render-profile selection to both Webview hosts.
- Keep the former Tkinter frontend available as `tacroman-tk` while its
  remaining specialized tools are migrated.

## 0.6.2

- Open a profile-driven acronym manager directly inside VS Code instead of
  requiring the separately installed desktop application.
- Add, edit, delete, and filter entries in the integrated manager while keeping
  automatic generated-output updates.
- Detect database changes made by another frontend before saving so concurrent
  desktop and Webview edits cannot silently overwrite each other.
- Keep the existing Python application available through the separate
  **TAcroMan: Open Desktop Application** command.
- Store the host-independent Webview assets with the Python package so the same
  interface can become the desktop frontend during the next migration stage.

## 0.5.8

- Use only `~/TAcroMan/state.json` for remembered database/output paths and
  stop importing legacy integration files, obsolete VS Code path settings, and
  legacy desktop directory settings. The desktop launcher is also read only
  from this shared state instead of VS Code settings or `PATH`.
- Use `~/TAcroMan/entries.json` as the one first-run database default shared by
  the desktop application and VS Code extension.

## 0.5.6

- Store database/output selection in shared `~/TAcroMan/state.json` instead of
  workspace settings and synchronize it live with the desktop application.
- Default generated `entries.tex` to the current VS Code project and regenerate
  output automatically after database changes.
- Add sidebar and Command Palette selection for the generated TeX output.

## 0.5.1

- Add a `VERSION`-file packaging workflow that automatically selects the next
  available patch version when a VSIX with the requested version already exists.

## 0.5.0

- Show explicit plural forms as separate rows in the TAcroMan sidebar.
- Keep plural-only fields from being treated as singular display values.
- Add AUC regression tests for explicit long plurals and `\acp{...}` replacement.
- Add Linux install/run/build helpers and Ubuntu compatibility CI.

## 0.4.1

- Make **Check Current File for Acronyms** reliably visible as both an inline toolbar action and an in-view action.
- Fix deletion of desktop TAcroMan entries after table sorting/filtering by resolving selected rows to stable entry UIDs.

## 0.4.0

- Watch the active acronym JSON file directly and refresh completion, diagnostics, and the sidebar after external saves.
- Add **Check Current File for Acronyms** to scan short and long forms in the active LaTeX file.
- Review every detected acronym individually before replacing it with the configured `\ac{...}` or `\acp{...}` command.

## 0.3.3

- Publish the desktop TAcroMan launcher alongside the active database path.
- Make **Open TAcroMan** automatically use the current desktop/venv installation.
- Keep `tacroman.executablePath` as an explicit VS Code override.
- Hide spawned console windows on Windows.

## 0.3.2

- Add a one-command Windows build script for installing dependencies, testing,
  and packaging the VS Code extension.
- Make **Open TAcroMan** a visible action in the sidebar title.
- Add an in-view **Open TAcroMan** entry for adding or editing acronyms.

## 0.3.1

- Fix the Secondary Side Bar view-container identifier so VS Code accepts the
  TAcroMan container instead of falling back to Explorer.

## 0.3.0

- Add a native TAcroMan acronym browser in VS Code's Secondary Side Bar.
- Show the active database path and all loaded acronym short/long forms.
- Add acronym filtering, automatic sidebar refresh, and database/open/reload actions.
- Add context actions to insert `\ac{...}` or `\acp{...}` from the acronym list.

## 0.2.1

- Offer completion directly in normal LaTeX prose.
- Match partial short forms such as `AU` and partial long forms such as `autonomous under`.
- Replace the typed prose with `\ac{...}` or `\acp{...}` when a suggestion is accepted.
- Keep plain-text completion out of comments, acronym commands, definitions, citations, references, and other configured ignored arguments.

## 0.2.0

- Keep the VS Code extension in the main TAcroMan repository.
- Detect known short forms written directly in LaTeX prose.
- Offer Quick Fixes such as `AUV` -> `\ac{AUV}`.
- Detect explicit and optionally inferred plural forms, e.g. `AUVs` -> `\acp{AUV}`.
- Ignore existing acronym commands, comments, acronym definitions, and common non-prose command arguments.
- Refresh diagnostics when the TAcroMan JSON database changes.

## 0.1.0

- Initial proof-of-concept.
- Workspace TAcroMan database discovery.
- LaTeX acronym completion by short and long form.
- Database selection, reload, and TAcroMan launch commands.
