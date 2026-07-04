"""Earnings-event risk flags with safe unknown handling."""

from __future__ import annotations

from collections.abc import Iterable
import pandas as pd


def earnings_context(
    as_of_date,
    earnings_dates: Iterable | None = None,
    *,
    window_days: int = 5,
) -> dict:
    as_of = pd.Timestamp(as_of_date).normalize()
    if earnings_dates is None:
        return {"earnings_in_window": False, "next_earnings_date": None, "earnings_unknown": True}
    dates = sorted(pd.Timestamp(value).normalize() for value in earnings_dates if pd.notna(value))
    future = [value for value in dates if value >= as_of]
    next_date = future[0] if future else None
    in_window = bool(next_date is not None and 0 <= (next_date - as_of).days <= window_days + 2)
    return {
        "earnings_in_window": in_window,
        "next_earnings_date": next_date.date().isoformat() if next_date is not None else None,
        "earnings_unknown": False,
    }
