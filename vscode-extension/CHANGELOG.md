# Change Log

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
