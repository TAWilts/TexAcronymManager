"""Tkinter desktop application driven by generic command-definition profiles."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from .i18n import DEFAULT_LANGUAGE, normalize_language, translate
from .importing import parse_acronym_package, read_tex_file
from .model import (
    CommandEntry,
    acronym_to_entry,
    command_fields,
    command_map,
    comparison_matches,
    similarity_matches,
    validate_entry,
)
from .profiles import load_profiles, normalise_profile, save_profiles
from .rendering import profile_template_warnings, render, rendered_entries, usage_for
from .storage import atomic_write_text, load_database, load_settings, save_database, save_settings


APP_NAME = "TAcroMan"
SETTINGS_FILENAME = "tacroman-settings.json"
LEGACY_SETTINGS_FILENAME = "acronym-manager-settings.json"
PROFILE_FILENAME = "tacroman-render-profiles.json"


def _default_database_path() -> Path:
    return Path.home() / APP_NAME / "entries.json"


@dataclass
class CommandForm:
    """Widgets and values belonging to one profile-defined command tab."""

    command: dict[str, object]
    variables: dict[str, tk.StringVar]
    text_widgets: dict[str, ScrolledText]
    validation_var: tk.StringVar
    validation_label: ttk.Label
    save_button: ttk.Button
    first_widget: tk.Widget | None

    @property
    def command_id(self) -> str:
        return str(self.command["id"])

    def values(self) -> dict[str, str]:
        result = {field_id: variable.get() for field_id, variable in self.variables.items()}
        result.update({field_id: widget.get("1.0", "end-1c") for field_id, widget in self.text_widgets.items()})
        return result

    def set_values(self, values: dict[str, str]) -> None:
        for field_id, variable in self.variables.items():
            variable.set(values.get(field_id, ""))
        for field_id, widget in self.text_widgets.items():
            widget.delete("1.0", "end")
            widget.insert("1.0", values.get(field_id, ""))

    def clear(self) -> None:
        self.set_values({})


class TAcroManApp(tk.Tk):
    """A local JSON-backed manager with fully profile-defined command forms."""

    def __init__(self, database_path: Path, output_path: Path | None, profiles_path: Path | None) -> None:
        super().__init__()
        self.minsize(1020, 650)
        self.geometry("1220x760")

        self.database_path = database_path.expanduser().resolve()
        settings = self._load_workspace_settings(self.database_path)
        self.output_path = (
            output_path.expanduser().resolve()
            if output_path
            else Path(settings.get("output_path", self.database_path.with_suffix(".tex"))).expanduser()
        )
        self.profiles_path = (
            profiles_path.expanduser().resolve()
            if profiles_path
            else Path(settings.get("profiles_path", self.database_path.parent / PROFILE_FILENAME)).expanduser()
        )

        self.entries: list[CommandEntry] = []
        self.profiles: list[dict[str, object]] = []
        self.editing_uid: str | None = None
        self.current_command_id = ""
        self.command_forms: dict[str, CommandForm] = {}
        self.command_tab_ids: dict[str, str] = {}
        self._ui_ready = False
        self._language_refresh_after_id: str | None = None
        self._rendered_language = ""
        self._suppress_command_change = False

        self.database_path_var = tk.StringVar(value=str(self.database_path))
        self.output_path_var = tk.StringVar(value=str(self.output_path))
        self.search_var = tk.StringVar()
        self.profile_var = tk.StringVar(value=str(settings.get("selected_profile_id", "acronym-package")))
        self.profile_display_var = tk.StringVar()
        self.language_var = tk.StringVar(value=normalize_language(str(settings.get("language", DEFAULT_LANGUAGE))))
        self.output_status_var = tk.StringVar()

        self.search_var.trace_add("write", lambda *_: self._refresh_table())
        self._build_ui()
        self._load_workspace(initial=True)
        self._ui_ready = True
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    @property
    def language(self) -> str:
        return normalize_language(self.language_var.get())

    def t(self, key: str, **values: object) -> str:
        return translate(self.language, key, **values)

    @staticmethod
    def _settings_path_for(database_path: Path) -> Path:
        return database_path.parent / SETTINGS_FILENAME

    @staticmethod
    def _legacy_settings_path_for(database_path: Path) -> Path:
        return database_path.parent / LEGACY_SETTINGS_FILENAME

    def _load_workspace_settings(self, database_path: Path) -> dict[str, object]:
        current_path = self._settings_path_for(database_path)
        if current_path.exists():
            return load_settings(current_path)
        legacy_path = self._legacy_settings_path_for(database_path)
        return load_settings(legacy_path) if legacy_path.exists() else {}

    def _build_ui(self) -> None:
        """Rebuild the user interface while retaining unsaved form values."""
        form_snapshot = {command_id: form.values() for command_id, form in self.command_forms.items()}
        previous_command_id = self.current_command_id
        if hasattr(self, "content"):
            self.content.destroy()

        self.title(self.t("app_title"))
        self._build_menu()
        self.content = ttk.Frame(self)
        self.content.pack(fill="both", expand=True)
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(3, weight=1)

        self._build_workspace_controls(self.content)
        self._build_body(self.content)
        self._update_profile_combo()
        if self.command_forms:
            requested = previous_command_id if previous_command_id in self.command_forms else next(iter(self.command_forms))
            self._select_command(requested)
            for command_id, values in form_snapshot.items():
                if command_id in self.command_forms:
                    self.command_forms[command_id].set_values(values)
            self._update_validation(requested)
        self._refresh_table()
        self._rendered_language = self.language

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label=self.t("menu_open_database"), command=self._choose_database)
        file_menu.add_command(label=self.t("menu_new_database"), command=self._new_database)
        file_menu.add_separator()
        file_menu.add_command(label=self.t("menu_import_tex"), command=self._import_tex_file)
        file_menu.add_command(label=self.t("menu_write_output"), command=lambda: self._write_output(show_success=True))
        file_menu.add_separator()
        file_menu.add_command(label=self.t("menu_exit"), command=self.destroy)
        menu.add_cascade(label=self.t("menu_file"), menu=file_menu)

        profile_menu = tk.Menu(menu, tearoff=False)
        profile_menu.add_command(label=self.t("menu_edit_profile"), command=self._open_profile_editor)
        profile_menu.add_command(label=self.t("menu_select_profile_file"), command=self._choose_profiles_file)
        menu.add_cascade(label=self.t("menu_profiles"), menu=profile_menu)

        language_menu = tk.Menu(menu, tearoff=False)
        language_menu.add_radiobutton(label="Deutsch", value="de", variable=self.language_var, command=self._request_language_refresh)
        language_menu.add_radiobutton(label="English", value="en", variable=self.language_var, command=self._request_language_refresh)
        menu.add_cascade(label=self.t("menu_language"), menu=language_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label=self.t("menu_help"), command=self._show_help)
        help_menu.add_command(label=self.t("menu_about"), command=self._show_about)
        menu.add_cascade(label=self.t("menu_help"), menu=help_menu)
        self.config(menu=menu)

    def _build_workspace_controls(self, parent: ttk.Frame) -> None:
        outer = ttk.Frame(parent, padding=12)
        outer.grid(row=0, column=0, rowspan=3, sticky="new")
        outer.columnconfigure(1, weight=1)

        ttk.Label(outer, text=self.t("database_label")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(outer, textvariable=self.database_path_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(outer, text=self.t("open"), command=self._choose_database).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(outer, text=self.t("new"), command=self._new_database).grid(row=0, column=3, padx=(6, 0))

        ttk.Label(outer, text=self.t("output_label")).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(7, 0))
        ttk.Entry(outer, textvariable=self.output_path_var).grid(row=1, column=1, sticky="ew", pady=(7, 0))
        ttk.Button(outer, text=self.t("target"), command=self._choose_output).grid(row=1, column=2, padx=(8, 0), pady=(7, 0))
        ttk.Button(outer, text=self.t("write_now"), command=lambda: self._write_output(show_success=True)).grid(
            row=1, column=3, padx=(6, 0), pady=(7, 0)
        )

        ttk.Label(outer, text=self.t("output_format")).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        self.profile_combo = ttk.Combobox(outer, textvariable=self.profile_display_var, state="readonly", width=50)
        self.profile_combo.grid(row=2, column=1, sticky="w", pady=(10, 0))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_profile_changed())
        ttk.Button(outer, text=self.t("edit_format"), command=self._open_profile_editor).grid(row=2, column=2, columnspan=2, padx=(8, 0), pady=(10, 0))
        ttk.Label(outer, textvariable=self.output_status_var, foreground="#336633", wraplength=950).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(5, 0)
        )

    def _build_body(self, parent: ttk.Frame) -> None:
        body = ttk.PanedWindow(parent, orient="horizontal")
        body.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))
        list_frame = ttk.Frame(body, padding=(0, 0, 12, 0))
        editor_frame = ttk.LabelFrame(body, text=self.t("edit_entry"), padding=10)
        body.add(list_frame, weight=3)
        body.add(editor_frame, weight=2)
        self._build_list(list_frame)
        self._build_command_editor(editor_frame)

    def _build_list(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        search = ttk.Frame(parent)
        search.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text=self.t("search")).grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(search, textvariable=self.search_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(search, text="✕", width=3, command=lambda: self.search_var.set("")).grid(row=0, column=2, padx=(6, 0))

        columns = ("command", "key", "details")
        self.tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("command", text=self.t("command"))
        self.tree.heading("key", text=self.t("key"))
        self.tree.heading("details", text=self.t("details"))
        self.tree.column("command", width=145, stretch=False)
        self.tree.column("key", width=145, stretch=False)
        self.tree.column("details", width=360, stretch=True)
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(parent)
        buttons.grid(row=2, column=0, sticky="ew", pady=(9, 0))
        ttk.Button(buttons, text=self.t("new_entry"), command=self._start_new_entry).pack(side="left")
        ttk.Button(buttons, text=self.t("delete"), command=self._delete_selected).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text=self.t("preview"), command=self._preview_output).pack(side="right")
        ttk.Label(buttons, text=self.t("select_to_edit")).pack(side="right", padx=(0, 12))

    def _build_command_editor(self, parent: ttk.LabelFrame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.command_forms = {}
        self.command_tab_ids = {}
        if not self.profiles:
            ttk.Label(parent, text=self.t("no_profile_commands"), wraplength=350).grid(row=0, column=0, sticky="nsew")
            return

        self.command_notebook = ttk.Notebook(parent)
        self.command_notebook.grid(row=0, column=0, sticky="nsew")
        self.command_notebook.bind("<<NotebookTabChanged>>", self._on_command_changed)
        for command in self._active_profile().get("commands", []):
            if not isinstance(command, dict):
                continue
            self._add_command_tab(command)

    def _add_command_tab(self, command: dict[str, object]) -> None:
        command_id = str(command["id"])
        tab = ttk.Frame(self.command_notebook, padding=8)
        tab.columnconfigure(0, weight=1)
        row = 0
        variables: dict[str, tk.StringVar] = {}
        text_widgets: dict[str, ScrolledText] = {}
        first_widget: tk.Widget | None = None
        for field in command_fields(command):
            field_id = str(field["id"])
            label = self._field_label(field)
            if bool(field.get("required")):
                label = f"{label} *"
            ttk.Label(tab, text=label).grid(row=row, column=0, sticky="w")
            row += 1
            if bool(field.get("multiline")):
                widget = ScrolledText(tab, height=4, wrap="word", font="TkDefaultFont")
                widget.grid(row=row, column=0, sticky="ew", pady=(3, 8))
                widget.bind("<KeyRelease>", lambda _event, command_id=command_id: self._update_validation(command_id))
                widget.bind("<<Paste>>", lambda _event, command_id=command_id: self.after_idle(lambda: self._update_validation(command_id)))
                text_widgets[field_id] = widget
            else:
                variable = tk.StringVar()
                variable.trace_add("write", lambda *_args, command_id=command_id: self._update_validation(command_id))
                widget = ttk.Entry(tab, textvariable=variable)
                widget.grid(row=row, column=0, sticky="ew", pady=(3, 8))
                widget.bind("<Return>", lambda _event, command_id=command_id: self._save_editor(command_id))
                variables[field_id] = variable
            if first_widget is None:
                first_widget = widget
            row += 1

        validation_var = tk.StringVar(value=self.t("ready"))
        validation_label = ttk.Label(tab, textvariable=validation_var, foreground="#336633", wraplength=340)
        validation_label.grid(row=row, column=0, sticky="ew", pady=(1, 8))
        row += 1
        actions = ttk.Frame(tab)
        actions.grid(row=row, column=0, sticky="ew")
        save_button = ttk.Button(actions, text=self.t("add_entry"), command=lambda command_id=command_id: self._save_editor(command_id))
        save_button.pack(side="left")
        ttk.Button(actions, text=self.t("clear"), command=lambda command_id=command_id: self._start_new_entry(command_id)).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text=self.t("copy_usage"), command=lambda command_id=command_id: self._copy_usage(command_id)).pack(side="right")

        form = CommandForm(command, variables, text_widgets, validation_var, validation_label, save_button, first_widget)
        self.command_forms[command_id] = form
        self.command_notebook.add(tab, text=str(command.get("label") or command_id))
        self.command_tab_ids[command_id] = str(tab)

    def _field_label(self, field: dict[str, object]) -> str:
        field_id = str(field["id"])
        common = {
            "short": "field_short",
            "long": "field_long",
            "key": "field_key",
            "category": "field_category",
            "note": "field_note",
            "short_plural": "field_short_plural",
            "long_plural": "field_long_plural",
        }
        return self.t(common[field_id]) if field_id in common else str(field.get("label") or field_id)

    def _load_workspace(self, *, initial: bool = False) -> None:
        try:
            self.entries = load_database(self.database_path, language=self.language)
            self.profiles = load_profiles(self.profiles_path, language=self.language)
        except (OSError, ValueError) as error:
            messagebox.showerror(APP_NAME, str(error))
            if not initial:
                return
            self.entries = []
            self.profiles = load_profiles(language=self.language)
        self._build_ui()
        self._start_new_entry()
        self.output_status_var.set(self.t("entries_loaded", count=len(self.entries)))

    def _update_profile_combo(self) -> None:
        if not hasattr(self, "profile_combo"):
            return
        if not self.profiles:
            self.profile_combo["values"] = ()
            self.profile_display_var.set("")
            return
        labels = [f"{profile['name']}  [{profile['id']}]" for profile in self.profiles]
        self.profile_combo["values"] = labels
        profile_ids = {str(profile["id"]) for profile in self.profiles}
        if self.profile_var.get() not in profile_ids:
            self.profile_var.set("acronym-package" if "acronym-package" in profile_ids else str(self.profiles[0]["id"]))
        active_id = self.profile_var.get()
        self.profile_display_var.set(next(label for label in labels if label.endswith(f"[{active_id}]")))

    def _active_profile(self) -> dict[str, object]:
        if not self.profiles:
            return {"id": "", "name": "", "commands": []}
        profile_ids = {str(profile["id"]) for profile in self.profiles}
        if self.profile_var.get() not in profile_ids:
            self.profile_var.set("acronym-package" if "acronym-package" in profile_ids else str(self.profiles[0]["id"]))
        selected = self.profile_display_var.get()
        if "[" in selected:
            selected_id = selected.rsplit("[", 1)[-1].rstrip("]")
            if selected_id in profile_ids:
                self.profile_var.set(selected_id)
        return next(profile for profile in self.profiles if str(profile["id"]) == self.profile_var.get())

    def _visible_command_map(self) -> dict[str, dict[str, object]]:
        return command_map(self._active_profile())

    def _filtered_entries(self) -> list[CommandEntry]:
        commands = self._visible_command_map()
        query = self.search_var.get().strip().casefold()
        ordered = sorted(
            (entry for entry in self.entries if entry.command_id in commands),
            key=lambda entry: (entry.command_id.casefold(), self._entry_key(entry, commands[entry.command_id]).casefold()),
        )
        if not query:
            return ordered
        return [
            entry
            for entry in ordered
            if query in entry.command_id.casefold()
            or any(query in value.casefold() for value in entry.values.values())
        ]

    def _entry_key(self, entry: CommandEntry, command: dict[str, object]) -> str:
        comparison_field = next(
            (field for field in command_fields(command) if str(field.get("comparison_group", "")).strip()),
            None,
        )
        if comparison_field:
            return entry.value(str(comparison_field["id"])).strip()
        fields = command_fields(command)
        return entry.value(str(fields[0]["id"])).strip() if fields else ""

    def _entry_details(self, entry: CommandEntry, command: dict[str, object]) -> str:
        key = self._entry_key(entry, command)
        values = [value.strip().replace("\n", " ") for value in entry.values.values() if value.strip() and value.strip() != key]
        return " · ".join(values[:2])

    def _refresh_table(self) -> None:
        if not hasattr(self, "tree"):
            return
        selected = self.editing_uid
        self.tree.delete(*self.tree.get_children())
        commands = self._visible_command_map()
        for entry in self._filtered_entries():
            command = commands[entry.command_id]
            self.tree.insert(
                "",
                "end",
                iid=entry.uid,
                values=(str(command.get("label") or entry.command_id), self._entry_key(entry, command), self._entry_details(entry, command)),
            )
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.focus(selected)

    def _on_tree_select(self, _event: object | None = None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        entry = next((item for item in self.entries if item.uid == selection[0]), None)
        if entry is None or entry.command_id not in self.command_forms:
            return
        self.editing_uid = entry.uid
        self._select_command(entry.command_id)
        form = self.command_forms[entry.command_id]
        form.set_values(entry.values)
        form.save_button.config(text=self.t("save_changes"))
        self._update_validation(entry.command_id)

    def _on_command_changed(self, _event: object | None = None) -> None:
        if self._suppress_command_change or not hasattr(self, "command_notebook"):
            return
        tab_id = self.command_notebook.select()
        command_id = next((key for key, value in self.command_tab_ids.items() if value == tab_id), "")
        if not command_id:
            return
        self.current_command_id = command_id
        current_entry = next((entry for entry in self.entries if entry.uid == self.editing_uid), None)
        if current_entry and current_entry.command_id != command_id:
            self._start_new_entry(command_id)
        else:
            self._update_validation(command_id)

    def _select_command(self, command_id: str) -> None:
        if command_id not in self.command_tab_ids:
            return
        self._suppress_command_change = True
        self.command_notebook.select(self.command_tab_ids[command_id])
        self._suppress_command_change = False
        self.current_command_id = command_id

    def _candidate_from_form(self, command_id: str) -> CommandEntry:
        form = self.command_forms[command_id]
        existing = next((entry for entry in self.entries if entry.uid == self.editing_uid), None)
        uid = self.editing_uid if existing and existing.command_id == command_id else None
        return CommandEntry(command_id=command_id, values=form.values(), uid=uid or CommandEntry(command_id).uid)

    def _update_validation(self, command_id: str | None = None) -> None:
        command_id = command_id or self.current_command_id
        if command_id not in self.command_forms:
            return
        form = self.command_forms[command_id]
        candidate = self._candidate_from_form(command_id)
        if not any(value.strip() for value in candidate.values.values()):
            form.validation_label.config(foreground="#336633")
            form.validation_var.set(self.t("ready"))
            return

        commands = self._visible_command_map()
        errors, formatting_warnings = validate_entry(candidate, form.command, language=self.language)
        same_command, other_command = comparison_matches(candidate, form.command, self.entries, commands, ignore_uid=candidate.uid)
        similar = similarity_matches(candidate, form.command, self.entries, commands, ignore_uid=candidate.uid)
        messages: list[str] = []
        if same_command:
            messages.append(self.t("duplicate_same_command_live", entries=self._matches_text(same_command)))
        if other_command:
            messages.append(self.t("duplicate_other_command_live", entries=self._matches_text(other_command)))
        if similar:
            messages.append(self.t("similar_live", entries=self._similar_text(similar)))
        messages.extend(errors)
        messages.extend(formatting_warnings)
        if same_command or errors:
            form.validation_label.config(foreground="#aa2222")
        elif other_command or similar or formatting_warnings:
            form.validation_label.config(foreground="#885500")
        else:
            form.validation_label.config(foreground="#336633")
            messages.append(self.t("format_valid"))
        form.validation_var.set(" • ".join(dict.fromkeys(messages)))

    def _matches_text(self, matches: list[Any]) -> str:
        commands = self._visible_command_map()
        return ", ".join(
            f"{commands.get(match.entry.command_id, {}).get('label', match.entry.command_id)}: {match.entry.value(match.matched_field_id)}"
            for match in matches[:3]
        )

    def _similar_text(self, matches: list[Any]) -> str:
        commands = self._visible_command_map()
        return ", ".join(
            f"{commands.get(match.entry.command_id, {}).get('label', match.entry.command_id)}: {match.entry.value(match.matched_field_id)} ({match.score:.0%})"
            for match in matches[:3]
        )

    def _save_editor(self, command_id: str | None = None) -> str | None:
        command_id = command_id or self.current_command_id
        if command_id not in self.command_forms:
            return "break"
        form = self.command_forms[command_id]
        candidate = self._candidate_from_form(command_id)
        errors, formatting_warnings = validate_entry(candidate, form.command, language=self.language)
        if errors:
            messagebox.showerror(APP_NAME, "\n".join(errors))
            return "break"
        same_command, _other_command = comparison_matches(
            candidate, form.command, self.entries, self._visible_command_map(), ignore_uid=candidate.uid
        )
        if same_command:
            messagebox.showerror(APP_NAME, self.t("duplicate_same_command_error", entries=self._matches_text(same_command)))
            return "break"
        if formatting_warnings and not messagebox.askyesno(
            APP_NAME, self.t("format_confirm", warnings="\n".join(formatting_warnings))
        ):
            return "break"

        was_editing = candidate.uid in {entry.uid for entry in self.entries}
        if was_editing:
            self.entries = [candidate if entry.uid == candidate.uid else entry for entry in self.entries]
        else:
            self.entries.append(candidate)
        if self._persist_and_render():
            self.editing_uid = None
            self._refresh_table()
            self._start_new_entry(command_id)
            self.output_status_var.set(self.t("entry_updated" if was_editing else "entry_added"))
        return "break"

    def _start_new_entry(self, command_id: str | None = None) -> None:
        if not self.command_forms:
            return
        desired = command_id or self.current_command_id or next(iter(self.command_forms))
        self.editing_uid = None
        for form in self.command_forms.values():
            form.clear()
            form.save_button.config(text=self.t("add_entry"))
        self._select_command(desired)
        if hasattr(self, "tree"):
            self.tree.selection_remove(self.tree.selection())
        self._update_validation(desired)
        first_widget = self.command_forms[desired].first_widget
        if first_widget is not None:
            self.after_idle(first_widget.focus_set)

    def _delete_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(APP_NAME, self.t("select_entry_first"))
            return
        entry = next((item for item in self.entries if item.uid == selection[0]), None)
        if entry is None:
            return
        if not messagebox.askyesno(APP_NAME, self.t("confirm_delete", key=self._entry_key(entry, self._visible_command_map()[entry.command_id]))):
            return
        self.entries = [item for item in self.entries if item.uid != entry.uid]
        self._start_new_entry()
        if self._persist_and_render():
            self._refresh_table()

    def _persist_and_render(self) -> bool:
        try:
            self.database_path = Path(self.database_path_var.get()).expanduser().resolve()
            self.output_path = Path(self.output_path_var.get()).expanduser().resolve()
            save_database(self.database_path, self.entries)
            self._save_workspace_settings()
            return self._write_output(show_success=False)
        except OSError as error:
            messagebox.showerror(APP_NAME, self.t("file_write_failed", error=error))
            return False

    def _write_output(self, *, show_success: bool) -> bool:
        try:
            self.output_path = Path(self.output_path_var.get()).expanduser().resolve()
            profile = self._active_profile()
            warnings = profile_template_warnings(profile, language=self.language)
            if warnings:
                messagebox.showwarning(APP_NAME, self.t("profile_warning", warnings="\n".join(warnings)))
            rendered = rendered_entries(self.entries, profile)
            atomic_write_text(self.output_path, render(self.entries, profile))
            self._save_workspace_settings()
            omitted = len(self.entries) - len(rendered)
            status_key = "output_status_written_with_omitted" if omitted else "output_status_written"
            self.output_status_var.set(self.t(status_key, path=self.output_path, count=omitted))
            if show_success:
                messagebox.showinfo(APP_NAME, self.t("output_written", count=len(rendered), path=self.output_path))
            return True
        except (OSError, KeyError, ValueError) as error:
            self.output_status_var.set(self.t("output_failed"))
            if show_success:
                messagebox.showerror(APP_NAME, self.t("file_write_failed", error=error))
            return False

    def _save_workspace_settings(self) -> None:
        settings = {
            "output_path": str(self.output_path),
            "profiles_path": str(self.profiles_path),
            "selected_profile_id": self.profile_var.get() if self.profiles else "acronym-package",
            "language": self.language,
        }
        save_settings(self._settings_path_for(self.database_path), settings)

    def _choose_database(self) -> None:
        selected = filedialog.askopenfilename(
            title=self.t("open_database_title"),
            filetypes=[(self.t("json_files"), "*.json"), (self.t("all_files"), "*.*")],
        )
        if not selected:
            return
        self.database_path = Path(selected).expanduser().resolve()
        settings = self._load_workspace_settings(self.database_path)
        self._ui_ready = False
        self.database_path_var.set(str(self.database_path))
        self.output_path = Path(settings.get("output_path", self.database_path.with_suffix(".tex"))).expanduser()
        self.output_path_var.set(str(self.output_path))
        self.profiles_path = Path(settings.get("profiles_path", self.database_path.parent / PROFILE_FILENAME)).expanduser()
        self.profile_var.set(str(settings.get("selected_profile_id", "acronym-package")))
        self.language_var.set(normalize_language(str(settings.get("language", self.language))))
        self.entries = []
        self.profiles = []
        self._load_workspace()
        self._ui_ready = True

    def _new_database(self) -> None:
        selected = filedialog.asksaveasfilename(
            title=self.t("new_database_title"),
            defaultextension=".json",
            initialfile="entries.json",
            filetypes=[(self.t("json_files"), "*.json")],
        )
        if not selected:
            return
        self.database_path = Path(selected).expanduser().resolve()
        self.database_path_var.set(str(self.database_path))
        self.output_path = self.database_path.with_suffix(".tex")
        self.output_path_var.set(str(self.output_path))
        self.profiles_path = self.database_path.parent / PROFILE_FILENAME
        self.entries = []
        self.profiles = load_profiles(self.profiles_path, language=self.language)
        self.profile_var.set("acronym-package")
        self._build_ui()
        self._start_new_entry()
        try:
            save_database(self.database_path, self.entries)
            self._write_output(show_success=False)
            self.output_status_var.set(self.t("new_database_status", path=self.database_path))
        except OSError as error:
            messagebox.showerror(APP_NAME, self.t("database_create_failed", error=error))

    def _choose_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            title=self.t("choose_output_title"),
            initialfile=self.output_path.name,
            defaultextension=".tex",
            filetypes=[(self.t("tex_files"), "*.tex"), (self.t("csv_files"), "*.csv"), (self.t("all_files"), "*.*")],
        )
        if not selected:
            return
        self.output_path = Path(selected).expanduser().resolve()
        self.output_path_var.set(str(self.output_path))
        self._write_output(show_success=False)

    def _choose_profiles_file(self) -> None:
        selected = filedialog.askopenfilename(
            title=self.t("choose_profiles_title"),
            filetypes=[(self.t("json_files"), "*.json"), (self.t("all_files"), "*.*")],
        )
        if not selected:
            return
        self.profiles_path = Path(selected).expanduser().resolve()
        try:
            self.profiles = load_profiles(self.profiles_path, language=self.language)
        except (OSError, ValueError) as error:
            messagebox.showerror(APP_NAME, str(error))
            return
        self._build_ui()
        self._start_new_entry()
        self._save_workspace_settings()

    def _import_tex_file(self) -> None:
        selected = filedialog.askopenfilename(
            title=self.t("import_tex_title"),
            filetypes=[(self.t("tex_files"), "*.tex"), (self.t("all_files"), "*.*")],
        )
        if not selected:
            return
        if "acronym" not in self._visible_command_map():
            messagebox.showwarning(APP_NAME, self.t("import_profile_unsupported"))
            return
        try:
            imported = [acronym_to_entry(item) for item in parse_acronym_package(read_tex_file(Path(selected)))]
        except (OSError, UnicodeDecodeError) as error:
            messagebox.showerror(APP_NAME, self.t("file_read_failed", error=error))
            return
        if not imported:
            messagebox.showwarning(APP_NAME, self.t("no_definitions"))
            return
        unique_imports: list[CommandEntry] = []
        seen: set[str] = set()
        for entry in imported:
            key = entry.value("short").casefold()
            if key not in seen:
                unique_imports.append(entry)
                seen.add(key)
        if self.entries:
            choice = messagebox.askyesnocancel(APP_NAME, self.t("import_choice", count=len(unique_imports)))
            if choice is None:
                return
            if choice:
                self.entries = unique_imports
            else:
                existing = {entry.value("short").casefold() for entry in self.entries if entry.command_id == "acronym"}
                self.entries.extend(entry for entry in unique_imports if entry.value("short").casefold() not in existing)
        else:
            self.entries = unique_imports
        if self._persist_and_render():
            self._start_new_entry("acronym")
            self._refresh_table()
            messagebox.showinfo(APP_NAME, self.t("imported", count=len(unique_imports)))

    def _on_profile_changed(self) -> None:
        self._active_profile()
        self.editing_uid = None
        self.current_command_id = ""
        self._build_ui()
        self._start_new_entry()
        self._save_workspace_settings()
        self.output_status_var.set(str(self._active_profile().get("preamble_hint", "")))

    def _request_language_refresh(self) -> None:
        """Queue a menu-safe rebuild after the language callback returns."""
        if not self._ui_ready or self.language == self._rendered_language:
            return
        if self._language_refresh_after_id is not None:
            return
        self._language_refresh_after_id = self.after_idle(self._apply_language_refresh)

    def _apply_language_refresh(self) -> None:
        self._language_refresh_after_id = None
        if not self._ui_ready or self.language == self._rendered_language:
            return
        self._build_ui()
        try:
            self._save_workspace_settings()
            self.output_status_var.set(self.t("language_changed"))
        except OSError as error:
            self.output_status_var.set(self.t("file_write_failed", error=error))

    def _copy_usage(self, command_id: str | None = None) -> None:
        command_id = command_id or self.current_command_id
        if command_id not in self.command_forms:
            return
        candidate = self._candidate_from_form(command_id)
        if not any(value.strip() for value in candidate.values.values()):
            selection = self.tree.selection()
            selected = next((entry for entry in self.entries if selection and entry.uid == selection[0]), None)
            if selected is not None:
                candidate = selected
        if not any(value.strip() for value in candidate.values.values()):
            messagebox.showinfo(APP_NAME, self.t("no_entry"))
            return
        command = usage_for(candidate, self._active_profile())
        if not command:
            messagebox.showinfo(APP_NAME, self.t("no_usage"))
            return
        self.clipboard_clear()
        self.clipboard_append(command)
        self.update()
        self.output_status_var.set(self.t("copied_usage", command=command))

    def _preview_output(self) -> None:
        profile = self._active_profile()
        window = tk.Toplevel(self)
        window.title(self.t("preview_title", name=profile["name"]))
        window.geometry("760x520")
        text = ScrolledText(window, wrap="none", font="TkFixedFont")
        text.pack(fill="both", expand=True, padx=10, pady=10)
        text.insert("1.0", render(self.entries, profile))
        text.config(state="disabled")

    def _open_profile_editor(self) -> None:
        if self.profiles:
            ProfileEditor(self)

    def _show_help(self) -> None:
        messagebox.showinfo(APP_NAME, self.t("help_text"))

    def _show_about(self) -> None:
        messagebox.showinfo(APP_NAME, self.t("about_text"))


class ProfileEditor(tk.Toplevel):
    """Edit a profile's generic command schema without adding Python code."""

    TEMPLATE_FIELDS = ("header", "footer", "separator", "usage_template")

    def __init__(self, app: TAcroManApp) -> None:
        super().__init__(app)
        self.app = app
        self.title(app.t("profile_editor_title"))
        self.geometry("860x800")
        self.minsize(700, 620)
        self.transient(app)
        self.selected_id_var = tk.StringVar(value=str(app._active_profile()["id"]))
        self.id_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.description_var = tk.StringVar()
        self.preamble_var = tk.StringVar()
        self.sort_var = tk.StringVar()
        self.escape_var = tk.StringVar()
        self.text_widgets: dict[str, ScrolledText] = {}
        self._build()
        self._load_selected()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)

        ttk.Label(frame, text=self.app.t("profile")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.selector = ttk.Combobox(
            frame, values=[str(profile["id"]) for profile in self.app.profiles], textvariable=self.selected_id_var, state="readonly"
        )
        self.selector.grid(row=0, column=1, sticky="ew")
        self.selector.bind("<<ComboboxSelected>>", lambda _event: self._load_selected())
        ttk.Button(frame, text=self.app.t("copy_as_new_profile"), command=self._clone_profile).grid(row=0, column=2, padx=(8, 0))

        basic = ttk.Frame(frame)
        basic.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        basic.columnconfigure(1, weight=1)
        for row, (label, variable) in enumerate(
            (
                ("ID:", self.id_var),
                (self.app.t("name"), self.name_var),
                (self.app.t("description"), self.description_var),
                (self.app.t("preamble_hint"), self.preamble_var),
            )
        ):
            ttk.Label(basic, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(0 if row == 0 else 6, 0))
            ttk.Entry(basic, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=(0 if row == 0 else 6, 0))

        options = ttk.Frame(frame)
        options.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 6))
        ttk.Label(options, text=self.app.t("sort")).pack(side="left")
        ttk.Entry(options, textvariable=self.sort_var, width=18).pack(side="left", padx=(6, 16))
        ttk.Label(options, text=self.app.t("escaping")).pack(side="left")
        ttk.Combobox(options, textvariable=self.escape_var, state="readonly", values=("none", "latex", "csv"), width=12).pack(side="left", padx=(6, 0))

        content = ttk.Notebook(frame)
        content.grid(row=3, column=0, columnspan=3, sticky="nsew")
        template_tab = ttk.Frame(content, padding=8)
        schema_tab = ttk.Frame(content, padding=8)
        content.add(template_tab, text=self.app.t("profile_templates_tab"))
        content.add(schema_tab, text=self.app.t("command_schema_tab"))

        template_tab.columnconfigure(1, weight=1)
        for row, field in enumerate(self.TEMPLATE_FIELDS):
            ttk.Label(template_tab, text=f"{field}:").grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=(0 if row == 0 else 6, 0))
            widget = ScrolledText(template_tab, height=2, wrap="none", font="TkFixedFont")
            widget.grid(row=row, column=1, sticky="ew", pady=(0 if row == 0 else 6, 0))
            self.text_widgets[field] = widget

        schema_tab.columnconfigure(0, weight=1)
        schema_tab.rowconfigure(1, weight=1)
        ttk.Label(schema_tab, text=self.app.t("command_schema_help"), wraplength=760, justify="left").grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.commands_text = ScrolledText(schema_tab, wrap="none", font="TkFixedFont")
        self.commands_text.grid(row=1, column=0, sticky="nsew")

        footer = ttk.Frame(frame)
        footer.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Label(footer, text=self.app.t("profile_file", path=self.app.profiles_path), foreground="#555555").pack(side="left")
        ttk.Button(footer, text=self.app.t("save"), command=self._save).pack(side="right")
        ttk.Button(footer, text=self.app.t("close"), command=self.destroy).pack(side="right", padx=(0, 8))

    def _find_profile(self, profile_id: str) -> dict[str, object]:
        return next(profile for profile in self.app.profiles if str(profile["id"]) == profile_id)

    def _load_selected(self) -> None:
        profile = self._find_profile(self.selected_id_var.get())
        self.id_var.set(str(profile["id"]))
        self.name_var.set(str(profile["name"]))
        self.description_var.set(str(profile.get("description", "")))
        self.preamble_var.set(str(profile.get("preamble_hint", "")))
        self.sort_var.set(str(profile.get("sort_by", "")))
        self.escape_var.set(str(profile.get("escape_mode", "none")))
        for field, widget in self.text_widgets.items():
            widget.delete("1.0", "end")
            widget.insert("1.0", str(profile.get(field, "")))
        self.commands_text.delete("1.0", "end")
        self.commands_text.insert("1.0", json.dumps(profile.get("commands", []), ensure_ascii=False, indent=2))

    def _clone_profile(self) -> None:
        source = self._find_profile(self.selected_id_var.get())
        identifier = simpledialog.askstring(self.app.t("new_profile_title"), self.app.t("new_profile_prompt"), parent=self)
        if not identifier:
            return
        identifier = identifier.strip()
        if any(str(profile["id"]) == identifier for profile in self.app.profiles):
            messagebox.showerror(APP_NAME, self.app.t("profile_id_exists"), parent=self)
            return
        profile_copy = json.loads(json.dumps(source))
        profile_copy["id"] = identifier
        profile_copy["name"] = self.app.t("profile_copy_name", name=source["name"])
        self.app.profiles.append(profile_copy)
        self.selected_id_var.set(identifier)
        self.selector.configure(values=[str(profile["id"]) for profile in self.app.profiles])
        self._load_selected()

    def _collect_profile(self) -> dict[str, object] | None:
        try:
            commands = json.loads(self.commands_text.get("1.0", "end-1c"))
        except json.JSONDecodeError as error:
            messagebox.showerror(APP_NAME, self.app.t("command_schema_invalid_json", error=error), parent=self)
            return None
        data: dict[str, object] = {
            "schema_version": 2,
            "id": self.id_var.get().strip(),
            "name": self.name_var.get().strip(),
            "description": self.description_var.get().strip(),
            "preamble_hint": self.preamble_var.get().strip(),
            "sort_by": self.sort_var.get().strip(),
            "escape_mode": self.escape_var.get().strip(),
            "commands": commands,
        }
        data.update({field: widget.get("1.0", "end-1c") for field, widget in self.text_widgets.items()})
        try:
            return normalise_profile(data, language=self.app.language)
        except ValueError as error:
            messagebox.showerror(APP_NAME, str(error), parent=self)
            return None

    def _save(self) -> None:
        profile = self._collect_profile()
        if profile is None:
            return
        old_id = self.selected_id_var.get()
        if str(profile["id"]) != old_id and any(str(item["id"]) == str(profile["id"]) for item in self.app.profiles):
            messagebox.showerror(APP_NAME, self.app.t("profile_id_exists"), parent=self)
            return
        warnings = profile_template_warnings(profile, language=self.app.language)
        if warnings and not messagebox.askyesno(
            APP_NAME, self.app.t("profile_confirm", warnings="\n".join(warnings)), parent=self
        ):
            return
        self.app.profiles = [profile if str(item["id"]) == old_id else item for item in self.app.profiles]
        try:
            save_profiles(self.app.profiles_path, self.app.profiles, language=self.app.language)
        except (OSError, ValueError) as error:
            messagebox.showerror(APP_NAME, self.app.t("profile_save_failed", error=error), parent=self)
            return
        self.app.profile_var.set(str(profile["id"]))
        self.app.current_command_id = ""
        self.app.editing_uid = None
        self.app._build_ui()
        self.app._start_new_entry()
        self.app._save_workspace_settings()
        self.selected_id_var.set(str(profile["id"]))
        self.selector.configure(values=[str(item["id"]) for item in self.app.profiles])
        self._load_selected()
        messagebox.showinfo(APP_NAME, self.app.t("profile_saved"), parent=self)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage profile-defined LaTeX command entries.")
    parser.add_argument("--database", type=Path, help="Path to the JSON command database.")
    parser.add_argument("--output", type=Path, help="Path of the generated output file.")
    parser.add_argument("--profiles", type=Path, help="Optional JSON file with custom command-definition profiles.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    app = TAcroManApp(args.database or _default_database_path(), args.output, args.profiles)
    app.mainloop()
