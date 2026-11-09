"""Statistics helpers for card functions: regression and day adjustment."""
from __future__ import annotations

import calendar
import datetime as dt

import pandas as pd

from .periods import num


def ols(df: pd.DataFrame, y: str, x: list[str]) -> dict | None:
    """Ordinary least squares y ~ x (with intercept). None when there are too few rows.

    Returns {"n", "r2", "adj_r2", "f_p_value", "rmse", "coefficients": [{term, estimate, std_err, t, p_value,
    ci_low, ci_high}], "fitted": [...], "residuals": [...]} (fitted/residuals in df row order)."""
    import statsmodels.api as sm

    d = df[[y, *x]].dropna()
    if len(d) < len(x) + 2:
        return None
    model = sm.OLS(d[y].astype(float), sm.add_constant(d[x].astype(float), has_constant="add")).fit()
    ci = model.conf_int()
    return {
        "n": int(model.nobs),
        "r2": num(model.rsquared),
        "adj_r2": num(model.rsquared_adj),
        "f_p_value": num(model.f_pvalue),
        "rmse": num(model.mse_resid ** 0.5),
        "coefficients": [
            {"term": term, "estimate": num(model.params[term]), "std_err": num(model.bse[term]), "t": num(model.tvalues[term]),
             "p_value": num(model.pvalues[term]), "ci_low": num(ci.loc[term, 0]), "ci_high": num(ci.loc[term, 1])}
            for term in model.params.index
        ],
        "fitted": [num(v) for v in model.fittedvalues],
        "residuals": [num(v) for v in model.resid],
    }


def working_days(month, holidays: set | None = None) -> int:
    """Monday-Friday days in the month of `month` (date or ISO string), minus any dates in `holidays`."""
    d = dt.date.fromisoformat(str(month)[:10])
    days = calendar.monthrange(d.year, d.month)[1]
    hol = holidays or set()
    return sum(1 for i in range(1, days + 1)
               if dt.date(d.year, d.month, i).weekday() < 5 and dt.date(d.year, d.month, i) not in hol)


def per_working_day(value, month, holidays: set | None = None):
    """value / working days in that month (None when not computable)."""
    v, wd = num(value), working_days(month, holidays)
    return v / wd if v is not None and wd else None
