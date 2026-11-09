"""Period and arithmetic helpers for card functions (pandas). Return None (not 0) when a value can't be
computed; commentary shows None as "n/a"."""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd


def num(v):
    """A finite float, or None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def ratio(a, b):
    a, b = num(a), num(b)
    return a / b if a is not None and b else None


def change(current, prior):
    """Fractional change: 0.052 = +5.2%."""
    c, p = num(current), num(prior)
    return c / p - 1 if c is not None and p else None


share = ratio


def total(df: pd.DataFrame, col: str) -> float:
    return float(df[col].sum()) if len(df) else 0.0


def distinct(df: pd.DataFrame, col: str) -> list:
    return sorted(df[col].dropna().unique().tolist()) if len(df) else []


def sum_by(df: pd.DataFrame, key: str, col: str) -> dict:
    """{key value: sum(col)}."""
    if not len(df):
        return {}
    return {k: float(v) for k, v in df.groupby(key, sort=True)[col].sum().items()}


def last_periods(df: pd.DataFrame, n: int, col: str = "month", offset: int = 0, end=None) -> pd.DataFrame:
    """Rows in the last n periods of `col` (ISO strings), skipping the most recent `offset`.
    end: only periods <= end count (e.g. the as-of month). Empty when fewer than n periods exist."""
    periods = distinct(df, col)
    if end is not None:
        periods = [p for p in periods if str(p) <= str(end)]
    stop = len(periods) - offset
    if stop - n < 0:
        return df.iloc[0:0]
    keep = set(periods[stop - n:stop])
    return df[df[col].isin(keep)]


def top_key(d: dict, absolute: bool = False):
    """Key with the largest value (by absolute value when absolute=True), or None."""
    best = None
    for k, v in d.items():
        v = num(v)
        if v is None:
            continue
        score = abs(v) if absolute else v
        if best is None or score > best[1]:
            best = (k, score)
    return best[0] if best else None


def quantile(values, q: float):
    v = sorted(x for x in (num(x) for x in values) if x is not None)
    if not v:
        return None
    pos = (len(v) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def month_label(iso) -> str | None:
    """"2026-10-01" or "2026-10" -> "Oct 2026"."""
    if not iso:
        return None
    text = str(iso)[:10]
    d = dt.date.fromisoformat(text if len(text) == 10 else f"{text[:7]}-01")
    return d.strftime("%b %Y")
