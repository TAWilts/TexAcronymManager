from __future__ import annotations

from pathlib import Path
import unittest

import tacroman.app as app_module


class DeletePersistenceTests(unittest.TestCase):
    def test_delete_handler_persists_before_model_update(self) -> None:
        source = Path(app_module.__file__).read_text(encoding="utf-8")

        marker = "# Persist deletion before updating the in-memory/UI state."
        self.assertIn(marker, source)

        marker_pos = source.index(marker)
        save_pos = source.index("save_database(", marker_pos)
        assign_pos = source.index("self.entries = remaining_entries", marker_pos)

        self.assertLess(save_pos, assign_pos)


if __name__ == "__main__":
    unittest.main()
