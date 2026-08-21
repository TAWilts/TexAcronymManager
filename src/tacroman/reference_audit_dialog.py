"""Tkinter UI for auditing bibliography usage in a LaTeX project."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .reference_audit import ReferenceAuditReport, audit_project, discover_reference_files

_MESSAGES = {
    "title": {"de": "Referenzen prüfen", "en": "Audit references"},
    "intro": {
        "de": "Vergleicht die ausgewählte Referenzdatei mit allen LaTeX-Quelldateien im Projekt. Die obere Tabelle zeigt Bibliographieeinträge, die nirgends zitiert werden; die untere Tabelle zeigt jede gefundene Zitationsstelle. Doppelklick auf eine Tabellenzelle markiert ihren Inhalt zum Kopieren.",
        "en": "Compare the selected reference file with all LaTeX source files in the project. The upper table shows bibliography entries that are never cited; the lower table shows every citation occurrence. Double-click a table cell to select its contents for copying.",
    },
    "project": {"de": "Projektverzeichnis:", "en": "Project directory:"},
    "choose_project": {"de": "Projektverzeichnis auswählen", "en": "Choose project directory"},
    "reference_file": {"de": "Referenzdatei:", "en": "Reference file:"},
    "excerpt_radius": {"de": "Auszug (Zeichen davor/danach):", "en": "Excerpt (characters before/after):"},
    "search": {"de": "Suche:", "en": "Search:"},
    "invalid_excerpt_radius": {
        "de": "Bitte für die Auszugslänge eine ganze Zahl zwischen 0 und 5000 eingeben.",
        "en": "Please enter a whole number between 0 and 5000 for the excerpt length.",
    },
    "refresh": {"de": "Neu laden", "en": "Refresh"},
    "analyse": {"de": "Referenzen prüfen", "en": "Audit references"},
    "unused_frame": {"de": "Nicht verwendete Referenzen", "en": "Unused references"},
    "used_frame": {"de": "Gefundene Referenzverwendungen", "en": "Found citation occurrences"},
    "reference": {"de": "Referenz", "en": "Reference"},
    "title_col": {"de": "Titel", "en": "Title"},
    "author": {"de": "Autor", "en": "Author"},
    "file": {"de": "Datei", "en": "File"},
    "line": {"de": "Zeile", "en": "Line"},
    "excerpt": {"de": "Auszug", "en": "Excerpt"},
    "ready": {
        "de": "Wähle zuerst ein Projektverzeichnis. Passende Referenzdateien werden automatisch im Dropdown gesucht.",
        "en": "Choose a project directory first. Suitable reference files are discovered automatically for the dropdown.",
    },
    "no_candidates": {
        "de": "Im Projekt wurden keine Dateien mit BibTeX/BibLaTeX-Einträgen gefunden.",
        "en": "No files containing BibTeX/BibLaTeX entries were found in the project.",
    },
    "choose_both": {
        "de": "Bitte ein vorhandenes Projektverzeichnis und eine Referenzdatei auswählen.",
        "en": "Please choose an existing project directory and reference file.",
    },
    "failed": {"de": "Die Referenzen konnten nicht geprüft werden:\n{error}", "en": "The references could not be audited:\n{error}"},
    "summary": {
        "de": "{entries} Bibliographieeinträge · {used} verwendet · {unused} nicht verwendet · {occurrences} Fundstellen · {unknown} unbekannte Zitationsschlüssel · {files} Quelldateien geprüft.",
        "en": "{entries} bibliography entries · {used} used · {unused} unused · {occurrences} occurrences · {unknown} unknown citation keys · {files} source files checked.",
    },
    "unknown_title": {"de": "[nicht in Referenzdatei]", "en": "[not in reference file]"},
    "close": {"de": "Schließen", "en": "Close"},
}


def _initial_project_directory(app: object) -> str:
    """Use the directory containing the current Generated file as audit default."""

    output_var = getattr(app, "output_path_var", None)
    try:
        value = str(output_var.get()).strip() if output_var is not None else ""
    except (AttributeError, tk.TclError):
        value = ""
    if not value:
        return ""

    path = Path(value).expanduser()
    if not path.is_absolute():
        database_path = getattr(app, "database_path", None)
        if database_path is not None:
            path = Path(database_path).expanduser().parent / path
    try:
        path = path.resolve()
    except OSError:
        pass
    return str(path if path.is_dir() else path.parent)


def _row_matches_search(values: tuple[object, ...], query: str) -> bool:
    """Return True when every search term occurs somewhere in the row."""

    terms = query.casefold().split()
    if not terms:
        return True
    searchable = "\n".join(str(value) for value in values).casefold()
    return all(term in searchable for term in terms)


class ReferenceAuditDialog(tk.Toplevel):
    """Interactive bibliography/project comparison."""

    def __init__(self, app: object) -> None:
        super().__init__(app)
        self.app = app
        self.title(self.t("title"))
        self.geometry("1280x820")
        self.minsize(960, 650)
        self.transient(app)

        initial_project = _initial_project_directory(app)
        self.project_var = tk.StringVar(value=initial_project)
        self.reference_var = tk.StringVar()
        self.excerpt_radius_var = tk.StringVar(value="50")
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value=self.t("ready"))
        self.reference_paths: dict[str, Path] = {}
        self.report: ReferenceAuditReport | None = None
        self._unused_rows: list[tuple[object, ...]] = []
        self._used_rows: list[tuple[object, ...]] = []
        self._cell_overlay: ttk.Entry | None = None
        self._active_cell: tuple[ttk.Treeview, str, str] | None = None
        self._build()
        self.search_var.trace_add("write", self._on_search_changed)
        if initial_project:
            self._refresh_reference_files()

    @property
    def language(self) -> str:
        return getattr(self.app, "language", "de")

    def t(self, key: str, **values: object) -> str:
        messages = _MESSAGES[key]
        text = messages.get(self.language, messages["en"])
        for name, value in values.items():
            text = text.replace("{" + name + "}", str(value))
        return text

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=2)
        frame.rowconfigure(4, weight=3)

        ttk.Label(frame, text=self.t("intro"), wraplength=1200, justify="left").grid(
            row=0, column=0, sticky="ew", pady=(0, 10)
        )

        controls = ttk.Frame(frame)
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text=self.t("project")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(controls, textvariable=self.project_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(controls, text=getattr(self.app, "t", lambda _key: "Open…")("open"), command=self._choose_project).grid(
            row=0, column=2, padx=(8, 0)
        )

        ttk.Label(controls, text=self.t("reference_file")).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.reference_combo = ttk.Combobox(controls, textvariable=self.reference_var, state="readonly")
        self.reference_combo.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text=self.t("refresh"), command=self._refresh_reference_files).grid(
            row=1, column=2, padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(controls, text=self.t("excerpt_radius")).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Spinbox(
            controls,
            from_=0,
            to=5000,
            textvariable=self.excerpt_radius_var,
            width=10,
        ).grid(row=2, column=1, sticky="w", pady=(8, 0))

        action_row = ttk.Frame(frame)
        action_row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(action_row, text=self.t("search")).pack(side="left", padx=(0, 8))
        self.search_entry = ttk.Entry(action_row, textvariable=self.search_var, width=42)
        self.search_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(action_row, text=self.t("analyse"), command=self._analyse).pack(side="right", padx=(12, 0))

        unused_frame = ttk.LabelFrame(frame, text=self.t("unused_frame"), padding=8)
        unused_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        self.unused_tree = self._make_tree(
            unused_frame,
            columns=("reference", "title", "author"),
            headings=(self.t("reference"), self.t("title_col"), self.t("author")),
            widths=(220, 540, 380),
            stretch=(False, True, True),
        )

        used_frame = ttk.LabelFrame(frame, text=self.t("used_frame"), padding=8)
        used_frame.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        self.used_tree = self._make_tree(
            used_frame,
            columns=("file", "line", "reference", "title", "author", "excerpt"),
            headings=(self.t("file"), self.t("line"), self.t("reference"), self.t("title_col"), self.t("author"), self.t("excerpt")),
            widths=(210, 70, 190, 320, 260, 520),
            stretch=(True, False, False, True, True, True),
        )

        footer = ttk.Frame(frame)
        footer.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(footer, textvariable=self.status_var, justify="left", wraplength=1050).pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text=self.t("close"), command=self.destroy).pack(side="right")

    def _make_tree(
        self,
        parent: ttk.LabelFrame,
        *,
        columns: tuple[str, ...],
        headings: tuple[str, ...],
        widths: tuple[int, ...],
        stretch: tuple[bool, ...],
    ) -> ttk.Treeview:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        tree = ttk.Treeview(parent, columns=columns, show="headings")
        for column, heading, width, can_stretch in zip(columns, headings, widths, stretch):
            tree.heading(column, text=heading, command=lambda c=column, t=tree: self._sort_tree(t, c, False))
            anchor = "e" if column == "line" else "w"
            tree.column(column, width=width, minwidth=55, stretch=can_stretch, anchor=anchor)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.bind("<Button-1>", lambda event, t=tree: self._remember_cell(t, event), add="+")
        tree.bind("<Double-1>", lambda event, t=tree: self._show_copy_cell(t, event), add="+")
        tree.bind("<Control-c>", lambda _event, t=tree: self._copy_active_cell(t))
        tree.bind("<Control-C>", lambda _event, t=tree: self._copy_active_cell(t))
        return tree

    def _cell_from_event(self, tree: ttk.Treeview, event: tk.Event) -> tuple[str, str] | None:
        if tree.identify_region(event.x, event.y) != "cell":
            return None
        iid = tree.identify_row(event.y)
        display_column = tree.identify_column(event.x)
        if not iid or not display_column.startswith("#"):
            return None
        try:
            index = int(display_column[1:]) - 1
            column = str(tree["columns"][index])
        except (ValueError, IndexError):
            return None
        return iid, column

    def _remember_cell(self, tree: ttk.Treeview, event: tk.Event) -> None:
        cell = self._cell_from_event(tree, event)
        if cell is not None:
            self._active_cell = (tree, cell[0], cell[1])

    def _show_copy_cell(self, tree: ttk.Treeview, event: tk.Event) -> str | None:
        cell = self._cell_from_event(tree, event)
        if cell is None:
            return None
        iid, column = cell
        self._active_cell = (tree, iid, column)
        self._close_cell_overlay()

        display_index = tuple(str(item) for item in tree["columns"]).index(column) + 1
        bbox = tree.bbox(iid, f"#{display_index}")
        if not bbox:
            return None
        x, y, width, height = bbox
        overlay = ttk.Entry(tree)
        overlay.insert(0, tree.set(iid, column))
        overlay.state(["readonly"])
        overlay.place(x=x, y=y, width=width, height=height)
        overlay.focus_set()
        overlay.selection_range(0, tk.END)
        overlay.bind("<Escape>", lambda _event: self._close_cell_overlay())
        overlay.bind("<Return>", lambda _event: self._close_cell_overlay())
        overlay.bind("<FocusOut>", lambda _event: self.after_idle(self._close_cell_overlay))
        self._cell_overlay = overlay
        return "break"

    def _copy_active_cell(self, tree: ttk.Treeview) -> str:
        if self._active_cell is not None and self._active_cell[0] is tree:
            _tree, iid, column = self._active_cell
            if tree.exists(iid):
                self.clipboard_clear()
                self.clipboard_append(tree.set(iid, column))
        return "break"

    def _close_cell_overlay(self) -> None:
        overlay = self._cell_overlay
        self._cell_overlay = None
        if overlay is not None and overlay.winfo_exists():
            overlay.destroy()

    def _choose_project(self) -> None:
        selected = filedialog.askdirectory(parent=self, title=self.t("choose_project"), initialdir=self.project_var.get() or None)
        if not selected:
            return
        self.project_var.set(selected)
        self._refresh_reference_files()

    def _refresh_reference_files(self) -> None:
        project = Path(self.project_var.get()).expanduser()
        self.reference_paths.clear()
        self.reference_combo["values"] = ()
        self.reference_var.set("")
        if not project.is_dir():
            self.status_var.set(self.t("ready"))
            return
        candidates = discover_reference_files(project)
        for path in candidates:
            try:
                display = str(path.relative_to(project.resolve()))
            except ValueError:
                display = str(path)
            self.reference_paths[display] = path
        values = tuple(self.reference_paths)
        self.reference_combo["values"] = values
        if values:
            self.reference_var.set(values[0])
            self.status_var.set(f"{len(values)} " + ("mögliche Referenzdatei(en) gefunden." if self.language == "de" else "possible reference file(s) found."))
        else:
            self.status_var.set(self.t("no_candidates"))

    def _analyse(self) -> None:
        project = Path(self.project_var.get()).expanduser()
        reference = self.reference_paths.get(self.reference_var.get())
        if not project.is_dir() or reference is None or not reference.is_file():
            messagebox.showerror(getattr(self.app, "title", lambda: "TAcroMan")(), self.t("choose_both"), parent=self)
            return
        try:
            excerpt_radius = int(self.excerpt_radius_var.get().strip())
            if not 0 <= excerpt_radius <= 5000:
                raise ValueError
        except ValueError:
            messagebox.showerror(getattr(self.app, "title", lambda: "TAcroMan")(), self.t("invalid_excerpt_radius"), parent=self)
            return
        try:
            report = audit_project(project, reference, excerpt_radius=excerpt_radius)
        except (OSError, UnicodeError, ValueError) as error:
            messagebox.showerror(getattr(self.app, "title", lambda: "TAcroMan")(), self.t("failed", error=error), parent=self)
            return
        self.report = report
        self._populate(report, project.resolve())

    def _populate(self, report: ReferenceAuditReport, project: Path) -> None:
        self._close_cell_overlay()
        self._active_cell = None
        self._unused_rows = [(item.key, item.title, item.author) for item in report.unused]
        self._used_rows = []

        for item in report.occurrences:
            try:
                file_display = str(item.path.resolve().relative_to(project))
            except ValueError:
                file_display = str(item.path)
            title = item.title if item.defined else self.t("unknown_title")
            self._used_rows.append((file_display, item.line, item.key, title, item.author, item.excerpt))

        self._apply_search_filter()
        self.status_var.set(
            self.t(
                "summary",
                entries=len(report.bibliography),
                used=len(report.used_keys),
                unused=len(report.unused),
                occurrences=len(report.occurrences),
                unknown=len(report.unknown_keys),
                files=len(report.source_files),
            )
        )

    def _on_search_changed(self, *_args: object) -> None:
        if hasattr(self, "unused_tree") and hasattr(self, "used_tree"):
            self._apply_search_filter()

    def _apply_search_filter(self) -> None:
        self._close_cell_overlay()
        self._active_cell = None
        query = self.search_var.get().strip()
        self.unused_tree.delete(*self.unused_tree.get_children())
        self.used_tree.delete(*self.used_tree.get_children())

        for row in self._unused_rows:
            if _row_matches_search(row, query):
                self.unused_tree.insert("", "end", values=row)

        for row in self._used_rows:
            if _row_matches_search(row, query):
                self.used_tree.insert("", "end", values=row)

    def _sort_tree(self, tree: ttk.Treeview, column: str, reverse: bool) -> None:
        self._close_cell_overlay()
        values: list[tuple[object, str]] = []
        for iid in tree.get_children(""):
            value: object = tree.set(iid, column)
            if column == "line":
                try:
                    value = int(str(value))
                except ValueError:
                    pass
            else:
                value = str(value).casefold()
            values.append((value, iid))
        values.sort(key=lambda item: item[0], reverse=reverse)
        for index, (_value, iid) in enumerate(values):
            tree.move(iid, "", index)
        tree.heading(column, command=lambda: self._sort_tree(tree, column, not reverse))
