"""Test the sanity check logic directly."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))

# Simulate bad TSM quarterly row
rev = 15_290_000_000   # 15.29B USD
ni  = 181_800_000_000  # 181.8B (TWD, wrong currency)

print(f"rev={rev/1e9:.2f}B  ni={ni/1e9:.2f}B")
print(f"ni > rev*1.5: {ni > rev * 1.5}")  # Should be True

# Now import and test actual function
from app_enhanced import _fundamentals_period_row
import inspect
src = inspect.getsource(_fundamentals_period_row)
print(f"\nHas _currency_mismatch: {'_currency_mismatch' in src}")

# Build a fake inc/cf dict mimicking a bad-currency TSM quarter
fake_inc = {
    "totalRevenue": str(rev),
    "netIncome": str(ni),
    "dilutedEPS": "35.05",
    "weightedAverageShsOutDil": "25900000000",
}
fake_cf = {}

row = _fundamentals_period_row(
    fake_inc, fake_cf,
    period_end="2023-06-30",
    label="Q2'23",
    fiscal_year=2023,
    shares_default=25_900_000_000,
)
print(f"\nResult row:")
print(f"  net_income_usd = {row['net_income_usd']/1e9:.2f}B  (expected 0.0)")
print(f"  eps            = {row['eps']}  (expected 0.0)")
