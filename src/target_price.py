"""Target and stop price calculations."""

from __future__ import annotations

import math


def _round(value: float) -> float:
    return round(float(value), 2)


def calculate_targets(snapshot: dict, config: dict) -> dict:
    """Calculate stop loss, target prices, expected return, and risk/reward."""
    risk_cfg = config.get("risk", {})
    current = float(snapshot.get("current_price", 0))
    ma20 = float(snapshot.get("ma20", 0))
    atr = float(snapshot.get("atr14", 0))
    high20 = float(snapshot.get("high20", 0))
    high60 = float(snapshot.get("high60", 0))

    if current <= 0 or atr <= 0 or math.isnan(atr):
        return {
            "valid": False,
            "exclude_reason": "ATR or current price is unavailable",
            "stop_loss": None,
            "target1": None,
            "target2": None,
            "expected_return_1": 0.0,
            "expected_return_2": 0.0,
            "downside_risk": 0.0,
            "risk_reward": 0.0,
        }

    stop_mult = float(risk_cfg.get("atr_stop_multiplier", 1.5))
    target1_mult = float(risk_cfg.get("atr_target1_multiplier", 1.5))
    target2_mult = float(risk_cfg.get("atr_target2_multiplier", 2.5))

    stop_loss = max(ma20, current - stop_mult * atr)
    if stop_loss >= current:
        stop_loss = current - 1.2 * atr

    target1 = min(high20, current + target1_mult * atr)
    if target1 <= current:
        target1 = current + target1_mult * atr

    target2 = min(high60, current + target2_mult * atr)
    if target2 <= target1:
        target2 = current + target2_mult * atr

    downside = (current / stop_loss - 1) * 100 if stop_loss > 0 else 0.0
    exp1 = (target1 / current - 1) * 100
    exp2 = (target2 / current - 1) * 100
    risk_reward = exp1 / downside if downside > 0 else 0.0
    return {
        "valid": True,
        "exclude_reason": "",
        "stop_loss": _round(stop_loss),
        "target1": _round(target1),
        "target2": _round(target2),
        "expected_return_1": round(exp1, 2),
        "expected_return_2": round(exp2, 2),
        "downside_risk": round(downside, 2),
        "risk_reward": round(risk_reward, 2),
    }
