from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.canonical.ranking import add_ranks


class RankingTests(unittest.TestCase):
    def test_ranks_descending(self) -> None:
        rows = [
            {"ticker": "A", "total_garp_score": 0.9},
            {"ticker": "B", "total_garp_score": 0.5},
        ]
        ranked = add_ranks(rows)
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[0]["ticker"], "A")


if __name__ == "__main__":
    unittest.main()
