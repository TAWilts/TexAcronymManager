"""Helpers for migrating LaTeX citation keys between two BibTeX exports.

The module deliberately stays dependency-free.  It matches bibliography entries
using conservative metadata signals and only rewrites keys inside citation-like
LaTeX commands.  Ambiguous matches are never applied automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
import unicodedata

from .storage import atomic_write_text


_NON_ENTRY_TYPES = {"comment", "preamble", "string"}
_CITE_COMMAND = (
    r"(?:[Cc]ite(?:p|t|alt|alp|author|year|yearpar|title)?|"
    r"[Aa]utocite|[Pp]arencite|[Tt]extcite|[Ff]ootcite(?:text)?|"
    r"[Ss]martcite|[Ss]upercite|[Ff]ullcite|[Vv]olcite|"
    r"[Pp]volcite|[Ff]volcite|[Ss]volcite|[Nn]otecite|nocite)"
)
_CITE_COMMAND_RE = re.compile(
    rf"(?P<prefix>\\{_CITE_COMMAND}\*?(?:\s*\[[^\]]*\]){{0,2}}\s*\{{)"
    r"(?P<keys>[^{}]*)"
    r"(?P<suffix>\})",
    re.MULTILINE,
)
_LATEX_ACCENT_RE = re.compile(r"\\(?:[\"'`^~=.uvHckbdtr])\s*\{?([A-Za-z])\}?")
_LATEX_COMMAND_RE = re.compile(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?")
_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


@dataclass(frozen=True)
class BibEntry:
    """A minimally parsed BibTeX entry."""

    key: str
    entry_type: str
    fields: dict[str, str]

    def field(self, name: str) -> str:
        return self.fields.get(name.casefold(), "")


@dataclass(frozen=True)
class KeyMatch:
    """One old bibliography key and its matching result in the new file."""

    old_key: str
    new_key: str | None
    status: str
    method: str = ""
    title: str = ""
    candidates: tuple[str, ...] = ()

    @property
    def changes_key(self) -> bool:
        return self.status == "matched" and bool(self.new_key) and self.old_key != self.new_key


@dataclass(frozen=True)
class MigrationReport:
    """Result of comparing an old and a new BibTeX export."""

    matches: tuple[KeyMatch, ...]

    @property
    def mapping(self) -> dict[str, str]:
        return {
            item.old_key: item.new_key
            for item in self.matches
            if item.changes_key and item.new_key is not None
        }

    @property
    def changed_count(self) -> int:
        return len(self.mapping)

    @property
    def unmatched_count(self) -> int:
        return sum(item.status == "unmatched" for item in self.matches)

    @property
    def ambiguous_count(self) -> int:
        return sum(item.status == "ambiguous" for item in self.matches)

    @property
    def unchanged_count(self) -> int:
        return sum(item.status == "unchanged" for item in self.matches)


@dataclass(frozen=True)
class FileMigrationResult:
    """Summary of applying a citation-key mapping to TeX files."""

    files_considered: int
    files_changed: int
    replacements: int
    changed_files: tuple[Path, ...] = field(default_factory=tuple)


def parse_bibtex(text: str) -> list[BibEntry]:
    """Parse enough BibTeX/BibLaTeX structure for reliable key matching.

    This is intentionally not a full BibTeX implementation.  It understands
    balanced braces/parentheses, quoted values, nested braces, and the usual
    field syntax produced by Zotero/Better BibTeX.
    """

    entries: list[BibEntry] = []
    pos = 0
    length = len(text)

    while pos < length:
        at = text.find("@", pos)
        if at < 0:
            break

        type_match = re.match(r"@\s*([A-Za-z]+)\s*([({])", text[at:])
        if not type_match:
            pos = at + 1
            continue

        entry_type = type_match.group(1).casefold()
        opener = type_match.group(2)
        closer = "}" if opener == "{" else ")"
        body_start = at + type_match.end()
        body_end = _find_balanced_end(text, body_start, opener, closer)
        if body_end is None:
            break

        body = text[body_start:body_end]
        pos = body_end + 1
        if entry_type in _NON_ENTRY_TYPES:
            continue

        key_end = _find_top_level_char(body, ",")
        if key_end is None:
            continue
        key = body[:key_end].strip()
        if not key:
            continue

        fields = _parse_fields(body[key_end + 1 :])
        entries.append(BibEntry(key=key, entry_type=entry_type, fields=fields))

    return entries


def build_key_migration(old_bib: str, new_bib: str) -> MigrationReport:
    """Build a conservative old-key -> new-key migration report."""

    old_entries = parse_bibtex(old_bib)
    new_entries = parse_bibtex(new_bib)
    new_by_key = {entry.key: entry for entry in new_entries}

    alias_index: dict[str, list[BibEntry]] = {}
    doi_index: dict[str, list[BibEntry]] = {}
    title_year_index: dict[tuple[str, str], list[BibEntry]] = {}
    title_index: dict[str, list[BibEntry]] = {}

    for entry in new_entries:
        for alias in _split_ids(entry.field("ids")):
            alias_index.setdefault(alias, []).append(entry)

        doi = _normalise_doi(entry.field("doi"))
        if doi:
            doi_index.setdefault(doi, []).append(entry)

        title = _normalise_text(entry.field("title"))
        year = _entry_year(entry)
        if title:
            title_index.setdefault(title, []).append(entry)
            if year:
                title_year_index.setdefault((title, year), []).append(entry)

    results: list[KeyMatch] = []
    for old in old_entries:
        title_for_display = _display_value(old.field("title"))

        if old.key in new_by_key:
            results.append(
                KeyMatch(
                    old_key=old.key,
                    new_key=old.key,
                    status="unchanged",
                    method="same-key",
                    title=title_for_display,
                )
            )
            continue

        candidate_sets: list[tuple[str, list[BibEntry]]] = []
        if old.key in alias_index:
            candidate_sets.append(("ids", alias_index[old.key]))

        doi = _normalise_doi(old.field("doi"))
        if doi and doi in doi_index:
            candidate_sets.append(("doi", doi_index[doi]))

        title = _normalise_text(old.field("title"))
        year = _entry_year(old)
        if title and year and (title, year) in title_year_index:
            candidate_sets.append(("title-year", title_year_index[(title, year)]))
        if title and title in title_index:
            candidate_sets.append(("title", title_index[title]))

        selected_method = ""
        selected: list[BibEntry] = []
        for method, candidates in candidate_sets:
            unique = _deduplicate_entries(candidates)
            if len(unique) == 1:
                selected_method = method
                selected = unique
                break
            if len(unique) > 1 and not selected:
                selected_method = method
                selected = unique

        if len(selected) == 1:
            results.append(
                KeyMatch(
                    old_key=old.key,
                    new_key=selected[0].key,
                    status="matched",
                    method=selected_method,
                    title=title_for_display,
                )
            )
        elif len(selected) > 1:
            results.append(
                KeyMatch(
                    old_key=old.key,
                    new_key=None,
                    status="ambiguous",
                    method=selected_method,
                    title=title_for_display,
                    candidates=tuple(entry.key for entry in selected),
                )
            )
        else:
            results.append(
                KeyMatch(
                    old_key=old.key,
                    new_key=None,
                    status="unmatched",
                    title=title_for_display,
                )
            )

    return MigrationReport(tuple(results))


def replace_citation_keys(tex: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Replace mapped keys only inside LaTeX citation-like commands."""

    if not mapping:
        return tex, 0

    replacements = 0

    def replace_command(match: re.Match[str]) -> str:
        nonlocal replacements
        if _is_commented(tex, match.start()):
            return match.group(0)

        pieces = match.group("keys").split(",")
        changed = False
        rewritten: list[str] = []
        for piece in pieces:
            leading = piece[: len(piece) - len(piece.lstrip())]
            trailing = piece[len(piece.rstrip()) :]
            key = piece.strip()
            replacement = mapping.get(key)
            if replacement and replacement != key:
                rewritten.append(f"{leading}{replacement}{trailing}")
                replacements += 1
                changed = True
            else:
                rewritten.append(piece)

        if not changed:
            return match.group(0)
        return f"{match.group('prefix')}{','.join(rewritten)}{match.group('suffix')}"

    return _CITE_COMMAND_RE.sub(replace_command, tex), replacements


def migrate_tex_files(paths: list[Path] | tuple[Path, ...], mapping: dict[str, str], *, backup: bool = True) -> FileMigrationResult:
    """Apply a key mapping to TeX files, optionally creating non-destructive backups."""

    changed_files: list[Path] = []
    total_replacements = 0
    unique_paths = tuple(dict.fromkeys(Path(path).expanduser().resolve() for path in paths))

    for path in unique_paths:
        original = path.read_text(encoding="utf-8-sig")
        migrated, replacements = replace_citation_keys(original, mapping)
        if not replacements or migrated == original:
            continue

        if backup:
            shutil.copy2(path, _next_backup_path(path))
        atomic_write_text(path, migrated)
        changed_files.append(path)
        total_replacements += replacements

    return FileMigrationResult(
        files_considered=len(unique_paths),
        files_changed=len(changed_files),
        replacements=total_replacements,
        changed_files=tuple(changed_files),
    )


def _find_balanced_end(text: str, start: int, opener: str, closer: str) -> int | None:
    depth = 1
    brace_depth = 0
    quote = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue

        if opener == "(":
            if char == '"' and brace_depth == 0:
                quote = not quote
                continue
            if quote:
                continue
            if char == "{":
                brace_depth += 1
                continue
            if char == "}" and brace_depth:
                brace_depth -= 1
                continue
            if brace_depth:
                continue
        else:
            if char == '"':
                quote = not quote
                continue
            if quote:
                continue

        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    return None


def _find_top_level_char(text: str, target: str) -> int | None:
    brace_depth = 0
    paren_depth = 0
    quote = False
    escaped = False

    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"' and brace_depth == 0:
            quote = not quote
            continue
        if quote:
            continue
        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        elif char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif char == target and brace_depth == 0 and paren_depth == 0:
            return index
    return None


def _split_top_level(text: str, separator: str = ",") -> list[str]:
    parts: list[str] = []
    start = 0
    brace_depth = 0
    paren_depth = 0
    quote = False
    escaped = False

    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"' and brace_depth == 0:
            quote = not quote
            continue
        if quote:
            continue
        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        elif char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif char == separator and brace_depth == 0 and paren_depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def _parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in _split_top_level(text):
        if not part.strip():
            continue
        equals = _find_top_level_char(part, "=")
        if equals is None:
            continue
        name = part[:equals].strip().casefold()
        if not name:
            continue
        fields[name] = _unwrap_value(part[equals + 1 :].strip())
    return fields


def _unwrap_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2:
        if value[0] == "{" and value[-1] == "}":
            return value[1:-1].strip()
        if value[0] == '"' and value[-1] == '"':
            return value[1:-1].strip()
    return value


def _normalise_doi(value: str) -> str:
    value = _DOI_PREFIX_RE.sub("", value.strip())
    value = value.strip("{} \t\r\n.").casefold()
    return value


def _normalise_text(value: str) -> str:
    if not value:
        return ""
    value = _LATEX_ACCENT_RE.sub(r"\1", value)
    value = _LATEX_COMMAND_RE.sub("", value)
    value = value.replace("{", "").replace("}", "")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[0-9A-Za-z]+", value.casefold()))


def _display_value(value: str, limit: int = 110) -> str:
    cleaned = " ".join(value.replace("{", "").replace("}", "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _entry_year(entry: BibEntry) -> str:
    year = entry.field("year").strip()
    if year:
        match = re.search(r"\d{4}", year)
        return match.group(0) if match else year
    date = entry.field("date").strip()
    match = re.search(r"\d{4}", date)
    return match.group(0) if match else ""


def _split_ids(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in re.split(r"[,;\s]+", value) if item.strip())


def _deduplicate_entries(entries: list[BibEntry]) -> list[BibEntry]:
    unique: dict[str, BibEntry] = {}
    for entry in entries:
        unique[entry.key] = entry
    return list(unique.values())


def _is_commented(text: str, position: int) -> bool:
    line_start = text.rfind("\n", 0, position) + 1
    escaped = False
    for index in range(line_start, position):
        char = text[index]
        if char == "\\":
            escaped = not escaped
            continue
        if char == "%" and not escaped:
            return True
        escaped = False
    return False


def _next_backup_path(path: Path) -> Path:
    candidate = path.with_name(path.name + ".bak")
    if not candidate.exists():
        return candidate
    counter = 1
    while True:
        candidate = path.with_name(f"{path.name}.bak.{counter}")
        if not candidate.exists():
            return candidate
        counter += 1
