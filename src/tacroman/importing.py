r"""Import helpers for the legacy ``acronym`` package's \acro command."""

from __future__ import annotations

from pathlib import Path

from .model import Acronym


def _skip_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _braced_group(text: str, index: int) -> tuple[str, int] | None:
    index = _skip_whitespace(text, index)
    if index >= len(text) or text[index] != "{":
        return None
    start = index + 1
    depth = 1
    index += 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index], index + 1
        index += 1
    return None


def parse_acronym_package(text: str) -> list[Acronym]:
    r"""Extract ``\acro{SHORT}{long}`` commands, including nested LaTeX braces."""
    entries: list[Acronym] = []
    offset = 0
    while True:
        command = text.find(r"\acro", offset)
        if command < 0:
            break
        first = _braced_group(text, command + len(r"\acro"))
        second = _braced_group(text, first[1]) if first else None
        if first and second:
            short, long = first[0].strip(), second[0].strip()
            if short and long:
                entries.append(Acronym(short=short, long=long))
            offset = second[1]
        else:
            offset = command + len(r"\acro")
    return entries


def read_tex_file(path: Path) -> str:
    """Read a TeX file using common encodings without modifying its bytes."""
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", data, 0, 1, "No supported text encoding matched")
