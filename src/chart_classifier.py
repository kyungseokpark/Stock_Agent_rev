"""Simple chart pattern classification."""

from __future__ import annotations


def classify_chart_type(snapshot: dict, vcp: dict | None = None) -> str:
    cp = float(snapshot.get("current_price", 0))
    ma20 = float(snapshot.get("ma20", 0))
    ma50 = float(snapshot.get("ma50", 0))
    rsi = float(snapshot.get("rsi14", 50))
    r5 = float(snapshot.get("return_5d", 0))
    r20 = float(snapshot.get("return_20d", 0))
    vr = float(snapshot.get("volume_ratio", 0))
    high20 = float(snapshot.get("high20", 0))
    high60 = float(snapshot.get("high60", 0))

    if vcp and float(vcp.get("vcp_score", 0)) >= 70 and vcp.get("vcp_status") == "돌파 임박":
        return "VCP breakout"
    if vcp and float(vcp.get("vcp_score", 0)) >= 45:
        return "VCP base"

    if cp > ma20 > 0 and cp > ma50 and 45 <= rsi <= 65 and r5 > 0 and cp / ma20 - 1 <= 0.05:
        return "Pullback rebound"
    if high20 and cp >= high20 * 0.98 and vr >= 1.2 and cp > ma20:
        return "Box breakout"
    if cp > ma20 > 0 and cp / ma20 - 1 <= 0.03 and r5 > 0:
        return "20MA rebound"
    if high60 and cp >= high60 * 0.97 and cp > ma20 and cp > ma50:
        return "Near new high"
    if 35 <= rsi <= 45 and r5 > 0:
        return "Oversold rebound"
    if r20 > 0 and cp > ma20 and vr >= 1.0:
        return "Relative strength leader"
    return "Watchlist pattern"
