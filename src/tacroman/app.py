"""Tkinter desktop application for maintaining LaTeX acronym definitions."""

from __future__ import annotations

import argparse
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from .i18n import DEFAULT_LANGUAGE, normalize_language, translate
from .importing import parse_acronym_package, read_tex_file
from .model import Acronym, duplicate_matches, validate
from .profiles import PROFILE_FIELDS, load_profiles, save_profiles
from .rendering import profile_template_warnings, render, usage_for
from .storage import atomic_write_text, load_database, load_settings, save_database, save_settings


APP_NAME = "TAcroMan"
SETTINGS_FILENAME = "tacroman-settings.json"
LEGACY_SETTINGS_FILENAME = "acronym-manager-settings.json"
PROFILE_FILENAME = "tacroman-render-profiles.json"


def _default_database_path() -> Path:
    return Path.home() / APP_NAME / "acronyms.json"


class TAcroManApp(tk.Tk):
    """A local JSON-backed manager with configurable LaTeX renderers."""

    def __init__(self, database_path: Path, output_path: Path | None, profiles_path: Path | None) -> None:
        super().__init__()
        self.minsize(980, 620)
        self.geometry("1180x720")

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

        self.entries: list[Acronym] = []
        self.profiles: list[dict[str, str]] = []
        self.editing_uid: str | None = None
        self._ui_ready = False
        self._language_refresh_after_id: str | None = None
        self._rendered_language = ""

        self.database_path_var = tk.StringVar(value=str(self.database_path))
        self.output_path_var = tk.StringVar(value=str(self.output_path))
        self.search_var = tk.StringVar()
        self.profile_var = tk.StringVar(value=str(settings.get("selected_profile_id", "acronym-package")))
        self.profile_display_var = tk.StringVar()
        self.language_var = tk.StringVar(value=normalize_language(str(settings.get("language", DEFAULT_LANGUAGE))))
        self.short_var = tk.StringVar()
        self.long_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.validation_var = tk.StringVar()
        self.output_status_var = tk.StringVar()

        self._build_ui()
        self._load_workspace(initial=True)
        self._ui_ready = True

        self.search_var.trace_add("write", lambda *_: self._refresh_table())
        for variable in (self.short_var, self.long_var, self.category_var):
            variable.trace_add("write", lambda *_: self._update_validation())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    @property
    def language(self) -> str:
        return normalize_language(self.language_var.get())

    def t(self, key: str, **values: object) -> str:
        """Translate a UI string using the current application language."""
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
        """Build the menu and editor, preserving unfinished editor input."""
        note_content = self.note_text.get("1.0", "end-1c") if hasattr(self, "note_text") else ""
        if hasattr(self, "content"):
            self.content.destroy()

        self.title(self.t("app_title"))
        self._build_menu()
        self.content = ttk.Frame(self)
        self.content.pack(fill="both", expand=True)
        self._build_acronym_tab(self.content)

        if note_content:
            self.note_text.insert("1.0", note_content)
        if self.profiles:
            self._update_profile_combo()
        self._refresh_table()
        self._update_validation()
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
        language_menu.add_radiobutton(
            label="Deutsch",
            value="de",
            variable=self.language_var,
            command=self._request_language_refresh,
        )
        language_menu.add_radiobutton(
            label="English",
            value="en",
            variable=self.language_var,
            command=self._request_language_refresh,
        )
        menu.add_cascade(label=self.t("menu_language"), menu=language_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label=self.t("menu_help"), command=self._show_help)
        help_menu.add_command(label=self.t("menu_about"), command=self._show_about)
        menu.add_cascade(label=self.t("menu_help"), menu=help_menu)
        self.config(menu=menu)

    def _build_acronym_tab(self, parent: ttk.Frame) -> None:
        outer = ttk.Frame(parent, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(3, weight=1)

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

        format_bar = ttk.Frame(outer)
        format_bar.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 10))
        format_bar.columnconfigure(1, weight=1)
        ttk.Label(format_bar, text=self.t("output_format")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.profile_combo = ttk.Combobox(format_bar, textvariable=self.profile_display_var, state="readonly", width=42)
        self.profile_combo.grid(row=0, column=1, sticky="w")
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_profile_changed())
        ttk.Button(format_bar, text=self.t("edit_format"), command=self._open_profile_editor).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(format_bar, textvariable=self.output_status_var, foreground="#336633").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(5, 0)
        )

        body = ttk.PanedWindow(outer, orient="horizontal")
        body.grid(row=3, column=0, columnspan=4, sticky="nsew")
        list_frame = ttk.Frame(body, padding=(0, 0, 12, 0))
        editor_frame = ttk.LabelFrame(body, text=self.t("edit_acronym"), padding=12)
        body.add(list_frame, weight=3)
        body.add(editor_frame, weight=2)
        self._build_list(list_frame)
        self._build_editor(editor_frame)

    def _build_list(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        search = ttk.Frame(parent)
        search.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text=self.t("search")).grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(search, textvariable=self.search_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(search, text="✕", width=3, command=lambda: self.search_var.set("")).grid(row=0, column=2, padx=(6, 0))

        columns = ("short", "long", "category")
        self.tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("short", text=self.t("short"))
        self.tree.heading("long", text=self.t("long"))
        self.tree.heading("category", text=self.t("category"))
        self.tree.column("short", width=95, stretch=False)
        self.tree.column("long", width=390, stretch=True)
        self.tree.column("category", width=130, stretch=False)
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

    def _build_editor(self, parent: ttk.LabelFrame) -> None:
        parent.columnconfigure(0, weight=1)
        ttk.Label(parent, text=self.t("short_required")).grid(row=0, column=0, sticky="w")
        self.short_entry = ttk.Entry(parent, textvariable=self.short_var)
        self.short_entry.grid(row=1, column=0, sticky="ew", pady=(3, 10))
        self.short_entry.bind("<Return>", lambda _event: self._focus_long_field())

        ttk.Label(parent, text=self.t("long_required")).grid(row=2, column=0, sticky="w")
        self.long_entry = ttk.Entry(parent, textvariable=self.long_var)
        self.long_entry.grid(row=3, column=0, sticky="ew", pady=(3, 10))
        self.long_entry.bind("<Control-Return>", lambda _event: self._save_editor())

        ttk.Label(parent, text=self.t("category_optional")).grid(row=4, column=0, sticky="w")
        ttk.Entry(parent, textvariable=self.category_var).grid(row=5, column=0, sticky="ew", pady=(3, 10))

        ttk.Label(parent, text=self.t("note_optional")).grid(row=6, column=0, sticky="w")
        self.note_text = ScrolledText(parent, height=6, wrap="word", font="TkDefaultFont")
        self.note_text.grid(row=7, column=0, sticky="nsew", pady=(3, 10))

        self.validation_label = ttk.Label(parent, textvariable=self.validation_var, foreground="#885500", wraplength=340)
        self.validation_label.grid(row=8, column=0, sticky="ew", pady=(0, 10))

        actions = ttk.Frame(parent)
        actions.grid(row=9, column=0, sticky="ew")
        self.save_entry_button = ttk.Button(actions, text=self.t("add_acronym"), command=self._save_editor)
        self.save_entry_button.pack(side="left")
        ttk.Button(actions, text=self.t("clear"), command=self._start_new_entry).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text=self.t("copy_usage"), command=self._copy_usage).pack(side="right")

    def _load_workspace(self, *, initial: bool = False) -> None:
        try:
            self.entries = load_database(self.database_path, language=self.language)
            self.profiles = load_profiles(self.profiles_path, language=self.language)
        except (OSError, ValueError) as error:
            messagebox.showerror(APP_NAME, str(error))
            if initial:
                self.entries = []
                self.profiles = load_profiles(language=self.language)
            return
        self._update_profile_combo()
        self._refresh_table()
        self._start_new_entry()
        self.output_status_var.set(self.t("entries_loaded", count=len(self.entries)))

    def _update_profile_combo(self) -> None:
        if not self.profiles:
            self.profile_combo["values"] = ()
            self.profile_display_var.set("")
            return
        labels = [f"{profile['name']}  [{profile['id']}]" for profile in self.profiles]
        self.profile_combo["values"] = labels
        profile_ids = {profile["id"] for profile in self.profiles}
        if self.profile_var.get() not in profile_ids:
            self.profile_var.set("acronym-package" if "acronym-package" in profile_ids else self.profiles[0]["id"])
        active_id = self.profile_var.get()
        self.profile_display_var.set(next(label for label in labels if label.endswith(f"[{active_id}]")))

    def _active_profile(self) -> dict[str, str]:
        selected = self.profile_display_var.get()
        selected_id = selected.rsplit("[", 1)[-1].rstrip("]")
        if selected_id in {profile["id"] for profile in self.profiles}:
            self.profile_var.set(selected_id)
        return next(profile for profile in self.profiles if profile["id"] == self.profile_var.get())

    def _filtered_entries(self) -> list[Acronym]:
        query = self.search_var.get().strip().casefold()
        ordered = sorted(self.entries, key=lambda entry: entry.short.casefold())
        if not query:
            return ordered
        return [
            entry
            for entry in ordered
            if query in entry.short.casefold()
            or query in entry.long.casefold()
            or query in entry.category.casefold()
            or query in entry.note.casefold()
        ]

    def _refresh_table(self) -> None:
        if not hasattr(self, "tree"):
            return
        selected = self.editing_uid
        self.tree.delete(*self.tree.get_children())
        for entry in self._filtered_entries():
            self.tree.insert("", "end", iid=entry.uid, values=(entry.short, entry.long, entry.category))
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.focus(selected)

    def _on_tree_select(self, _event: object | None = None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        entry = next((item for item in self.entries if item.uid == selection[0]), None)
        if entry is None:
            return
        self.editing_uid = entry.uid
        self.short_var.set(entry.short)
        self.long_var.set(entry.long)
        self.category_var.set(entry.category)
        self.note_text.delete("1.0", "end")
        self.note_text.insert("1.0", entry.note)
        self.save_entry_button.config(text=self.t("save_changes"))
        self._update_validation()

    def _candidate_from_editor(self) -> Acronym:
        values = {
            "short": self.short_var.get().strip(),
            "long": self.long_var.get().strip(),
            "category": self.category_var.get().strip(),
            "note": self.note_text.get("1.0", "end-1c").strip(),
        }
        return Acronym(uid=self.editing_uid, **values) if self.editing_uid else Acronym(**values)

    def _update_validation(self) -> None:
        if not hasattr(self, "validation_label"):
            return
        candidate = self._candidate_from_editor()
        if not candidate.short and not candidate.long:
            self.validation_label.config(foreground="#336633")
            self.validation_var.set(self.t("ready"))
            return

        errors, warnings = validate(candidate, language=self.language)
        exact, similar = duplicate_matches(candidate, self.entries, ignore_uid=self.editing_uid)
        messages: list[str] = []
        if exact:
            duplicates = ", ".join(f"{entry.short}: {entry.long}" for entry in exact[:3])
            messages.append(self.t("duplicate_live", entries=duplicates))
        if errors:
            messages.extend(errors)
        if not exact and similar:
            suggestions = ", ".join(f"{entry.short} ({score:.0%})" for entry, score in similar[:3])
            messages.append(self.t("similar_live", entries=suggestions))
        if warnings:
            messages.extend(warnings)

        if exact or errors:
            self.validation_label.config(foreground="#aa2222")
        elif similar or warnings:
            self.validation_label.config(foreground="#885500")
        else:
            self.validation_label.config(foreground="#336633")
            messages.append(self.t("format_valid"))
        self.validation_var.set(" • ".join(messages))

    def _save_editor(self) -> None:
        candidate = self._candidate_from_editor()
        errors, warnings = validate(candidate, language=self.language)
        if errors:
            messagebox.showerror(APP_NAME, "\n".join(errors))
            return
        exact, similar = duplicate_matches(candidate, self.entries, ignore_uid=self.editing_uid)
        if exact:
            entries = "\n".join(f"• {item.short}: {item.long}" for item in exact)
            messagebox.showerror(APP_NAME, self.t("duplicate_error", entries=entries))
            return
        if similar:
            entries = "\n".join(f"• {entry.short}: {entry.long} ({score:.0%})" for entry, score in similar[:4])
            if not messagebox.askyesno(APP_NAME, self.t("similar_confirm", entries=entries)):
                return
        if warnings and not messagebox.askyesno(APP_NAME, self.t("format_confirm", warnings="\n".join(warnings))):
            return

        was_editing = self.editing_uid is not None
        if self.editing_uid:
            candidate.uid = self.editing_uid
            for index, entry in enumerate(self.entries):
                if entry.uid == self.editing_uid:
                    self.entries[index] = candidate
                    break
        else:
            self.entries.append(candidate)
        if self._persist_and_render():
            self.editing_uid = None
            self._refresh_table()
            self._start_new_entry()
            self.output_status_var.set(self.t("entry_updated" if was_editing else "entry_added"))

    def _start_new_entry(self) -> None:
        self._clear_editor(focus_short=True)
        if hasattr(self, "tree"):
            self.tree.selection_remove(self.tree.selection())

    def _clear_editor(self, *, focus_short: bool = False) -> None:
        self.editing_uid = None
        self.short_var.set("")
        self.long_var.set("")
        self.category_var.set("")
        if hasattr(self, "note_text"):
            self.note_text.delete("1.0", "end")
        if hasattr(self, "save_entry_button"):
            self.save_entry_button.config(text=self.t("add_acronym"))
        self._update_validation()
        if focus_short and hasattr(self, "short_entry"):
            self.after_idle(self.short_entry.focus_set)

    def _focus_long_field(self) -> str:
        self.long_entry.focus_set()
        return "break"

    def _delete_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(APP_NAME, self.t("select_entry_first"))
            return
        entry = next((item for item in self.entries if item.uid == selection[0]), None)
        if entry is None:
            return
        if not messagebox.askyesno(APP_NAME, self.t("confirm_delete", short=entry.short)):
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
            atomic_write_text(self.output_path, render(self.entries, profile))
            self._save_workspace_settings()
            self.output_status_var.set(self.t("output_status_written", path=self.output_path))
            if show_success:
                messagebox.showinfo(APP_NAME, self.t("output_written", count=len(self.entries), path=self.output_path))
            return True
        except (OSError, KeyError, ValueError) as error:
            self.output_status_var.set(self.t("output_failed"))
            if show_success:
                messagebox.showerror(APP_NAME, self.t("file_write_failed", error=error))
            return False

    def _save_workspace_settings(self) -> None:
        selected_profile_id = self.profile_var.get() if self.profiles else "acronym-package"
        settings = {
            "output_path": str(self.output_path),
            "profiles_path": str(self.profiles_path),
            "selected_profile_id": selected_profile_id,
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
        self._build_ui()
        self._ui_ready = True
        self._load_workspace()

    def _new_database(self) -> None:
        selected = filedialog.asksaveasfilename(
            title=self.t("new_database_title"),
            defaultextension=".json",
            initialfile="acronyms.json",
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
        self._update_profile_combo()
        self._refresh_table()
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
            filetypes=[
                (self.t("tex_files"), "*.tex"),
                (self.t("csv_files"), "*.csv"),
                (self.t("all_files"), "*.*"),
            ],
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
        self._update_profile_combo()
        self._save_workspace_settings()

    def _import_tex_file(self) -> None:
        selected = filedialog.askopenfilename(
            title=self.t("import_tex_title"),
            filetypes=[(self.t("tex_files"), "*.tex"), (self.t("all_files"), "*.*")],
        )
        if not selected:
            return
        try:
            imported = parse_acronym_package(read_tex_file(Path(selected)))
        except (OSError, UnicodeDecodeError) as error:
            messagebox.showerror(APP_NAME, self.t("file_read_failed", error=error))
            return
        if not imported:
            messagebox.showwarning(APP_NAME, self.t("no_definitions"))
            return

        unique_imports: list[Acronym] = []
        imported_shorts: set[str] = set()
        for entry in imported:
            short_key = entry.short.casefold()
            if short_key not in imported_shorts:
                unique_imports.append(entry)
                imported_shorts.add(short_key)

        if self.entries:
            choice = messagebox.askyesnocancel(APP_NAME, self.t("import_choice", count=len(unique_imports)))
            if choice is None:
                return
            if choice:
                self.entries = unique_imports
            else:
                existing_shorts = {entry.short.casefold() for entry in self.entries}
                self.entries.extend(entry for entry in unique_imports if entry.short.casefold() not in existing_shorts)
        else:
            self.entries = unique_imports

        if self._persist_and_render():
            self.editing_uid = None
            self._refresh_table()
            self._start_new_entry()
            messagebox.showinfo(APP_NAME, self.t("imported", count=len(unique_imports)))

    def _on_profile_changed(self) -> None:
        self._active_profile()
        self._save_workspace_settings()
        self.output_status_var.set(self._active_profile().get("preamble_hint", ""))

    def _request_language_refresh(self) -> None:
        """Queue a UI rebuild after the active menu command has finished.

        Replacing the menu while its language radio button is still handling a
        click can make Tkinter reference the old, already-destroyed menu on a
        subsequent language change.  Deferring the rebuild until idle keeps
        the menu callback short and makes repeated language switches safe.
        """
        if not self._ui_ready or self.language == self._rendered_language:
            return
        if self._language_refresh_after_id is not None:
            return
        self._language_refresh_after_id = self.after_idle(self._apply_language_refresh)

    def _apply_language_refresh(self) -> None:
        """Rebuild the interface once the language menu is no longer active."""
        self._language_refresh_after_id = None
        if not self._ui_ready or self.language == self._rendered_language:
            return
        self._build_ui()
        try:
            self._save_workspace_settings()
            self.output_status_var.set(self.t("language_changed"))
        except OSError as error:
            self.output_status_var.set(self.t("file_write_failed", error=error))

    def _copy_usage(self) -> None:
        candidate = self._candidate_from_editor()
        if not candidate.short:
            selection = self.tree.selection()
            candidate = next((entry for entry in self.entries if selection and entry.uid == selection[0]), candidate)
        if not candidate.short:
            messagebox.showinfo(APP_NAME, self.t("no_acronym"))
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
        ProfileEditor(self)

    def _show_help(self) -> None:
        messagebox.showinfo(APP_NAME, self.t("help_text"))

    def _show_about(self) -> None:
        messagebox.showinfo(APP_NAME, self.t("about_text"))


class ProfileEditor(tk.Toplevel):
    """Editor for JSON-backed renderer profiles."""

    TEMPLATE_FIELDS = ("header", "entry", "footer", "separator", "usage_template")

    def __init__(self, app: TAcroManApp) -> None:
        super().__init__(app)
        self.app = app
        self.title(app.t("profile_editor_title"))
        self.geometry("790x780")
        self.minsize(650, 600)
        self.transient(app)

        self.selected_id_var = tk.StringVar(value=app._active_profile()["id"])
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
        values = [profile["id"] for profile in self.app.profiles]
        chooser = ttk.Combobox(frame, values=values, textvariable=self.selected_id_var, state="readonly")
        chooser.grid(row=0, column=1, sticky="ew")
        chooser.bind("<<ComboboxSelected>>", lambda _event: self._load_selected())
        ttk.Button(frame, text=self.app.t("copy_as_new_profile"), command=self._clone_profile).grid(row=0, column=2, padx=(8, 0))

        basic = ttk.Frame(frame)
        basic.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        basic.columnconfigure(1, weight=1)
        ttk.Label(basic, text="ID:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(basic, textvariable=self.id_var).grid(row=0, column=1, sticky="ew")
        ttk.Label(basic, text="Name:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        ttk.Entry(basic, textvariable=self.name_var).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(basic, text=self.app.t("description")).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        ttk.Entry(basic, textvariable=self.description_var).grid(row=2, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(basic, text=self.app.t("preamble_hint")).grid(row=3, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        ttk.Entry(basic, textvariable=self.preamble_var).grid(row=3, column=1, sticky="ew", pady=(6, 0))

        options = ttk.Frame(frame)
        options.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 6))
        ttk.Label(options, text=self.app.t("sort")).pack(side="left")
        ttk.Combobox(options, textvariable=self.sort_var, state="readonly", values=("short", "long", "identifier", "category", "none"), width=14).pack(side="left", padx=(6, 16))
        ttk.Label(options, text=self.app.t("escaping")).pack(side="left")
        ttk.Combobox(options, textvariable=self.escape_var, state="readonly", values=("none", "latex", "csv"), width=12).pack(side="left", padx=(6, 0))

        templates = ttk.LabelFrame(frame, text=self.app.t("templates"), padding=8)
        templates.grid(row=3, column=0, columnspan=3, sticky="nsew")
        templates.columnconfigure(1, weight=1)
        for row, field in enumerate(self.TEMPLATE_FIELDS):
            ttk.Label(templates, text=f"{field}:").grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=(0 if row == 0 else 6, 0))
            widget = ScrolledText(templates, height=2 if field != "entry" else 4, wrap="none", font="TkFixedFont")
            widget.grid(row=row, column=1, sticky="ew", pady=(0 if row == 0 else 6, 0))
            self.text_widgets[field] = widget

        footer = ttk.Frame(frame)
        footer.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Label(footer, text=self.app.t("profile_file", path=self.app.profiles_path), foreground="#555555").pack(side="left")
        ttk.Button(footer, text=self.app.t("save"), command=self._save).pack(side="right")
        ttk.Button(footer, text=self.app.t("close"), command=self.destroy).pack(side="right", padx=(0, 8))

    def _find_profile(self, profile_id: str) -> dict[str, str]:
        return next(profile for profile in self.app.profiles if profile["id"] == profile_id)

    def _load_selected(self) -> None:
        profile = self._find_profile(self.selected_id_var.get())
        self.id_var.set(profile["id"])
        self.name_var.set(profile["name"])
        self.description_var.set(profile["description"])
        self.preamble_var.set(profile["preamble_hint"])
        self.sort_var.set(profile["sort_by"])
        self.escape_var.set(profile["escape_mode"])
        for field, widget in self.text_widgets.items():
            widget.delete("1.0", "end")
            widget.insert("1.0", profile[field])

    def _clone_profile(self) -> None:
        source = self._find_profile(self.selected_id_var.get())
        identifier = simpledialog.askstring(self.app.t("new_profile_title"), self.app.t("new_profile_prompt"), parent=self)
        if not identifier:
            return
        identifier = identifier.strip()
        if any(profile["id"] == identifier for profile in self.app.profiles):
            messagebox.showerror(APP_NAME, self.app.t("profile_id_exists"), parent=self)
            return
        profile_copy = dict(source)
        profile_copy["id"] = identifier
        profile_copy["name"] = self.app.t("profile_copy_name", name=source["name"])
        self.app.profiles.append(profile_copy)
        self.selected_id_var.set(identifier)
        self._refresh_selector()

    def _refresh_selector(self) -> None:
        for child in self.winfo_children():
            for descendant in child.winfo_children():
                if isinstance(descendant, ttk.Combobox) and str(descendant.cget("textvariable")) == str(self.selected_id_var):
                    descendant.configure(values=[profile["id"] for profile in self.app.profiles])
        self._load_selected()

    def _collect_profile(self) -> dict[str, str]:
        data = {
            "id": self.id_var.get().strip(),
            "name": self.name_var.get().strip(),
            "description": self.description_var.get().strip(),
            "preamble_hint": self.preamble_var.get().strip(),
            "sort_by": self.sort_var.get().strip(),
            "escape_mode": self.escape_var.get().strip(),
        }
        data.update({field: widget.get("1.0", "end-1c") for field, widget in self.text_widgets.items()})
        return {field: data.get(field, "") for field in PROFILE_FIELDS}

    def _save(self) -> None:
        profile = self._collect_profile()
        if not profile["id"] or not profile["name"] or not profile["entry"]:
            messagebox.showerror(APP_NAME, self.app.t("profile_required"), parent=self)
            return
        old_id = self.selected_id_var.get()
        ids = {item["id"] for item in self.app.profiles}
        if profile["id"] != old_id and profile["id"] in ids:
            messagebox.showerror(APP_NAME, self.app.t("profile_id_exists"), parent=self)
            return
        warnings = profile_template_warnings(profile, language=self.app.language)
        if warnings and not messagebox.askyesno(APP_NAME, self.app.t("profile_confirm", warnings="\n".join(warnings)), parent=self):
            return
        for index, item in enumerate(self.app.profiles):
            if item["id"] == old_id:
                self.app.profiles[index] = profile
                break
        try:
            save_profiles(self.app.profiles_path, self.app.profiles, language=self.app.language)
        except (OSError, ValueError) as error:
            messagebox.showerror(APP_NAME, self.app.t("profile_save_failed", error=error), parent=self)
            return
        self.app.profile_var.set(profile["id"])
        self.app._update_profile_combo()
        self.app._save_workspace_settings()
        self.selected_id_var.set(profile["id"])
        self._refresh_selector()
        messagebox.showinfo(APP_NAME, self.app.t("profile_saved"), parent=self)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage LaTeX acronym definitions with configurable output profiles.")
    parser.add_argument("--database", type=Path, help="Path to the acronym JSON database.")
    parser.add_argument("--output", type=Path, help="Path of the generated output file.")
    parser.add_argument("--profiles", type=Path, help="Optional JSON file with custom renderer profiles.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    app = TAcroManApp(args.database or _default_database_path(), args.output, args.profiles)
    app.mainloop()


if __name__ == "__main__":
    main()
