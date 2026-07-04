"""Scoring rules for the daily stock screener."""

from __future__ import annotations

import math


def _num(value, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(value) else value


def calculate_score(snapshot: dict, targets: dict, context: dict | None = None, config: dict | None = None) -> dict:
    """Calculate a 0-100 technical setup score."""
    cp = _num(snapshot.get("current_price"))
    ma20 = _num(snapshot.get("ma20"))
    ma50 = _num(snapshot.get("ma50"))
    ma200 = _num(snapshot.get("ma200"))
    rsi = _num(snapshot.get("rsi14"), 50)
    vr = _num(snapshot.get("volume_ratio"))
    r5 = _num(snapshot.get("return_5d"))
    r20 = _num(snapshot.get("return_20d"))
    macd = _num(snapshot.get("macd"))
    signal = _num(snapshot.get("macd_signal"))
    hist = _num(snapshot.get("macd_hist"))
    hist_prev = _num(snapshot.get("macd_hist_prev"))
    high20 = _num(snapshot.get("high20"))
    high60 = _num(snapshot.get("high60"))
    low20 = _num(snapshot.get("low20"))
    atr_pct = _num(snapshot.get("atr_pct"))
    risk_reward_raw = _num(targets.get("risk_reward"))
    risk_reward = min(risk_reward_raw, 5.0)

    trend = int(cp > ma20) * 10 + int(cp > ma50) * 8 + int(ma20 > ma50) * 7 + int(cp > ma200) * 5
    if vr >= 1.5:
        volume = 15
    elif vr >= 1.2:
        volume = 10
    elif vr >= 1.0:
        volume = 6
    elif vr >= 0.8:
        volume = 3
    else:
        volume = 0

    momentum = 0
    if 45 <= rsi <= 65:
        momentum += 12
    elif 65 < rsi <= 70:
        momentum += 8
    elif 35 <= rsi < 45:
        momentum += 5
    momentum += int(r5 > 0) * 5 + int(r20 > 0) * 3

    macd_score = int(macd > signal) * 6 + int(hist > hist_prev) * 4
    position = 0
    position += int(high20 and cp >= high20 * 0.97) * 6
    position += int(high60 and cp >= high60 * 0.97) * 4
    position += int(low20 and cp >= low20 * 1.10) * 3
    position += int(cp > ma20 and ma20 and cp / ma20 - 1 <= 0.05) * 2

    if risk_reward >= 2.0:
        rr_score = 10
    elif risk_reward >= 1.5:
        rr_score = 6
    elif risk_reward >= 1.2:
        rr_score = 3
    else:
        rr_score = -5

    penalty = 0
    penalty -= int(rsi >= 75) * 10
    penalty -= int(r5 >= 10) * 6
    penalty -= int(cp < ma20) * 12
    penalty -= int(cp < ma50) * 8
    penalty -= int(bool(ma20) and bool(ma50) and ma20 < ma50) * 8
    penalty -= int(vr < 0.7) * 5
    penalty -= int(atr_pct >= 7) * 5
    penalty -= int(risk_reward_raw > 10) * 8
    penalty -= int(_num(targets.get("target1")) <= cp) * 10
    penalty -= int(_num(targets.get("stop_loss")) >= cp) * 10

    raw = trend + volume + momentum + macd_score + position + rr_score + penalty
    final = max(0, min(100, int(round(raw))))
    if not targets.get("valid", True):
        final = 0

    if context is not None:
        vcp_score = _num(context.get("vcp_score"))
        rs_rank = _num(context.get("rs_rank"))
        weekly = 100.0 if context.get("weekly_trend_ok") else 0.0
        regime = _num(context.get("regime_score"), 0.5) * 100
        weights = (config or {}).get("signal_weights", {})
        base_w = _num(weights.get("base", 0.70), 0.70)
        vcp_w = _num(weights.get("vcp", 0.15), 0.15)
        rs_w = _num(weights.get("rs", 0.10), 0.10)
        mtf_w = _num(weights.get("mtf", 0.03), 0.03)
        regime_w = _num(weights.get("regime", 0.02), 0.02)
        total = max(base_w + vcp_w + rs_w + mtf_w + regime_w, 0.01)
        final = int(round((final * base_w + vcp_score * vcp_w + rs_rank * rs_w + weekly * mtf_w + regime * regime_w) / total))
        min_rs = _num((config or {}).get("ranking", {}).get("min_rs_rank", 0))
        if min_rs and rs_rank < min_rs:
            final = min(final, 64)
        regime_state = str(context.get("regime_state", "neutral"))
        regime_mult = {"risk_on": 1.0, "neutral": 0.90, "risk_off": 0.70}.get(regime_state, 0.90)
        final = int(round(final * regime_mult))
        final = max(0, min(100, final))

    if final >= 80:
        decision = "Strong Candidate"
    elif final >= 65:
        decision = "Candidate"
    elif final >= 50:
        decision = "Watchlist"
    else:
        decision = "Excluded"

    reasons = []
    if cp < ma20 or cp < ma50:
        reasons.append("weak trend")
    if vr < 0.7:
        reasons.append("low volume")
    if risk_reward_raw < 1.2:
        reasons.append("low risk/reward")
    if rsi >= 75:
        reasons.append("overheated RSI")
    if not targets.get("valid", True):
        reasons.append(targets.get("exclude_reason", "invalid targets"))

    return {
        "trend_score": trend,
        "volume_score": volume,
        "momentum_score": momentum,
        "macd_score": macd_score,
        "position_score": position,
        "risk_reward_score": rr_score,
        "risk_penalty": penalty,
        "base_score": max(0, min(100, int(round(raw)))),
        "final_score": final,
        "decision": decision,
        "exclude_reason": "; ".join(reasons),
    }
