"""Cross-sectional relative-strength ranking."""

from __future__ import annotations

import numpy as np
import pandas as pd


def relative_strength_value(df: pd.DataFrame, benchmark_df: pd.DataFrame | None = None) -> float:
    close = pd.to_numeric(df.get("Close"), errors="coerce").dropna()
    if len(close) < 40:
        return float("nan")
    lookback = min(252, len(close) - 1)
    skip = min(21, max(1, lookback // 4))
    momentum = float(close.iloc[-skip - 1] / close.iloc[-lookback - 1] - 1) if len(close) > lookback else 0.0
    if benchmark_df is not None and not benchmark_df.empty:
        bench = pd.to_numeric(benchmark_df.get("Close"), errors="coerce").dropna()
        if len(bench) > lookback:
            momentum -= float(bench.iloc[-skip - 1] / bench.iloc[-lookback - 1] - 1)
    high_proximity = float(close.iloc[-1] / close.tail(min(252, len(close))).max())
    return momentum * 0.75 + high_proximity * 0.25


def rank_relative_strength(histories: dict[str, pd.DataFrame], benchmark_df: pd.DataFrame | None = None) -> dict[str, float]:
    raw = pd.Series({ticker: relative_strength_value(frame, benchmark_df) for ticker, frame in histories.items()}, dtype=float)
    return (raw.rank(pct=True) * 100).fillna(0).round(2).to_dict()


def attach_rs_rank(rows: pd.DataFrame, ranks: dict[str, float]) -> pd.DataFrame:
    out = rows.copy()
    out["rs_rank"] = out["ticker"].astype(str).map(ranks).fillna(0.0)
    return out
