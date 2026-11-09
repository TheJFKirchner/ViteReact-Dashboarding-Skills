"""EXAMPLE dataset (synthetic retail sales). Delete once real pipeline scripts exist.

Monthly revenue by region for the 25 months ending at the run's "Data as of" month (slow parameter).
Deterministic: a month's value depends only on the calendar month and region, so changing as_of
shifts the window without changing the numbers.
"""
import datetime as dt
import math

from _dataset_io import last_month_end, params, write_dataset

_as_of = params().get("as_of")
# a month-end date when the project has that parameter; anything else (none, a string) -> the last complete month
END = _as_of if isinstance(_as_of, dt.date) else last_month_end()
MONTHS = 25
REGIONS = {"North": 410_000, "South": 350_000, "East": 520_000, "West": 300_000}  # base monthly revenue
GROWTH = 0.04  # per year


def month_starts():
    y, m = END.year, END.month
    out = []
    for _ in range(MONTHS):
        out.append(dt.date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


rows = []
for month in month_starts():
    t = (month.year - 2020) * 12 + month.month  # calendar-month index (independent of as_of)
    season = 1 + 0.12 * math.cos(2 * math.pi * (month.month - 12) / 12)  # December peak
    for k, (region, base) in enumerate(REGIONS.items()):
        wobble = 1 + 0.03 * math.sin(t * 1.3 + k * 2.1)
        rows.append({
            "month": month.isoformat(),
            "region": region,
            "revenue": round(base * (1 + GROWTH) ** (t / 12) * season * wobble, 2),
        })

write_dataset(
    "sales_monthly",
    rows,
    grain="month x region",
    source=f"Synthetic example - sales through {END:%b %Y}",
    description="Revenue by month and region",
    as_of=END.isoformat(),
)
