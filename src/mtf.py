"""Weekly trend confirmation for daily signals."""

from __future__ import annotations

import pandas as pd


def weekly_trend_context(df: pd.DataFrame, config: dict | None = None) -> dict:
    weeks = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    period = int((config or {}).get("mtf", {}).get("weekly_ma_period", 30))
    if len(weeks) < period + 4:
        return {"weekly_trend_ok": False, "weekly_ma30": float("nan"), "weekly_trend_reason": "주봉 이력 부족"}
    ma = weeks["Close"].rolling(period).mean()
    last_close = float(weeks["Close"].iloc[-1])
    last_ma = float(ma.iloc[-1])
    rising = last_ma > float(ma.iloc[-4])
    return {
        "weekly_trend_ok": bool(last_close > last_ma and rising),
        "weekly_ma30": round(last_ma, 2),
        "weekly_trend_reason": "주봉 상승 추세" if last_close > last_ma and rising else "주봉 추세 미충족",
    }
