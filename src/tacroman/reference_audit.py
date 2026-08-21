"""Audit bibliography entries against citations in a LaTeX project.

The implementation is intentionally dependency-free.  It reuses TAcroMan's
small BibTeX parser and scans common LaTeX citation commands directly, so an
audit does not require a successful LaTeX/Biber build first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re

from .bib_migration import BibEntry, parse_bibtex

_SOURCE_SUFFIXES = {".tex", ".ltx", ".sty", ".cls"}
_REFERENCE_CANDIDATE_SUFFIXES = {".bib", ".bibtex", ".tex", ".ltx", ".txt", ".bbl"}
_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    "out",
}

# Common singular citation commands.  The parser also accepts a trailing star
# and up to any number of optional [...] arguments before the key group.
_SINGULAR_CITE_COMMANDS = {
    "cite",
    "citep",
    "citet",
    "citealt",
    "citealp",
    "citeauthor",
    "citeyear",
    "citeyearpar",
    "citetitle",
    "autocite",
    "parencite",
    "textcite",
    "footcite",
    "footcitetext",
    "smartcite",
    "supercite",
    "fullcite",
    "notecite",
    "nocite",
}
_MULTICITE_COMMANDS = {
    "cites",
    "autocites",
    "parencites",
    "textcites",
    "footcites",
    "smartcites",
    "supercites",
}
_CITE_COMMAND_RE = re.compile(r"\\(?P<name>[A-Za-z]+)\*?")
_VERBATIM_RE = re.compile(
    r"\\begin\{(?P<env>verbatim\*?|Verbatim|lstlisting|minted|comment)\}.*?"
    r"\\end\{(?P=env)\}",
    re.DOTALL,
)


@dataclass(frozen=True)
class ReferenceSummary:
    """Bibliography metadata used by the audit tables."""

    key: str
    title: str
    author: str


@dataclass(frozen=True)
class CitationOccurrence:
    """One concrete citation-key occurrence in a project source file."""

    path: Path
    line: int
    key: str
    title: str
    author: str
    excerpt: str
    defined: bool


@dataclass(frozen=True)
class ReferenceAuditReport:
    """Result of comparing a bibliography with a LaTeX project."""

    bibliography: tuple[ReferenceSummary, ...]
    unused: tuple[ReferenceSummary, ...]
    occurrences: tuple[CitationOccurrence, ...]
    unknown_keys: tuple[str, ...]
    source_files: tuple[Path, ...]

    @property
    def used_keys(self) -> tuple[str, ...]:
        known = {entry.key for entry in self.bibliography}
        return tuple(sorted({item.key for item in self.occurrences if item.key in known}, key=str.casefold))


@dataclass(frozen=True)
class _RawOccurrence:
    path: Path
    line: int
    key: str
    excerpt: str


def discover_reference_files(project_dir: Path) -> tuple[Path, ...]:
    """Return project files that actually contain parseable BibTeX entries.

    This keeps the UI dropdown useful even when the bibliography has a less
    common extension or lives in a nested project directory.
    """

    project_dir = Path(project_dir).expanduser().resolve()
    if not project_dir.is_dir():
        return ()

    candidates: list[Path] = []
    for path in _iter_project_files(project_dir, _REFERENCE_CANDIDATE_SUFFIXES):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        if parse_bibtex(text):
            candidates.append(path)

    def sort_key(path: Path) -> tuple[int, int, str]:
        name = path.name.casefold()
        preferred = {
            "refs.bib": 0,
            "references.bib": 1,
            "reference.bib": 2,
            "bibliography.bib": 3,
        }.get(name, 10)
        suffix_rank = 0 if path.suffix.casefold() in {".bib", ".bibtex"} else 1
        try:
            relative = str(path.relative_to(project_dir)).casefold()
        except ValueError:
            relative = str(path).casefold()
        return preferred, suffix_rank, relative

    return tuple(sorted(candidates, key=sort_key))


def audit_project(project_dir: Path, reference_file: Path, *, excerpt_radius: int = 50) -> ReferenceAuditReport:
    """Compare all bibliography entries with citation uses in project sources."""

    project_dir = Path(project_dir).expanduser().resolve()
    reference_file = Path(reference_file).expanduser().resolve()
    if not project_dir.is_dir():
        raise ValueError(f"Project directory does not exist: {project_dir}")
    if not reference_file.is_file():
        raise ValueError(f"Reference file does not exist: {reference_file}")

    reference_text = reference_file.read_text(encoding="utf-8-sig")
    entries = parse_bibtex(reference_text)
    if not entries:
        raise ValueError("No BibTeX/BibLaTeX entries were found in the selected reference file.")

    # Keep the first occurrence of duplicate keys.  Duplicate-key validation is
    # deliberately outside the scope of this audit.
    by_key: dict[str, BibEntry] = {}
    for entry in entries:
        by_key.setdefault(entry.key, entry)

    bibliography = tuple(
        ReferenceSummary(
            key=entry.key,
            title=_display_field(entry.field("title")),
            author=_display_field(entry.field("author") or entry.field("editor")),
        )
        for entry in by_key.values()
    )
    summary_by_key = {entry.key: entry for entry in bibliography}

    source_files = tuple(
        path for path in _iter_project_files(project_dir, _SOURCE_SUFFIXES) if path.resolve() != reference_file
    )
    raw_occurrences: list[_RawOccurrence] = []
    nocite_all = False
    for path in source_files:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        found, has_nocite_all = find_citation_occurrences(text, path, excerpt_radius=excerpt_radius)
        raw_occurrences.extend(found)
        nocite_all = nocite_all or has_nocite_all

    occurrences: list[CitationOccurrence] = []
    for item in raw_occurrences:
        summary = summary_by_key.get(item.key)
        occurrences.append(
            CitationOccurrence(
                path=item.path,
                line=item.line,
                key=item.key,
                title=summary.title if summary else "",
                author=summary.author if summary else "",
                excerpt=item.excerpt,
                defined=summary is not None,
            )
        )

    used = {item.key for item in raw_occurrences if item.key in summary_by_key}
    if nocite_all:
        used.update(summary_by_key)
    unused = tuple(sorted((item for item in bibliography if item.key not in used), key=lambda item: item.key.casefold()))
    unknown_keys = tuple(sorted({item.key for item in raw_occurrences if item.key not in summary_by_key}, key=str.casefold))
    occurrences.sort(key=lambda item: (str(item.path).casefold(), item.line, item.key.casefold()))

    return ReferenceAuditReport(
        bibliography=tuple(sorted(bibliography, key=lambda item: item.key.casefold())),
        unused=unused,
        occurrences=tuple(occurrences),
        unknown_keys=unknown_keys,
        source_files=source_files,
    )


def find_citation_occurrences(
    text: str,
    path: Path = Path("document.tex"),
    *,
    excerpt_radius: int = 50,
) -> tuple[list[_RawOccurrence], bool]:
    """Find citation keys in common LaTeX citation commands.

    Commented text and common verbatim/code environments are ignored while
    character positions are preserved for accurate line/excerpt reporting.
    """

    masked = _mask_non_source_text(text)
    line_starts = _line_starts(text)
    results: list[_RawOccurrence] = []
    nocite_all = False

    for command_match in _CITE_COMMAND_RE.finditer(masked):
        name = command_match.group("name").casefold()
        is_multi = name in _MULTICITE_COMMANDS
        if not is_multi and name not in _SINGULAR_CITE_COMMANDS:
            continue

        cursor = command_match.end()
        groups_found = 0
        while cursor < len(masked):
            cursor = _skip_whitespace(masked, cursor)
            # Prenote/postnote arguments may precede each citation-key group.
            while cursor < len(masked) and masked[cursor] == "[":
                end = _balanced_group_end(masked, cursor, "[", "]")
                if end is None:
                    break
                cursor = _skip_whitespace(masked, end + 1)
            if cursor >= len(masked) or masked[cursor] != "{":
                break
            end = _balanced_group_end(masked, cursor, "{", "}")
            if end is None:
                break
            groups_found += 1
            content_start = cursor + 1
            content = masked[content_start:end]
            for key, offset in _split_keys_with_offsets(content):
                if name == "nocite" and key == "*":
                    nocite_all = True
                    continue
                absolute = content_start + offset
                results.append(
                    _RawOccurrence(
                        path=Path(path),
                        line=_line_for_position(line_starts, absolute),
                        key=key,
                        excerpt=_excerpt(text, absolute, len(key), excerpt_radius),
                    )
                )
            cursor = end + 1
            if not is_multi:
                break
            # Multi-cite commands may contain repeated [pre][post]{key} groups.
            if groups_found > 1000:  # defensive guard for malformed input
                break

    return results, nocite_all


def _iter_project_files(project_dir: Path, suffixes: set[str]):
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [name for name in dirs if name not in _IGNORED_DIRS and not name.startswith(".latexmk")]
        root_path = Path(root)
        for filename in files:
            path = root_path / filename
            if path.suffix.casefold() in suffixes:
                yield path.resolve()


def _display_field(value: str, limit: int = 180) -> str:
    cleaned = value.replace("{", "").replace("}", "").replace("~", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _mask_non_source_text(text: str) -> str:
    chars = list(text)

    # Mask common verbatim/code environments first so percent signs inside them
    # are not interpreted as comments.
    for match in _VERBATIM_RE.finditer(text):
        for index in range(match.start(), match.end()):
            if chars[index] not in "\r\n":
                chars[index] = " "

    masked = "".join(chars)
    chars = list(masked)
    line_start = 0
    for line in masked.splitlines(keepends=True):
        escaped = False
        for offset, char in enumerate(line):
            if char in "\r\n":
                break
            if char == "\\":
                escaped = not escaped
                continue
            if char == "%" and not escaped:
                for index in range(line_start + offset, line_start + len(line)):
                    if chars[index] not in "\r\n":
                        chars[index] = " "
                break
            escaped = False
        line_start += len(line)
    return "".join(chars)


def _skip_whitespace(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _balanced_group_end(text: str, start: int, opener: str, closer: str) -> int | None:
    if start >= len(text) or text[start] != opener:
        return None
    depth = 0
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_keys_with_offsets(content: str) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    start = 0
    for index in range(len(content) + 1):
        if index != len(content) and content[index] != ",":
            continue
        raw = content[start:index]
        key = raw.strip()
        if key:
            leading = len(raw) - len(raw.lstrip())
            result.append((key, start + leading))
        start = index + 1
    return result


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for match in re.finditer("\n", text):
        starts.append(match.end())
    return starts


def _line_for_position(starts: list[int], position: int) -> int:
    # Small binary search without another dependency/import.
    low = 0
    high = len(starts)
    while low + 1 < high:
        middle = (low + high) // 2
        if starts[middle] <= position:
            low = middle
        else:
            high = middle
    return low + 1


def _excerpt(text: str, position: int, key_length: int, radius: int) -> str:
    radius = max(0, int(radius))
    start = max(0, position - radius)
    end = min(len(text), position + key_length + radius)
    excerpt = text[start:end].replace("\r", " ").replace("\n", " ").replace("\t", " ")
    excerpt = " ".join(excerpt.split())
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(text):
        excerpt += "…"
    return excerpt
