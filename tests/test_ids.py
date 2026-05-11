from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.canonical.ids import make_company_id, make_listing_id, make_security_id, normalize_name


class IdTests(unittest.TestCase):
    def test_normalize_name(self) -> None:
        self.assertEqual(normalize_name(" Acme, Inc. "), "acme inc")

    def test_ids_are_stable(self) -> None:
        company_id = make_company_id("Acme", "US")
        security_id = make_security_id(company_id, "Common Stock")
        listing_id = make_listing_id(security_id, "US", "ACME")
        self.assertTrue(company_id.startswith("cmp_"))
        self.assertTrue(security_id.startswith("sec_"))
        self.assertTrue(listing_id.startswith("lst_"))


if __name__ == "__main__":
    unittest.main()
