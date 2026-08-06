"""Domain types and validation for acronym entries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
import re
import unicodedata
from uuid import uuid4

from .i18n import translate


def normalise_for_comparison(value: str) -> str:
    """Normalise whitespace, Unicode and case for duplicate detection."""
    value = unicodedata.normalize("NFKC", value)
    return " ".join(value.casefold().split())


def make_identifier(short: str) -> str:
    """Create a stable, LaTeX-friendly key for packages that need one.

    The original short form is intentionally retained separately.  This means
    that e.g. ``DVL-2`` can still be printed verbatim while a profile such as
    ``glossaries-extra`` receives the key ``dvl_2``.
    """
    value = unicodedata.normalize("NFKD", short).encode("ascii", "ignore").decode()
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return value or "acronym"


@dataclass(slots=True)
class Acronym:
    short: str
    long: str
    category: str = ""
    note: str = ""
    uid: str = field(default_factory=lambda: str(uuid4()))

    @property
    def identifier(self) -> str:
        return make_identifier(self.short)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Acronym":
        return cls(
            short=str(data.get("short", "")),
            long=str(data.get("long", "")),
            category=str(data.get("category", "")),
            note=str(data.get("note", "")),
            uid=str(data.get("uid") or uuid4()),
        )


def validate(acronym: Acronym, *, language: str = "en") -> tuple[list[str], list[str]]:
    """Return blocking errors and non-blocking formatting warnings."""
    errors: list[str] = []
    warnings: list[str] = []
    short = acronym.short.strip()
    long = acronym.long.strip()

    if not short:
        errors.append(translate(language, "error_enter_short"))
    if not long:
        errors.append(translate(language, "error_enter_long"))
    if "\n" in short or "\r" in short:
        errors.append(translate(language, "error_short_linebreak"))
    if "\n" in long or "\r" in long:
        errors.append(translate(language, "error_long_linebreak"))
    if short and any(char.isspace() for char in short):
        warnings.append(translate(language, "warning_short_whitespace"))
    if long.endswith((".", ";", ":")):
        warnings.append(translate(language, "warning_long_punctuation"))
    if short != acronym.short or long != acronym.long:
        warnings.append(translate(language, "warning_trimmed"))
    if any(char in short for char in "{}"):
        warnings.append(translate(language, "warning_short_braces"))
    return errors, warnings


def duplicate_matches(
    candidate: Acronym,
    entries: list[Acronym],
    *,
    ignore_uid: str | None = None,
    threshold: float = 0.68,
) -> tuple[list[Acronym], list[tuple[Acronym, float]]]:
    """Find exact and plausibly similar entries without mutating the database."""
    exact: list[Acronym] = []
    similar: list[tuple[Acronym, float]] = []
    candidate_short = normalise_for_comparison(candidate.short)
    candidate_long = normalise_for_comparison(candidate.long)

    for entry in entries:
        if entry.uid == ignore_uid:
            continue
        short_score = SequenceMatcher(None, candidate_short, normalise_for_comparison(entry.short)).ratio()
        long_score = SequenceMatcher(None, candidate_long, normalise_for_comparison(entry.long)).ratio()
        score = max(short_score, long_score)
        if candidate_short and candidate_short == normalise_for_comparison(entry.short):
            exact.append(entry)
        elif candidate_long and candidate_long == normalise_for_comparison(entry.long):
            exact.append(entry)
        elif score >= threshold:
            similar.append((entry, score))

    similar.sort(key=lambda item: item[1], reverse=True)
    return exact, similar
