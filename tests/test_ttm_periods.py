import unittest

from equity_sorter.canonical.ttm_periods import (
    select_ttm_period_keys,
    ttm_flow_period_count,
)


class TtmPeriodTests(unittest.TestCase):
    def test_quarterly_us_four_periods(self) -> None:
        keys = ["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
        self.assertEqual(ttm_flow_period_count(keys), 4)
        self.assertEqual(len(select_ttm_period_keys(keys)), 4)

    def test_semi_annual_nestle_two_periods(self) -> None:
        keys = [
            "2025-12-31",
            "2025-06-30",
            "2024-12-31",
            "2024-06-30",
            "2024-03-31",
        ]
        self.assertEqual(ttm_flow_period_count(keys), 2)
        self.assertEqual(
            select_ttm_period_keys(keys),
            ["2025-12-31", "2025-06-30"],
        )

    def test_semi_annual_two_year_four_halves(self) -> None:
        keys = [
            "2025-12-31",
            "2025-06-30",
            "2024-12-31",
            "2024-06-30",
            "2023-12-31",
            "2023-06-30",
        ]
        self.assertEqual(len(select_ttm_period_keys(keys, trailing_years=2)), 4)


if __name__ == "__main__":
    unittest.main()
