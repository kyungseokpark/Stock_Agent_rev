"""Volatility Contraction Pattern scoring."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd


def _safe(value, default: float = 0.0) -> float:
    try:
        value = float(value)
        return default if math.isnan(value) else value
    except (TypeError, ValueError):
        return default


def score_vcp(df: pd.DataFrame, snapshot: dict, config: dict | None = None) -> dict:
    cfg = (config or {}).get("vcp", {})
    base_days = int(cfg.get("base_days", 60))
    work = df.tail(max(base_days, 60)).copy()
    cp = _safe(snapshot.get("current_price"))
    ma50 = _safe(snapshot.get("ma50"))
    ma200 = _safe(snapshot.get("ma200"))
    trend_ok = cp > ma50 > ma200 > 0
    if len(work) < 45 or not trend_ok:
        return {
            "vcp_score": 0.0,
            "vcp_contractions": 0,
            "vcp_contraction_depths": [],
            "vcp_volume_dryup": 0.0,
            "vcp_atr_compression": 0.0,
            "pivot_price": _safe(work["High"].max()) if not work.empty else 0.0,
            "dist_to_pivot_pct": 0.0,
            "vcp_status": "해당없음",
        }

    boundaries = np.linspace(0, len(work), 4, dtype=int)
    segments = [work.iloc[boundaries[i] : boundaries[i + 1]] for i in range(3)]
    depths = []
    for segment in segments:
        high = _safe(segment["High"].max())
        low = _safe(segment["Low"].min())
        depths.append((high - low) / high * 100 if high else 0.0)
    contractions = sum(depths[i] < depths[i - 1] * 0.9 for i in range(1, len(depths))) + 1

    recent_volume = _safe(work["Volume"].tail(10).mean())
    prior_volume = _safe(work["Volume"].iloc[:-10].tail(40).mean())
    volume_dryup = recent_volume / prior_volume if prior_volume else 0.0
    ranges = (work["High"] - work["Low"]) / work["Close"].replace(0, np.nan)
    recent_range = _safe(ranges.tail(10).mean())
    prior_range = _safe(ranges.iloc[:-10].tail(20).mean())
    atr_compression = recent_range / prior_range if prior_range else 1.0
    pivot = _safe(work["High"].iloc[:-1].tail(20).max(), cp)
    dist = (pivot / cp - 1) * 100 if cp else 0.0

    score = 25.0
    score += min(contractions, 3) / 3 * 30
    score += max(0.0, min(1.0, (1.0 - volume_dryup) / 0.4)) * 20
    score += max(0.0, min(1.0, (1.0 - atr_compression) / 0.4)) * 15
    score += max(0.0, 1.0 - abs(dist) / 8.0) * 10
    score = round(max(0.0, min(100.0, score)), 2)
    dryup_limit = float(cfg.get("volume_dryup_max", 0.8))
    near_limit = float(cfg.get("pivot_near_pct", 2.0))
    if abs(dist) <= near_limit and volume_dryup <= dryup_limit and score >= float(cfg.get("min_score", 70)):
        status = "돌파 임박"
    elif score >= 45:
        status = "베이스 형성"
    else:
        status = "해당없음"
    return {
        "vcp_score": score,
        "vcp_contractions": int(contractions),
        "vcp_contraction_depths": [round(value, 2) for value in depths],
        "vcp_volume_dryup": round(volume_dryup, 3),
        "vcp_atr_compression": round(atr_compression, 3),
        "pivot_price": round(pivot, 2),
        "dist_to_pivot_pct": round(dist, 2),
        "vcp_status": status,
    }
