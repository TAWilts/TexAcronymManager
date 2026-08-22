# Change Log

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
