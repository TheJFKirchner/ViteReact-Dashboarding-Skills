"""EXAMPLE cards (summary KPI, revenue trend) on the synthetic sales_monthly table. Replace with real ones."""
from Shared.periods import change, distinct, last_periods, month_label, sum_by, top_key, total
from Shared.registry import section


def t12(df, offset=0):
    """Trailing 12 months (offset=12: the 12 before that)."""
    return last_periods(df, 12, offset=offset)


@section("s1_summary", tables=["sales_monthly"])
def summary(t):
    sales = t.sales_monthly
    months = distinct(sales, "month")
    by_month = sum_by(sales, "month", "revenue")
    cur, prior = t12(sales), t12(sales, 12)
    return {
        "data": {"revenue_spark": [by_month[m] for m in months[-24:]]},
        "metrics": {
            "latest_month": month_label(months[-1]) if months else None,
            "revenue_t12": total(cur, "revenue") if len(cur) else None,
            "revenue_change": change(total(cur, "revenue"), total(prior, "revenue")),
        },
    }


@section("s2_revenue_trend", tables=["sales_monthly"])
def revenue_trend(t):
    sales = t.sales_monthly
    months = distinct(sales, "month")
    by_month = sum_by(sales, "month", "revenue")
    latest = months[-1] if months else None
    year_ago = months[-13] if len(months) >= 13 else None
    peak = top_key(sum_by(t12(sales), "month", "revenue"))
    return {
        "data": {"months": [month_label(m) for m in months], "revenue": [by_month[m] for m in months]},
        "metrics": {
            "latest_month": month_label(latest),
            "latest_revenue": by_month.get(latest),
            "yoy_change": change(by_month.get(latest), by_month.get(year_ago)),
            "peak_month": month_label(peak),
        },
    }
