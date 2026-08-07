"""Generic command-entry types, validation, and comparison helpers.

TAcroMan deliberately has no package-specific concepts such as a primary
acronym command or a parent command.  A profile supplies independent command
definitions and the comparison groups that should be checked.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
import re
import unicodedata
from uuid import uuid4

from .i18n import translate


def normalise_for_comparison(value: str, *, case_sensitive: bool = False) -> str:
    """Normalise Unicode and whitespace for a predictable text comparison."""
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    return value if case_sensitive else value.casefold()


def make_identifier(value: str) -> str:
    """Create a stable LaTeX-friendly identifier from a human-facing value."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return value or "entry"


@dataclass(slots=True)
class CommandEntry:
    """One independent command invocation described by a profile."""

    command_id: str
    values: dict[str, str] = field(default_factory=dict)
    uid: str = field(default_factory=lambda: str(uuid4()))

    def value(self, field_id: str) -> str:
        return self.values.get(field_id, "")

    def to_dict(self) -> dict[str, object]:
        return {
            "uid": self.uid,
            "command_id": self.command_id,
            "values": dict(self.values),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CommandEntry":
        values = data.get("values")
        if isinstance(values, dict):
            clean_values = {str(key): str(value) for key, value in values.items()}
            return cls(
                command_id=str(data.get("command_id", "entry")),
                values=clean_values,
                uid=str(data.get("uid") or uuid4()),
            )

        # A permissive fallback for hand-written, pre-v2 records.  Full v1
        # database migration is handled in storage.py, but accepting this
        # shape here makes the public model API pleasant to use as well.
        legacy_fields = ("short", "long", "category", "note")
        return cls(
            command_id=str(data.get("command_id", "acronym")),
            values={name: str(data.get(name, "")) for name in legacy_fields},
            uid=str(data.get("uid") or uuid4()),
        )


@dataclass(slots=True)
class Acronym:
    """Compatibility type for scripts written against TAcroMan 0.2.x.

    The graphical application now uses :class:`CommandEntry`, but retaining
    this small type avoids needlessly breaking existing scripts and the legacy
    importer.
    """

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


def acronym_to_entry(acronym: Acronym) -> CommandEntry:
    """Convert a legacy acronym into the built-in generic command shape."""
    return CommandEntry(
        command_id="acronym",
        values={
            "short": acronym.short,
            "long": acronym.long,
            "category": acronym.category,
            "note": acronym.note,
        },
        uid=acronym.uid,
    )


@dataclass(frozen=True, slots=True)
class ComparisonMatch:
    """A matching comparison-group value between two command entries."""

    entry: CommandEntry
    candidate_field_id: str
    matched_field_id: str
    comparison_group: str


@dataclass(frozen=True, slots=True)
class SimilarityMatch:
    """A non-blocking similarity hint between two configured fields."""

    entry: CommandEntry
    candidate_field_id: str
    matched_field_id: str
    similarity_group: str
    score: float


def command_map(profile: dict[str, object]) -> dict[str, dict[str, object]]:
    """Return the profile's command definitions indexed by their IDs."""
    commands = profile.get("commands", [])
    if not isinstance(commands, list):
        return {}
    return {
        str(command["id"]): command
        for command in commands
        if isinstance(command, dict) and isinstance(command.get("id"), str)
    }


def command_fields(command: dict[str, object]) -> list[dict[str, object]]:
    fields = command.get("fields", [])
    return [field for field in fields if isinstance(field, dict)] if isinstance(fields, list) else []


def validate_entry(
    entry: CommandEntry,
    command: dict[str, object],
    *,
    language: str = "en",
) -> tuple[list[str], list[str]]:
    """Validate only the generic field rules declared by a command profile."""
    errors: list[str] = []
    warnings: list[str] = []

    for field in command_fields(command):
        field_id = str(field["id"])
        label = str(field.get("label") or field_id)
        raw_value = entry.value(field_id)
        value = raw_value.strip()
        if bool(field.get("required")) and not value:
            errors.append(translate(language, "error_field_required", field=label))
        if not bool(field.get("multiline")) and ("\n" in raw_value or "\r" in raw_value):
            errors.append(translate(language, "error_field_linebreak", field=label))
        if raw_value != value:
            warnings.append(translate(language, "warning_field_trimmed", field=label))
        if bool(field.get("warn_whitespace")) and value and any(character.isspace() for character in value):
            warnings.append(translate(language, "warning_field_whitespace", field=label))
        if bool(field.get("warn_trailing_punctuation")) and value.endswith((".", ";", ":")):
            warnings.append(translate(language, "warning_field_punctuation", field=label))
        if bool(field.get("warn_braces")) and any(character in value for character in "{}"):
            warnings.append(translate(language, "warning_field_braces", field=label))

    return _unique_messages(errors), _unique_messages(warnings)


def comparison_matches(
    candidate: CommandEntry,
    candidate_command: dict[str, object],
    entries: list[CommandEntry],
    commands: dict[str, dict[str, object]],
    *,
    ignore_uid: str | None = None,
) -> tuple[list[ComparisonMatch], list[ComparisonMatch]]:
    """Find blocking same-command and warning-only cross-command matches.

    The only special rule is intentionally mechanical: values in equal
    ``comparison_group`` values are compared.  Equal values in the same command
    type block saving, while equal values from another command type merely warn.
    No command is considered a parent, child, primary, or supplement.
    """
    same_command: list[ComparisonMatch] = []
    other_command: list[ComparisonMatch] = []
    seen: set[tuple[str, str, str, str]] = set()

    for candidate_field in command_fields(candidate_command):
        group = str(candidate_field.get("comparison_group", "")).strip()
        candidate_field_id = str(candidate_field["id"])
        candidate_value = candidate.value(candidate_field_id).strip()
        if not group or not candidate_value:
            continue

        for existing in entries:
            if existing.uid == ignore_uid:
                continue
            existing_command = commands.get(existing.command_id)
            if existing_command is None:
                continue
            for existing_field in command_fields(existing_command):
                if str(existing_field.get("comparison_group", "")).strip() != group:
                    continue
                existing_field_id = str(existing_field["id"])
                existing_value = existing.value(existing_field_id).strip()
                if not existing_value:
                    continue
                case_sensitive = bool(candidate_field.get("case_sensitive")) and bool(
                    existing_field.get("case_sensitive")
                )
                if normalise_for_comparison(candidate_value, case_sensitive=case_sensitive) != normalise_for_comparison(
                    existing_value, case_sensitive=case_sensitive
                ):
                    continue
                marker = (existing.uid, candidate_field_id, existing_field_id, group)
                if marker in seen:
                    continue
                seen.add(marker)
                match = ComparisonMatch(existing, candidate_field_id, existing_field_id, group)
                (same_command if existing.command_id == candidate.command_id else other_command).append(match)

    return same_command, other_command


def similarity_matches(
    candidate: CommandEntry,
    candidate_command: dict[str, object],
    entries: list[CommandEntry],
    commands: dict[str, dict[str, object]],
    *,
    ignore_uid: str | None = None,
    threshold: float = 0.68,
) -> list[SimilarityMatch]:
    """Return non-blocking hints for fields sharing a similarity group."""
    matches: list[SimilarityMatch] = []
    seen: set[tuple[str, str, str, str]] = set()

    for candidate_field in command_fields(candidate_command):
        group = str(candidate_field.get("similarity_group", "")).strip()
        candidate_field_id = str(candidate_field["id"])
        candidate_value = candidate.value(candidate_field_id).strip()
        if not group or not candidate_value:
            continue
        candidate_normalised = normalise_for_comparison(
            candidate_value, case_sensitive=bool(candidate_field.get("case_sensitive"))
        )

        for existing in entries:
            if existing.uid == ignore_uid:
                continue
            existing_command = commands.get(existing.command_id)
            if existing_command is None:
                continue
            for existing_field in command_fields(existing_command):
                if str(existing_field.get("similarity_group", "")).strip() != group:
                    continue
                existing_field_id = str(existing_field["id"])
                existing_value = existing.value(existing_field_id).strip()
                if not existing_value:
                    continue
                existing_normalised = normalise_for_comparison(
                    existing_value, case_sensitive=bool(existing_field.get("case_sensitive"))
                )
                score = SequenceMatcher(None, candidate_normalised, existing_normalised).ratio()
                if score < threshold:
                    continue
                marker = (existing.uid, candidate_field_id, existing_field_id, group)
                if marker in seen:
                    continue
                seen.add(marker)
                matches.append(SimilarityMatch(existing, candidate_field_id, existing_field_id, group, score))

    return sorted(matches, key=lambda item: item.score, reverse=True)


def _unique_messages(messages: list[str]) -> list[str]:
    return list(dict.fromkeys(messages))


# The following helpers retain the 0.2.x public API for small external scripts.
def validate(acronym: Acronym, *, language: str = "en") -> tuple[list[str], list[str]]:
    """Validate a legacy acronym without imposing it on generic profiles."""
    command = {
        "fields": [
            {"id": "short", "label": "Short form", "required": True, "warn_whitespace": True, "warn_braces": True},
            {"id": "long", "label": "Long form", "required": True, "warn_trailing_punctuation": True},
        ]
    }
    return validate_entry(acronym_to_entry(acronym), command, language=language)


def duplicate_matches(
    candidate: Acronym,
    entries: list[Acronym],
    *,
    ignore_uid: str | None = None,
    threshold: float = 0.68,
) -> tuple[list[Acronym], list[tuple[Acronym, float]]]:
    """Compatibility implementation of the old short/long matching helper."""
    exact: list[Acronym] = []
    similar: list[tuple[Acronym, float]] = []
    candidate_short = normalise_for_comparison(candidate.short)
    candidate_long = normalise_for_comparison(candidate.long)

    for entry in entries:
        if entry.uid == ignore_uid:
            continue
        entry_short = normalise_for_comparison(entry.short)
        entry_long = normalise_for_comparison(entry.long)
        short_score = SequenceMatcher(None, candidate_short, entry_short).ratio()
        long_score = SequenceMatcher(None, candidate_long, entry_long).ratio()
        score = max(short_score, long_score)
        if candidate_short and candidate_short == entry_short:
            exact.append(entry)
        elif candidate_long and candidate_long == entry_long:
            exact.append(entry)
        elif score >= threshold:
            similar.append((entry, score))

    similar.sort(key=lambda item: item[1], reverse=True)
    return exact, similar
