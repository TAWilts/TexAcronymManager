from __future__ import annotations

from dataclasses import dataclass
import unittest

from tacroman.table_selection import selected_entry_uids


@dataclass
class _Entry:
    uid: str


class TableSelectionTests(unittest.TestCase):
    def test_maps_tk_generated_iid_by_visible_row_order(self) -> None:
        visible = [_Entry("uid-b"), _Entry("uid-a"), _Entry("uid-c")]
        self.assertEqual(
            selected_entry_uids(["I002"], ["I001", "I002", "I003"], visible),
            {"uid-a"},
        )

    def test_accepts_uid_as_tree_iid(self) -> None:
        visible = [_Entry("uid-b"), _Entry("uid-a")]
        self.assertEqual(
            selected_entry_uids(["uid-a"], ["uid-b", "uid-a"], visible),
            {"uid-a"},
        )

    def test_unknown_selection_is_ignored(self) -> None:
        visible = [_Entry("uid-a")]
        self.assertEqual(
            selected_entry_uids(["missing"], ["I001"], visible),
            set(),
        )


if __name__ == "__main__":
    unittest.main()
