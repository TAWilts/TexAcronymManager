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

  const texts = {
    en: {
      menuFile: "File", openDatabase: "Open database…", newDatabase: "New database…",
      importTex: "Import TeX file…", writeOutput: "Write output file", exit: "Exit",
      menuProfiles: "Profiles", editProfile: "Edit active profile…", selectProfiles: "Choose profile file…",
      menuTools: "Tools", citationMigration: "Migrate citation keys…", referenceAudit: "Audit references…",
      menuLanguage: "Language", menuHelp: "Help", help: "Help", about: "About TAcroMan", close: "Close",
      helpTitle: "TAcroMan help",
      helpText: "Select or create a database, choose a profile and edit entries in the form. Changes are written to the JSON database and generated output. The profile editor and bibliography tools currently open as classic tool windows.",
      aboutText: "TAcroMan manages profile-defined LaTeX commands from one shared database.",
      databaseLabel: "Database:", outputLabel: "Output:", selectDatabase: "Select database",
      selectOutput: "Select output", desktopApp: "Desktop app", searchEntries: "Search entries",
      conflict: "The database changed outside this editor.", reload: "Reload", newEntry: "New entry",
      editEntry: "Edit entry", type: "Type", save: "Save", new: "New", delete: "Delete", loading: "Loading…",
      noOutput: "No generated output selected", noMatches: "No matching entries", noEntries: "No entries yet",
      untitled: "Untitled entry", discard: "Discard the unsaved changes?", unsupported: "This entry type is not part of the active profile.",
      unsaved: "Unsaved changes", saved: "Saved", reloaded: "Database reloaded", ready: "Ready",
      saving: "Saving…", deleting: "Deleting…", deleteConfirm: "Delete this entry?", changingProfile: "Changing profile…",
      importing: "Importing…",
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
      helpText: "Wähle oder erstelle eine Datenbank, wähle ein Profil und bearbeite die Einträge in der Eingabemaske. Änderungen werden in die JSON-Datenbank und die generierte Ausgabedatei geschrieben. Profil- und Literaturwerkzeuge öffnen derzeit als klassische Werkzeugfenster.",
      aboutText: "TAcroMan verwaltet profildefinierte LaTeX-Befehle aus einer gemeinsamen Datenbank.",
      databaseLabel: "Datenbank:", outputLabel: "Ausgabe:", selectDatabase: "Datenbank auswählen",
      selectOutput: "Ausgabe auswählen", desktopApp: "Desktop-App", searchEntries: "Einträge durchsuchen",
      conflict: "Die Datenbank wurde außerhalb dieses Editors geändert.", reload: "Neu laden", newEntry: "Neuer Eintrag",
      editEntry: "Eintrag bearbeiten", type: "Typ", save: "Speichern", new: "Neu", delete: "Löschen", loading: "Laden…",
      noOutput: "Keine Ausgabedatei ausgewählt", noMatches: "Keine passenden Einträge", noEntries: "Noch keine Einträge",
      untitled: "Unbenannter Eintrag", discard: "Ungespeicherte Änderungen verwerfen?", unsupported: "Dieser Eintragstyp gehört nicht zum aktiven Profil.",
      unsaved: "Ungespeicherte Änderungen", saved: "Gespeichert", reloaded: "Datenbank neu geladen", ready: "Bereit",
      saving: "Wird gespeichert…", deleting: "Wird gelöscht…", deleteConfirm: "Diesen Eintrag löschen?", changingProfile: "Profil wird gewechselt…",
      importing: "Import läuft…",
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

  function showInfo(title, content) {
    elements.infoTitle.textContent = title;
    elements.infoContent.textContent = content;
    elements.infoDialog.showModal();
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
    elements.menuEditProfile.addEventListener("click", () => host.postMessage({ type: "runLegacyTool", action: "profile-editor" }));
    elements.menuSelectProfiles.addEventListener("click", () => host.postMessage({ type: "selectProfiles" }));
    elements.menuCitationMigration.addEventListener("click", () => host.postMessage({ type: "runLegacyTool", action: "citation-migration" }));
    elements.menuReferenceAudit.addEventListener("click", () => host.postMessage({ type: "runLegacyTool", action: "reference-audit" }));
    elements.menuLanguageDe.addEventListener("click", () => host.postMessage({ type: "setLanguage", language: "de" }));
    elements.menuLanguageEn.addEventListener("click", () => host.postMessage({ type: "setLanguage", language: "en" }));
    elements.menuHelp.addEventListener("click", () => showInfo(text("helpTitle"), text("helpText")));
    elements.menuAbout.addEventListener("click", () => showInfo("TAcroMan", text("aboutText")));
    elements.desktopMenubar.addEventListener("click", (event) => {
      if (event.target.closest("button")) closeMenus();
    });
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
      if (message?.type === "error") setStatus(message.message, "error");
    });
    window.addEventListener("pywebviewready", () => {
      while (queuedDesktopMessages.length) host.postMessage(queuedDesktopMessages.shift());
    });
    host.postMessage({ type: "ready" });
  }

  document.addEventListener("DOMContentLoaded", initialize);
}());
