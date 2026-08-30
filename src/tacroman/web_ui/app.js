(function () {
  "use strict";

  const vscode = typeof acquireVsCodeApi === "function" ? acquireVsCodeApi() : null;
  const queuedDesktopMessages = [];
  const host = window.tacromanHost || {
    postMessage(message) {
      if (vscode) {
        vscode.postMessage(message);
        return;
      }
      if (window.pywebview?.api?.post_message) {
        window.pywebview.api.post_message(JSON.stringify(message));
        return;
      }
      queuedDesktopMessages.push(message);
    },
  };

  const elements = {};
  let snapshot = null;
  let selectedUid = null;
  let draftCommandId = null;
  let dirty = false;
  let deferredSnapshot = null;
  let language = "en";
  let profileEditorState = null;
  let citationState = null;
  let auditState = null;

  const texts = {
    en: {
      menuFile: "File", openDatabase: "Open database…", newDatabase: "New database…",
      importTex: "Import TeX file…", writeOutput: "Write output file", exit: "Exit",
      menuProfiles: "Profiles", editProfile: "Edit active profile…", selectProfiles: "Choose profile file…",
      menuTools: "Tools", citationMigration: "Migrate citation keys…", referenceAudit: "Audit references…",
      menuLanguage: "Language", menuHelp: "Help", help: "Help", about: "About TAcroMan", close: "Close",
      helpTitle: "TAcroMan help",
      helpText: "Select or create a database, choose a profile and edit entries in the form. Changes are written to the JSON database and generated output. Profile and bibliography tools are available from the desktop menu.",
      aboutText: "TAcroMan manages profile-defined LaTeX commands from one shared database.",
      windowHelp: "What is this window for?",
      generalHelpTooltip: "This window gives you a brief overview of the normal workflow. Read the instructions, close the window, then select a database and profile to start editing.",
      aboutHelpTooltip: "This window explains the purpose of TAcroMan and the shared database model. No action is required.",
      databaseLabel: "Database:", outputLabel: "Output:", selectDatabase: "Select database",
      selectOutput: "Select output", desktopApp: "Desktop app", searchEntries: "Search entries",
      conflict: "The database changed outside this editor.", reload: "Reload", newEntry: "New entry",
      editEntry: "Edit entry", type: "Type", save: "Save", new: "New", delete: "Delete", loading: "Loading…",
      noOutput: "No generated output selected", noMatches: "No matching entries", noEntries: "No entries yet",
      untitled: "Untitled entry", discard: "Discard the unsaved changes?", unsupported: "This entry type is not part of the active profile.",
      unsaved: "Unsaved changes", saved: "Saved", reloaded: "Database reloaded", ready: "Ready",
      saving: "Saving…", deleting: "Deleting…", deleteConfirm: "Delete this entry?", changingProfile: "Changing profile…",
      importing: "Importing…",
      profileEditorTitle: "Edit profiles", citationToolTitle: "Migrate citation keys",
      auditToolTitle: "Audit references", profileFile: "Profile file", duplicateProfile: "Duplicate profile",
      profileEditorHelp: "Use this window to define how TAcroMan stores and renders command types.\n\n1. Select an existing profile or duplicate one.\n2. Edit its metadata, output settings, and command schema.\n3. Save the profile. TAcroMan validates it and immediately regenerates the output with the selected profile.",
      citationToolHelp: "Use this window when citation keys changed between two bibliography files.\n\n1. Select the old and new bibliography.\n2. Analyse the proposed mappings and correct them if necessary.\n3. Add the TeX files or a project folder.\n4. Keep backups enabled and update the TeX files.",
      auditToolHelp: "Use this window to check which bibliography entries are used in a LaTeX project.\n\n1. Select the project folder.\n2. Select one of the discovered bibliography files.\n3. Run the audit.\n4. Review used, unused, and unknown citation keys; use the search field to narrow the results.",
      profileId: "Profile ID", profileName: "Name", description: "Description", preamble: "Preamble hint",
      header: "Header", footer: "Footer", separator: "Separator", sortBy: "Sort by", escapeMode: "Escape mode",
      usageTemplate: "Usage template", commandSchema: "Command schema (JSON)", saveProfile: "Save profile",
      choose: "Choose…", oldBibliography: "Old bibliography", newBibliography: "New bibliography",
      texFiles: "TeX files", addFiles: "Add files…", addFolder: "Add folder…", analyse: "Analyse mappings",
      createBackups: "Create .bak backups", applyMigration: "Update TeX files", addMapping: "Add mapping",
      use: "Use", oldKey: "Old key", newKey: "New key", status: "Status", method: "Method", title: "Title",
      projectFolder: "Project folder", referenceFile: "Reference file", audit: "Run audit",
      bibliography: "Bibliography", unusedReferences: "Unused references", citationOccurrences: "Citation occurrences", unknownKeys: "Unknown keys",
      key: "Key", author: "Author", file: "File", line: "Line", excerpt: "Excerpt",
      noResults: "No results", invalidJson: "The command schema is not valid JSON.",
      importConfirm: "Import acronym definitions from a TeX file?",
      replaceConfirm: "Replace the existing entries? Choose Cancel to merge new acronyms instead.",
      exitConfirm: "Close TAcroMan?",
    },
    de: {
      menuFile: "Datei", openDatabase: "Datenbank öffnen…", newDatabase: "Neue Datenbank…",
      importTex: "TeX-Datei importieren…", writeOutput: "Ausgabedatei schreiben", exit: "Beenden",
      menuProfiles: "Profile", editProfile: "Aktives Profil bearbeiten…", selectProfiles: "Profildatei auswählen…",
      menuTools: "Werkzeuge", citationMigration: "Zitationsschlüssel migrieren…", referenceAudit: "Referenzen prüfen…",
      menuLanguage: "Sprache", menuHelp: "Hilfe", help: "Hilfe", about: "Über TAcroMan", close: "Schließen",
      helpTitle: "TAcroMan-Hilfe",
      helpText: "Wähle oder erstelle eine Datenbank, wähle ein Profil und bearbeite die Einträge in der Eingabemaske. Änderungen werden in die JSON-Datenbank und die generierte Ausgabedatei geschrieben. Profil- und Literaturwerkzeuge findest du im Desktop-Menü.",
      aboutText: "TAcroMan verwaltet profildefinierte LaTeX-Befehle aus einer gemeinsamen Datenbank.",
      windowHelp: "Wofür ist dieses Fenster da?",
      generalHelpTooltip: "Dieses Fenster gibt dir einen kurzen Überblick über den normalen Arbeitsablauf. Lies die Hinweise, schließe das Fenster und wähle danach eine Datenbank und ein Profil aus, um mit der Bearbeitung zu beginnen.",
      aboutHelpTooltip: "Dieses Fenster erklärt den Zweck von TAcroMan und das gemeinsame Datenbankmodell. Du musst hier nichts einstellen.",
      databaseLabel: "Datenbank:", outputLabel: "Ausgabe:", selectDatabase: "Datenbank auswählen",
      selectOutput: "Ausgabe auswählen", desktopApp: "Desktop-App", searchEntries: "Einträge durchsuchen",
      conflict: "Die Datenbank wurde außerhalb dieses Editors geändert.", reload: "Neu laden", newEntry: "Neuer Eintrag",
      editEntry: "Eintrag bearbeiten", type: "Typ", save: "Speichern", new: "Neu", delete: "Löschen", loading: "Laden…",
      noOutput: "Keine Ausgabedatei ausgewählt", noMatches: "Keine passenden Einträge", noEntries: "Noch keine Einträge",
      untitled: "Unbenannter Eintrag", discard: "Ungespeicherte Änderungen verwerfen?", unsupported: "Dieser Eintragstyp gehört nicht zum aktiven Profil.",
      unsaved: "Ungespeicherte Änderungen", saved: "Gespeichert", reloaded: "Datenbank neu geladen", ready: "Bereit",
      saving: "Wird gespeichert…", deleting: "Wird gelöscht…", deleteConfirm: "Diesen Eintrag löschen?", changingProfile: "Profil wird gewechselt…",
      importing: "Import läuft…",
      profileEditorTitle: "Profile bearbeiten", citationToolTitle: "Zitationsschlüssel migrieren",
      auditToolTitle: "Referenzen prüfen", profileFile: "Profildatei", duplicateProfile: "Profil duplizieren",
      profileEditorHelp: "In diesem Fenster legst du fest, wie TAcroMan Befehlstypen speichert und ausgibt.\n\n1. Wähle ein vorhandenes Profil oder dupliziere es.\n2. Bearbeite Metadaten, Ausgabeoptionen und das Befehlsschema.\n3. Speichere das Profil. TAcroMan prüft es und erzeugt die Ausgabe sofort mit dem gewählten Profil neu.",
      citationToolHelp: "Dieses Fenster verwendest du, wenn sich Zitationsschlüssel zwischen zwei Bibliographien geändert haben.\n\n1. Wähle die alte und die neue Bibliographie.\n2. Analysiere die vorgeschlagenen Zuordnungen und korrigiere sie bei Bedarf.\n3. Füge die TeX-Dateien oder einen Projektordner hinzu.\n4. Lasse die Sicherungen aktiviert und aktualisiere die TeX-Dateien.",
      auditToolHelp: "Mit diesem Fenster prüfst du, welche Bibliographieeinträge in einem LaTeX-Projekt verwendet werden.\n\n1. Wähle den Projektordner.\n2. Wähle eine der gefundenen Bibliographiedateien.\n3. Starte die Prüfung.\n4. Kontrolliere verwendete, ungenutzte und unbekannte Zitationsschlüssel; mit der Suche grenzt du die Ergebnisse ein.",
      profileId: "Profil-ID", profileName: "Name", description: "Beschreibung", preamble: "Präambel-Hinweis",
      header: "Kopf", footer: "Fuß", separator: "Trennzeichen", sortBy: "Sortierung", escapeMode: "Maskierung",
      usageTemplate: "Verwendungsvorlage", commandSchema: "Befehlsschema (JSON)", saveProfile: "Profil speichern",
      choose: "Auswählen…", oldBibliography: "Alte Bibliographie", newBibliography: "Neue Bibliographie",
      texFiles: "TeX-Dateien", addFiles: "Dateien hinzufügen…", addFolder: "Ordner hinzufügen…", analyse: "Zuordnungen analysieren",
      createBackups: ".bak-Sicherungen anlegen", applyMigration: "TeX-Dateien aktualisieren", addMapping: "Zuordnung hinzufügen",
      use: "Nutzen", oldKey: "Alter Schlüssel", newKey: "Neuer Schlüssel", status: "Status", method: "Methode", title: "Titel",
      projectFolder: "Projektordner", referenceFile: "Referenzdatei", audit: "Prüfung starten",
      bibliography: "Bibliographie", unusedReferences: "Ungenutzte Referenzen", citationOccurrences: "Zitationsvorkommen", unknownKeys: "Unbekannte Schlüssel",
      key: "Schlüssel", author: "Autor", file: "Datei", line: "Zeile", excerpt: "Ausschnitt",
      noResults: "Keine Ergebnisse", invalidJson: "Das Befehlsschema ist kein gültiges JSON.",
      importConfirm: "Akronymdefinitionen aus einer TeX-Datei importieren?",
      replaceConfirm: "Vorhandene Einträge ersetzen? Mit Abbrechen werden die neuen Akronyme stattdessen zusammengeführt.",
      exitConfirm: "TAcroMan schließen?",
    },
  };

  function text(key) {
    return texts[language]?.[key] || texts.en[key] || key;
  }

  function applyLanguage(nextLanguage) {
    language = nextLanguage === "de" ? "de" : "en";
    document.documentElement.lang = language;
    for (const node of document.querySelectorAll("[data-text]")) {
      node.textContent = text(node.dataset.text);
    }
    for (const node of document.querySelectorAll("[data-placeholder]")) {
      node.placeholder = text(node.dataset.placeholder);
      node.setAttribute("aria-label", text(node.dataset.placeholder));
    }
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function setStatus(message, kind) {
    elements.status.textContent = message || "";
    elements.status.dataset.kind = kind || "info";
  }

  function closeMenus() {
    for (const menu of document.querySelectorAll(".menu[open]")) menu.removeAttribute("open");
  }

  function configureWindowHelp(button, tooltip, helpKey) {
    const label = text("windowHelp");
    button.setAttribute("aria-label", label);
    button.title = label;
    tooltip.textContent = text(helpKey);
  }

  function showInfo(title, content, helpKey) {
    elements.infoTitle.textContent = title;
    elements.infoContent.textContent = content;
    configureWindowHelp(elements.infoHelp, elements.infoHelpTooltip, helpKey);
    elements.infoDialog.showModal();
  }

  function toolButton(labelKey, onClick, secondary = true) {
    const button = el("button", `button${secondary ? " secondary" : ""}`, text(labelKey));
    button.type = "button";
    button.addEventListener("click", onClick);
    return button;
  }

  function toolField(labelKey, value = "", multiline = false) {
    const wrapper = el("label", "field");
    wrapper.append(el("span", "field-label", text(labelKey)));
    const control = el(multiline ? "textarea" : "input", "field-control");
    control.value = value ?? "";
    wrapper.append(control);
    return { wrapper, control };
  }

  function openTool(titleKey, helpKey) {
    elements.toolTitle.textContent = text(titleKey);
    configureWindowHelp(elements.toolHelp, elements.toolHelpTooltip, helpKey);
    if (!elements.toolDialog.open) elements.toolDialog.showModal();
  }

  function profileFormValue(id) {
    return document.getElementById(id)?.value ?? "";
  }

  function renderProfileEditor(selectedId) {
    if (!profileEditorState) return;
    const profiles = profileEditorState.profiles;
    const selected = profiles.find((profile) => profile.id === selectedId) || profiles[0];
    if (!selected) return;
    profileEditorState.originalId = selected.id;
    profileEditorState.editing = JSON.parse(JSON.stringify(selected));
    openTool("profileEditorTitle", "profileEditorHelp");
    elements.toolBody.replaceChildren();

    const top = el("div", "tool-row");
    const selectorField = toolField("profileFile", profileEditorState.profilesPath);
    selectorField.control.readOnly = true;
    const selector = el("select", "field-control");
    for (const profile of profiles) {
      const option = el("option", "", profile.name || profile.id);
      option.value = profile.id;
      option.selected = profile.id === selected.id;
      selector.append(option);
    }
    selector.addEventListener("change", () => renderProfileEditor(selector.value));
    top.append(selector, toolButton("duplicateProfile", () => {
      const duplicate = JSON.parse(JSON.stringify(profileEditorState.editing));
      duplicate.id = `${duplicate.id}-copy`;
      duplicate.name = `${duplicate.name} copy`;
      profileEditorState.profiles.push(duplicate);
      renderProfileEditor(duplicate.id);
      profileEditorState.originalId = null;
    }));
    elements.toolBody.append(top, selectorField.wrapper);

    const form = el("div", "profile-form");
    const fields = [
      ["profileId", "profile-id", selected.id, false], ["profileName", "profile-name", selected.name, false],
      ["description", "profile-description", selected.description, true], ["preamble", "profile-preamble", selected.preamble_hint, true],
      ["header", "profile-header", selected.header, true], ["footer", "profile-footer", selected.footer, true],
      ["separator", "profile-separator", selected.separator, true], ["sortBy", "profile-sort", selected.sort_by, false],
      ["usageTemplate", "profile-usage", selected.usage_template, true],
    ];
    for (const [label, id, value, multiline] of fields) {
      const item = toolField(label, value || "", multiline);
      item.control.id = id;
      if (multiline) item.wrapper.classList.add("wide");
      form.append(item.wrapper);
    }
    const escapeField = toolField("escapeMode");
    const escapeSelect = el("select", "field-control");
    escapeSelect.id = "profile-escape";
    for (const mode of ["none", "latex", "csv"]) {
      const option = el("option", "", mode);
      option.value = mode;
      option.selected = mode === selected.escape_mode;
      escapeSelect.append(option);
    }
    escapeField.control.replaceWith(escapeSelect);
    form.append(escapeField.wrapper);
    const commands = toolField("commandSchema", JSON.stringify(selected.commands || [], null, 2), true);
    commands.wrapper.classList.add("wide");
    commands.control.id = "profile-commands";
    commands.control.classList.add("commands-editor");
    form.append(commands.wrapper);
    elements.toolBody.append(form);

    const status = el("div", "tool-status");
    status.id = "profile-status";
    const actions = el("div", "tool-actions");
    actions.append(toolButton("saveProfile", () => {
      let commandSchema;
      try {
        commandSchema = JSON.parse(profileFormValue("profile-commands"));
      } catch (_error) {
        status.textContent = text("invalidJson");
        status.dataset.kind = "error";
        return;
      }
      const profile = {
        ...profileEditorState.editing,
        id: profileFormValue("profile-id").trim(),
        name: profileFormValue("profile-name").trim(),
        description: profileFormValue("profile-description"),
        preamble_hint: profileFormValue("profile-preamble"),
        header: profileFormValue("profile-header"),
        footer: profileFormValue("profile-footer"),
        separator: profileFormValue("profile-separator"),
        sort_by: profileFormValue("profile-sort").trim(),
        escape_mode: profileFormValue("profile-escape"),
        usage_template: profileFormValue("profile-usage"),
        commands: commandSchema,
      };
      host.postMessage({ type: "saveProfile", originalId: profileEditorState.originalId, profile });
      status.textContent = text("saving");
    }, false));
    elements.toolBody.append(actions, status);
  }

  function openCitationTool() {
    citationState = { oldBib: "", newBib: "", texFiles: [], matches: [], summary: null, result: "" };
    renderCitationTool();
  }

  function renderCitationTool() {
    if (!citationState) return;
    openTool("citationToolTitle", "citationToolHelp");
    elements.toolBody.replaceChildren();
    const grid = el("div", "tool-grid two-columns");
    const bibs = el("section", "tool-section");
    bibs.append(el("h3", "", text("citationToolTitle")));
    for (const [label, target, property] of [
      ["oldBibliography", "oldBib", "oldBib"], ["newBibliography", "newBib", "newBib"],
    ]) {
      const row = el("div", "tool-row");
      const field = toolField(label, citationState[property]);
      field.control.readOnly = true;
      row.append(field.wrapper, toolButton("choose", () => host.postMessage({ type: "chooseToolPath", target })));
      bibs.append(row);
    }
    bibs.append(toolButton("analyse", () => host.postMessage({
      type: "analyseCitations", oldBib: citationState.oldBib, newBib: citationState.newBib,
    }), false));

    const files = el("section", "tool-section");
    files.append(el("h3", "", text("texFiles")));
    const fileActions = el("div", "tool-actions");
    fileActions.append(
      toolButton("addFiles", () => host.postMessage({ type: "chooseToolPath", target: "texFiles" })),
      toolButton("addFolder", () => host.postMessage({ type: "chooseToolPath", target: "texFolder" })),
    );
    files.append(fileActions);
    const list = el("ul", "tool-list");
    citationState.texFiles.forEach((path, index) => {
      const item = el("li");
      item.append(el("span", "", path), toolButton("delete", () => {
        citationState.texFiles.splice(index, 1);
        renderCitationTool();
      }));
      list.append(item);
    });
    files.append(list);
    grid.append(bibs, files);
    elements.toolBody.append(grid);

    const mappingSection = el("section", "tool-section");
    mappingSection.append(el("h3", "", text("analyse")));
    const mappingActions = el("div", "tool-actions");
    mappingActions.append(toolButton("addMapping", () => {
      citationState.matches.push({ old_key: "", new_key: "", status: "manual", method: "manual", title: "", selected: true });
      renderCitationTool();
    }));
    mappingSection.append(mappingActions);
    const tableWrap = el("div", "tool-table-wrap");
    const table = el("table", "tool-table");
    const head = el("tr");
    for (const label of ["use", "oldKey", "newKey", "status", "method", "title", "delete"]) head.append(el("th", "", text(label)));
    const tableHead = el("thead");
    tableHead.append(head);
    table.append(tableHead);
    const body = el("tbody");
    citationState.matches.forEach((match, index) => {
      const row = el("tr");
      const selectedCell = el("td");
      const selected = el("input"); selected.type = "checkbox"; selected.checked = match.selected ?? (match.status === "matched" && match.old_key !== match.new_key);
      selected.addEventListener("change", () => { match.selected = selected.checked; });
      selectedCell.append(selected);
      const oldCell = el("td"); const oldInput = el("input"); oldInput.type = "text"; oldInput.value = match.old_key || "";
      oldInput.addEventListener("input", () => { match.old_key = oldInput.value; }); oldCell.append(oldInput);
      const newCell = el("td"); const newInput = el("input"); newInput.type = "text"; newInput.value = match.new_key || "";
      newInput.addEventListener("input", () => { match.new_key = newInput.value; }); newCell.append(newInput);
      const removeCell = el("td"); removeCell.append(toolButton("delete", () => { citationState.matches.splice(index, 1); renderCitationTool(); }));
      row.append(selectedCell, oldCell, newCell, el("td", "", match.status), el("td", "", match.method), el("td", "", match.title), removeCell);
      body.append(row);
    });
    table.append(body); tableWrap.append(table); mappingSection.append(tableWrap);
    if (citationState.summary) {
      mappingSection.append(el("div", "tool-status", JSON.stringify(citationState.summary)));
    }
    elements.toolBody.append(mappingSection);

    const backupLabel = el("label", "field-label");
    const backup = el("input"); backup.type = "checkbox"; backup.checked = citationState.backup !== false;
    backup.addEventListener("change", () => { citationState.backup = backup.checked; });
    backupLabel.append(backup, document.createTextNode(` ${text("createBackups")}`));
    const actions = el("div", "tool-actions");
    actions.append(backupLabel, toolButton("applyMigration", () => {
      const mapping = {};
      for (const match of citationState.matches) {
        if (!match.selected) continue;
        const oldKey = (match.old_key || "").trim();
        const newKey = (match.new_key || "").trim();
        if (!oldKey || !newKey || oldKey === newKey) continue;
        if (mapping[oldKey] && mapping[oldKey] !== newKey) {
          window.alert(`Conflicting mappings for ${oldKey}`);
          return;
        }
        mapping[oldKey] = newKey;
      }
      if (!window.confirm(`${text("applyMigration")}?`)) return;
      host.postMessage({ type: "applyCitationMigration", mapping, paths: citationState.texFiles, backup: citationState.backup !== false });
    }, false));
    elements.toolBody.append(actions, el("div", "tool-status", citationState.result || ""));
  }

  function openAuditTool() {
    auditState = { project: snapshot?.outputPath ? snapshot.outputPath.replace(/[\\/][^\\/]+$/, "") : "", reference: "", referenceFiles: [], report: null, query: "" };
    renderAuditTool();
  }

  function auditTable(columns, rows) {
    const terms = (auditState?.query || "").toLocaleLowerCase().split(/\s+/).filter(Boolean);
    rows = rows.filter((item) => {
      const searchable = Object.values(item).join(" ").toLocaleLowerCase();
      return terms.every((term) => searchable.includes(term));
    });
    if (!rows.length) return el("div", "empty", text("noResults"));
    const wrap = el("div", "tool-table-wrap");
    const table = el("table", "tool-table");
    const head = el("tr");
    columns.forEach(([label]) => head.append(el("th", "", text(label))));
    const thead = el("thead"); thead.append(head); table.append(thead);
    const body = el("tbody");
    rows.forEach((item) => {
      const row = el("tr");
      columns.forEach(([, key, className]) => row.append(el("td", className || "", String(item[key] ?? ""))));
      body.append(row);
    });
    table.append(body); wrap.append(table); return wrap;
  }

  function renderAuditTool() {
    if (!auditState) return;
    openTool("auditToolTitle", "auditToolHelp");
    elements.toolBody.replaceChildren();
    const controls = el("section", "tool-section");
    for (const [label, target, property] of [
      ["projectFolder", "auditProject", "project"], ["referenceFile", "auditReference", "reference"],
    ]) {
      const row = el("div", "tool-row");
      const field = toolField(label, auditState[property]); field.control.readOnly = true;
      row.append(field.wrapper, toolButton("choose", () => host.postMessage({ type: "chooseToolPath", target })));
      controls.append(row);
    }
    if (auditState.referenceFiles.length) {
      const field = toolField("referenceFile");
      const select = el("select", "field-control");
      auditState.referenceFiles.forEach((path) => {
        const option = el("option", "", path); option.value = path; option.selected = path === auditState.reference; select.append(option);
      });
      select.addEventListener("change", () => { auditState.reference = select.value; });
      field.control.replaceWith(select); controls.append(field.wrapper);
    }
    controls.append(toolButton("audit", () => host.postMessage({
      type: "auditReferences", project: auditState.project, reference: auditState.reference,
    }), false));
    elements.toolBody.append(controls);
    if (!auditState.report) return;
    const report = auditState.report;
    const search = toolField("searchEntries", auditState.query);
    search.control.type = "search";
    search.control.addEventListener("change", () => {
      auditState.query = search.control.value;
      renderAuditTool();
    });
    elements.toolBody.append(search.wrapper);
    const summary = el("div", "audit-summary");
    for (const value of [
      `${report.bibliography.length} references`, `${report.usedKeys.length} used`,
      `${report.unused.length} unused`, `${report.unknownKeys.length} unknown`,
    ]) summary.append(el("span", "summary-chip", value));
    const results = el("div", "audit-results");
    results.append(
      el("h3", "", text("bibliography")),
      auditTable([["key", "key"], ["title", "title"], ["author", "author"]], report.bibliography),
      el("h3", "", text("unusedReferences")),
      auditTable([["key", "key"], ["title", "title"], ["author", "author"]], report.unused),
      el("h3", "", text("citationOccurrences")),
      auditTable([["file", "relativePath"], ["line", "line"], ["key", "key"], ["excerpt", "excerpt", "excerpt"]], report.occurrences),
      el("h3", "", text("unknownKeys")),
      auditTable([["key", "key"]], report.unknownKeys.map((key) => ({ key }))),
    );
    elements.toolBody.append(summary, results);
  }

  function commandForEntry(entry) {
    return snapshot.profile.commands.find((command) => command.id === entry.commandId);
  }

  function primaryValue(entry) {
    const command = commandForEntry(entry);
    const comparisonField = command?.fields.find((field) => field.comparisonGroup);
    const field = comparisonField || command?.fields[0];
    return field ? (entry.values[field.id] || "") : entry.commandId;
  }

  function secondaryValue(entry) {
    const primary = primaryValue(entry);
    return Object.values(entry.values).find((value) => value && value !== primary) || "";
  }

  function currentEntry() {
    return snapshot?.entries.find((entry) => entry.uid === selectedUid) || null;
  }

  function confirmDiscard() {
    return !dirty || window.confirm(text("discard"));
  }

  function selectEntry(uid) {
    if (uid === selectedUid || !confirmDiscard()) return;
    selectedUid = uid;
    draftCommandId = snapshot.entries.find((entry) => entry.uid === uid)?.commandId || null;
    dirty = false;
    renderList();
    renderForm();
  }

  function renderList() {
    elements.entryList.replaceChildren();
    if (!snapshot) return;
    const query = elements.search.value.trim().toLocaleLowerCase();
    const entries = snapshot.entries
      .filter((entry) => !query || [entry.commandId, ...Object.values(entry.values)]
        .join(" ").toLocaleLowerCase().includes(query))
      .sort((left, right) => primaryValue(left).localeCompare(primaryValue(right), undefined, { sensitivity: "base" }));

    elements.count.textContent = `${entries.length} / ${snapshot.entries.length}`;
    if (!entries.length) {
      elements.entryList.append(el("div", "empty", query ? text("noMatches") : text("noEntries")));
      return;
    }
    for (const entry of entries) {
      const button = el("button", `entry-row${entry.uid === selectedUid ? " selected" : ""}`);
      button.type = "button";
      button.addEventListener("click", () => selectEntry(entry.uid));
      const title = el("span", "entry-title", primaryValue(entry) || text("untitled"));
      const details = el("span", "entry-details", secondaryValue(entry));
      const command = commandForEntry(entry);
      const badge = el("span", "entry-command", command?.label || entry.commandId);
      button.append(title, details, badge);
      elements.entryList.append(button);
    }
  }

  function fieldControl(field, value) {
    const wrapper = el("label", "field");
    const caption = el("span", "field-label", field.label + (field.required ? " *" : ""));
    const control = field.multiline ? el("textarea", "field-control") : el("input", "field-control");
    control.name = field.id;
    control.value = value || "";
    control.required = field.required;
    control.autocomplete = "off";
    control.addEventListener("input", () => {
      dirty = true;
      setStatus(text("unsaved"), "warning");
    });
    wrapper.append(caption, control);
    return wrapper;
  }

  function renderForm() {
    elements.formFields.replaceChildren();
    if (!snapshot) return;
    const entry = currentEntry();
    const selectedCommandId = entry?.commandId || draftCommandId || snapshot.profile.commands[0]?.id;
    elements.command.replaceChildren();
    for (const command of snapshot.profile.commands) {
      const option = el("option", "", command.label);
      option.value = command.id;
      option.selected = command.id === selectedCommandId;
      elements.command.append(option);
    }
    const command = snapshot.profile.commands.find((item) => item.id === selectedCommandId);
    if (entry && !command) {
      const unsupported = el("option", "", entry.commandId);
      unsupported.value = entry.commandId;
      unsupported.selected = true;
      unsupported.disabled = true;
      elements.command.prepend(unsupported);
    }
    elements.formTitle.textContent = entry ? text("editEntry") : text("newEntry");
    elements.formDescription.textContent = command?.description
      || (entry ? text("unsupported") : "");
    elements.deleteButton.hidden = !entry;
    elements.saveButton.disabled = !command;
    if (!command) return;
    for (const field of command.fields) {
      elements.formFields.append(fieldControl(field, entry?.values[field.id] || ""));
    }
  }

  function applySnapshot(next, reason) {
    if (dirty && reason === "external" && snapshot?.revision !== next.revision) {
      deferredSnapshot = next;
      elements.conflict.hidden = false;
      setStatus("The database changed outside this editor.", "warning");
      return;
    }
    snapshot = next;
    deferredSnapshot = null;
    elements.conflict.hidden = true;
    applyLanguage(next.language || language);
    elements.databasePath.textContent = next.databasePath;
    elements.databasePath.title = next.databasePath;
    elements.outputPath.textContent = next.outputPath || text("noOutput");
    elements.profileSelect.replaceChildren();
    for (const profile of next.profiles || [{ id: next.profile.id, name: next.profile.name }]) {
      const option = el("option", "", profile.name);
      option.value = profile.id;
      option.selected = profile.id === next.profile.id;
      elements.profileSelect.append(option);
    }
    elements.openDesktop.hidden = next.hostKind === "desktop";
    elements.desktopMenubar.hidden = next.hostKind !== "desktop";
    if (selectedUid && !next.entries.some((entry) => entry.uid === selectedUid)) selectedUid = null;
    if (selectedUid) draftCommandId = next.entries.find((entry) => entry.uid === selectedUid)?.commandId || null;
    dirty = false;
    renderList();
    renderForm();
    if (reason === "mutation") setStatus(text("saved"), "success");
    else if (reason === "external") setStatus(text("reloaded"), "info");
    else setStatus(text("ready"), "info");
  }

  function saveEntry(event) {
    event.preventDefault();
    if (!snapshot) return;
    const values = {};
    for (const control of elements.formFields.querySelectorAll("input, textarea")) {
      values[control.name] = control.value;
    }
    host.postMessage({
      type: "saveEntry",
      revision: snapshot.revision,
      entry: {
        uid: selectedUid || undefined,
        commandId: elements.command.value,
        values,
      },
    });
    setStatus(text("saving"), "info");
  }

  function deleteEntry() {
    if (!snapshot || !selectedUid || !window.confirm(text("deleteConfirm"))) return;
    host.postMessage({ type: "deleteEntry", revision: snapshot.revision, uid: selectedUid });
    setStatus(text("deleting"), "info");
  }

  function initialize() {
    for (const id of [
      "database-path", "output-path", "profile-select", "search", "count", "entry-list", "editor-form",
      "form-title", "form-description", "command", "form-fields", "new-button", "delete-button",
      "save-button", "select-database", "select-output", "open-desktop", "status", "conflict", "reload-conflict",
      "desktop-menubar", "menu-open-database", "menu-new-database", "menu-import-tex", "menu-write-output",
      "menu-exit", "menu-edit-profile", "menu-select-profiles", "menu-citation-migration", "menu-reference-audit",
      "menu-language-de", "menu-language-en", "menu-help", "menu-about", "info-dialog", "info-title", "info-content",
      "info-help", "info-help-tooltip", "tool-dialog", "tool-title", "tool-body", "tool-close", "tool-help", "tool-help-tooltip",
    ]) elements[id.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = document.getElementById(id);

    elements.search.addEventListener("input", renderList);
    elements.editorForm.addEventListener("submit", saveEntry);
    elements.command.addEventListener("change", () => {
      const nextCommandId = elements.command.value;
      if (!confirmDiscard()) {
        renderForm();
        return;
      }
      selectedUid = null;
      draftCommandId = nextCommandId;
      dirty = false;
      renderList();
      renderForm();
    });
    elements.newButton.addEventListener("click", () => {
      if (!confirmDiscard()) return;
      selectedUid = null;
      draftCommandId = elements.command.value || snapshot?.profile.commands[0]?.id || null;
      dirty = false;
      renderList();
      renderForm();
      elements.formFields.querySelector("input, textarea")?.focus();
    });
    elements.deleteButton.addEventListener("click", deleteEntry);
    elements.selectDatabase.addEventListener("click", () => host.postMessage({ type: "selectDatabase" }));
    elements.selectOutput.addEventListener("click", () => host.postMessage({ type: "selectOutput" }));
    elements.openDesktop.addEventListener("click", () => host.postMessage({ type: "openDesktop" }));
    elements.menuOpenDatabase.addEventListener("click", () => host.postMessage({ type: "selectDatabase" }));
    elements.menuNewDatabase.addEventListener("click", () => host.postMessage({ type: "newDatabase" }));
    elements.menuImportTex.addEventListener("click", () => {
      if (!window.confirm(text("importConfirm"))) return;
      const mode = snapshot?.entries.length && window.confirm(text("replaceConfirm")) ? "replace" : "merge";
      host.postMessage({ type: "importTex", mode, revision: snapshot?.revision });
      setStatus(text("importing"), "info");
    });
    elements.menuWriteOutput.addEventListener("click", () => host.postMessage({ type: "writeOutput" }));
    elements.menuExit.addEventListener("click", () => {
      if (window.confirm(text("exitConfirm"))) host.postMessage({ type: "exitApp" });
    });
    elements.menuEditProfile.addEventListener("click", () => host.postMessage({ type: "openProfileEditor" }));
    elements.menuSelectProfiles.addEventListener("click", () => host.postMessage({ type: "selectProfiles" }));
    elements.menuCitationMigration.addEventListener("click", openCitationTool);
    elements.menuReferenceAudit.addEventListener("click", openAuditTool);
    elements.menuLanguageDe.addEventListener("click", () => host.postMessage({ type: "setLanguage", language: "de" }));
    elements.menuLanguageEn.addEventListener("click", () => host.postMessage({ type: "setLanguage", language: "en" }));
    elements.menuHelp.addEventListener("click", () => showInfo(text("helpTitle"), text("helpText"), "generalHelpTooltip"));
    elements.menuAbout.addEventListener("click", () => showInfo("TAcroMan", text("aboutText"), "aboutHelpTooltip"));
    elements.toolClose.addEventListener("click", () => elements.toolDialog.close());
    elements.desktopMenubar.addEventListener("click", (event) => {
      if (event.target.closest("button")) closeMenus();
    });
    for (const menu of elements.desktopMenubar.querySelectorAll(".menu")) {
      menu.addEventListener("toggle", () => {
        if (!menu.open) return;
        for (const other of elements.desktopMenubar.querySelectorAll(".menu[open]")) {
          if (other !== menu) other.removeAttribute("open");
        }
      });
    }
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".menu")) closeMenus();
    });
    elements.profileSelect.addEventListener("change", () => {
      if (!confirmDiscard()) {
        applySnapshot(snapshot, "initial");
        return;
      }
      selectedUid = null;
      draftCommandId = null;
      dirty = false;
      host.postMessage({ type: "selectProfile", profileId: elements.profileSelect.value });
      setStatus(text("changingProfile"), "info");
    });
    elements.reloadConflict.addEventListener("click", () => {
      if (!deferredSnapshot || !confirmDiscard()) return;
      selectedUid = null;
      dirty = false;
      applySnapshot(deferredSnapshot, "external");
    });
    window.addEventListener("message", (event) => {
      const message = event.data;
      if (message?.type === "snapshot") applySnapshot(message.snapshot, message.reason);
      if (message?.type === "error") {
        setStatus(message.message, "error");
        if (elements.toolDialog.open) {
          const error = el("div", "tool-status", message.message);
          error.dataset.kind = "error";
          elements.toolBody.append(error);
        }
      }
      if (message?.type === "profileEditor") {
        profileEditorState = message;
        renderProfileEditor(message.selectedProfileId);
      }
      if (message?.type === "toolPaths") {
        if (citationState && ["oldBib", "newBib", "texFiles", "texFolder"].includes(message.target)) {
          if (message.target === "oldBib" || message.target === "newBib") citationState[message.target] = message.paths[0] || "";
          else citationState.texFiles = [...new Set([...citationState.texFiles, ...message.paths])].sort();
          renderCitationTool();
        }
        if (auditState && message.target === "auditProject") {
          auditState.project = message.paths[0] || "";
          auditState.reference = "";
          auditState.referenceFiles = [];
          auditState.report = null;
          renderAuditTool();
          if (auditState.project) host.postMessage({ type: "discoverReferences", project: auditState.project });
        }
        if (auditState && message.target === "auditReference") {
          auditState.reference = message.paths[0] || "";
          auditState.report = null;
          renderAuditTool();
        }
      }
      if (message?.type === "citationAnalysis" && citationState) {
        citationState.matches = message.matches.map((match) => ({
          ...match,
          selected: match.status === "matched" && match.old_key !== match.new_key,
        }));
        citationState.summary = message.summary;
        renderCitationTool();
      }
      if (message?.type === "citationMigrationResult" && citationState) {
        citationState.result = `${message.replacements} replacements in ${message.filesChanged} of ${message.filesConsidered} files.`;
        renderCitationTool();
      }
      if (message?.type === "referenceFiles" && auditState) {
        auditState.project = message.project;
        auditState.referenceFiles = message.paths;
        if (!auditState.reference || !message.paths.includes(auditState.reference)) auditState.reference = message.paths[0] || "";
        renderAuditTool();
      }
      if (message?.type === "referenceAudit" && auditState) {
        auditState.report = message;
        renderAuditTool();
      }
    });
    window.addEventListener("pywebviewready", () => {
      while (queuedDesktopMessages.length) host.postMessage(queuedDesktopMessages.shift());
    });
    host.postMessage({ type: "ready" });
  }

  document.addEventListener("DOMContentLoaded", initialize);
}());
