"""Helpers for mapping Tk Treeview selections back to model entries."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol


class _EntryWithUID(Protocol):
    uid: str


def selected_entry_uids(
    selected_iids: Iterable[str],
    row_iids: Sequence[str],
    visible_entries: Sequence[_EntryWithUID],
) -> set[str]:
    """Resolve selected Treeview rows to model UIDs.

    Rows may use either the model UID directly or Tk-generated identifiers such
    as ``I001``. In the latter case, row position is mapped to the same ordered
    visible-entry list used to populate the table. This stays correct when the
    table is sorted or filtered.
    """
    selected = tuple(str(iid) for iid in selected_iids)
    if not selected:
        return set()

    visible_by_uid = {str(entry.uid): entry for entry in visible_entries}
    row_index = {str(iid): index for index, iid in enumerate(row_iids)}
    result: set[str] = set()

    for iid in selected:
        if iid in visible_by_uid:
            result.add(iid)
            continue
        index = row_index.get(iid)
        if index is None or index >= len(visible_entries):
            continue
        result.add(str(visible_entries[index].uid))

    return result
