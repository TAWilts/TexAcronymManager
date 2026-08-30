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
    return !dirty || window.confirm("Discard the unsaved changes?");
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
      elements.entryList.append(el("div", "empty", query ? "No matching entries" : "No entries yet"));
      return;
    }
    for (const entry of entries) {
      const button = el("button", `entry-row${entry.uid === selectedUid ? " selected" : ""}`);
      button.type = "button";
      button.addEventListener("click", () => selectEntry(entry.uid));
      const title = el("span", "entry-title", primaryValue(entry) || "Untitled entry");
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
      setStatus("Unsaved changes", "warning");
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
    elements.formTitle.textContent = entry ? "Edit entry" : "New entry";
    elements.formDescription.textContent = command?.description
      || (entry ? "This entry type is not part of the active profile." : "");
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
    elements.databasePath.textContent = next.databasePath;
    elements.databasePath.title = next.databasePath;
    elements.outputPath.textContent = next.outputPath || "No generated output selected";
    elements.profileSelect.replaceChildren();
    for (const profile of next.profiles || [{ id: next.profile.id, name: next.profile.name }]) {
      const option = el("option", "", profile.name);
      option.value = profile.id;
      option.selected = profile.id === next.profile.id;
      elements.profileSelect.append(option);
    }
    elements.openDesktop.hidden = next.hostKind === "desktop";
    if (selectedUid && !next.entries.some((entry) => entry.uid === selectedUid)) selectedUid = null;
    if (selectedUid) draftCommandId = next.entries.find((entry) => entry.uid === selectedUid)?.commandId || null;
    dirty = false;
    renderList();
    renderForm();
    if (reason === "mutation") setStatus("Saved", "success");
    else if (reason === "external") setStatus("Database reloaded", "info");
    else setStatus("Ready", "info");
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
    setStatus("Saving…", "info");
  }

  function deleteEntry() {
    if (!snapshot || !selectedUid || !window.confirm("Delete this entry?")) return;
    host.postMessage({ type: "deleteEntry", revision: snapshot.revision, uid: selectedUid });
    setStatus("Deleting…", "info");
  }

  function initialize() {
    for (const id of [
      "database-path", "output-path", "profile-select", "search", "count", "entry-list", "editor-form",
      "form-title", "form-description", "command", "form-fields", "new-button", "delete-button",
      "save-button", "select-database", "select-output", "open-desktop", "status", "conflict", "reload-conflict",
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
    elements.profileSelect.addEventListener("change", () => {
      if (!confirmDiscard()) {
        applySnapshot(snapshot, "initial");
        return;
      }
      selectedUid = null;
      draftCommandId = null;
      dirty = false;
      host.postMessage({ type: "selectProfile", profileId: elements.profileSelect.value });
      setStatus("Changing profile…", "info");
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
