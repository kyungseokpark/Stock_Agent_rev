"""OHLCV normalization and quality checks shared by screening and backtests."""

from __future__ import annotations

import numpy as np
import pandas as pd

PRICE_COLUMNS = ["Open", "High", "Low", "Close"]


def normalize_ohlcv(df: pd.DataFrame, *, apply_adjustment: bool = True) -> tuple[pd.DataFrame, dict]:
    if df is None or df.empty:
        return pd.DataFrame(), {"data_quality_flag": "poor", "data_quality_reasons": "empty_data"}

    out = df.copy()
    out.index = pd.to_datetime(out.index, errors="coerce").tz_localize(None)
    out = out[~out.index.isna()].sort_index()
    out = out[~out.index.duplicated(keep="last")]
    for column in [*PRICE_COLUMNS, "Adj Close", "Volume"]:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    missing = [column for column in [*PRICE_COLUMNS, "Volume"] if column not in out.columns]
    if missing:
        return pd.DataFrame(), {
            "data_quality_flag": "poor",
            "data_quality_reasons": f"missing_columns:{','.join(missing)}",
        }

    if apply_adjustment and "Adj Close" in out.columns:
        ratio = (out["Adj Close"] / out["Close"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        for column in PRICE_COLUMNS:
            out[column] = out[column] * ratio
        out["Close"] = out["Adj Close"].fillna(out["Close"])

    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=PRICE_COLUMNS)
    out = out[(out[PRICE_COLUMNS] > 0).all(axis=1)]
    out["Volume"] = out["Volume"].fillna(0).clip(lower=0)
    if "Adj Close" not in out.columns:
        out["Adj Close"] = out["Close"]

    reasons: list[str] = []
    zero_volume_ratio = float((out["Volume"] <= 0).mean()) if len(out) else 1.0
    stale_ratio = float((out["Close"].pct_change().fillna(0).abs() < 1e-10).rolling(5).sum().ge(5).mean())
    bad_bar_ratio = float(((out["High"] < out[["Open", "Close"]].max(axis=1)) | (out["Low"] > out[["Open", "Close"]].min(axis=1))).mean())
    if zero_volume_ratio > 0.05:
        reasons.append("zero_volume")
    if stale_ratio > 0.05:
        reasons.append("stale_price")
    if bad_bar_ratio > 0:
        reasons.append("invalid_ohlc")
        out["High"] = out[["Open", "High", "Low", "Close"]].max(axis=1)
        out["Low"] = out[["Open", "High", "Low", "Close"]].min(axis=1)

    flag = "good" if not reasons else "warning"
    if len(out) < 60 or zero_volume_ratio > 0.3:
        flag = "poor"
    return out, {
        "data_quality_flag": flag,
        "data_quality_reasons": ",".join(reasons),
        "zero_volume_ratio": round(zero_volume_ratio, 4),
        "stale_price_ratio": round(stale_ratio, 4),
        "rows_after_quality": len(out),
    }
