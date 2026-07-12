"""Supplementary technical-signal helpers."""

from __future__ import annotations

import math

from .analysis_enrichment import calculate_chase_risk


def _number(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def dema_stoch_signals(snapshot: dict, config: dict) -> dict[str, bool]:
    """Return DEMA/Stochastic confirmation flags without raising on missing data."""
    settings = config.get("scoring", {}).get("dema_stoch", {})
    if not settings.get("enabled", False):
        return {
            "dema60_breakout": False,
            "dema60_slope_up": False,
            "stoch_d_cross_50_up": False,
            "vol_surge": False,
            "index_above": False,
            "candle_overheat": False,
            "atr_stop_excess": False,
        }

    close = _number(snapshot.get("current_price"))
    prev_close = _number(snapshot.get("previous_close"))
    dema = _number(snapshot.get("dema60"))
    dema_prev = _number(snapshot.get("dema60_prev"))
    stoch_d = _number(snapshot.get("stoch_d"))
    stoch_d_prev = _number(snapshot.get("stoch_d_prev"))
    volume_ratio = _number(snapshot.get("volume_ratio"))

    vol_surge_mult = _number(settings.get("vol_surge_mult"))
    overheat_gap_pct = _number(settings.get("overheat_gap_pct"))
    candle_return_pct = _number(settings.get("candle_return_pct"))
    atr_stop_excess_mult = _number(settings.get("atr_stop_excess_mult"))

    # Reuse the established chase-risk calculation for its MA distance and
    # daily-return values; the module-specific thresholds remain configurable.
    chase_risk = calculate_chase_risk(snapshot)
    distance_from_ma20 = _number(chase_risk.get("distance_from_ma20"))
    last_day_return = _number(chase_risk.get("last_day_return"))

    atr14 = _number(snapshot.get("atr14"))
    stop_loss = _number(snapshot.get("stop_loss"))
    stop_distance = close - stop_loss if close is not None and stop_loss is not None else None

    return {
        "dema60_breakout": all(value is not None for value in (close, prev_close, dema, dema_prev))
        and close > dema
        and prev_close <= dema_prev,
        "dema60_slope_up": dema is not None and dema_prev is not None and dema > dema_prev,
        "stoch_d_cross_50_up": stoch_d is not None and stoch_d_prev is not None and stoch_d > 50 and stoch_d_prev <= 50,
        "vol_surge": volume_ratio is not None and vol_surge_mult is not None and volume_ratio >= vol_surge_mult,
        "index_above": False,
        "candle_overheat": (
            (distance_from_ma20 is not None and overheat_gap_pct is not None and distance_from_ma20 >= overheat_gap_pct)
            or (last_day_return is not None and candle_return_pct is not None and last_day_return >= candle_return_pct)
        ),
        "atr_stop_excess": (
            stop_distance is not None
            and atr14 is not None
            and atr14 > 0
            and atr_stop_excess_mult is not None
            and stop_distance / atr14 >= atr_stop_excess_mult
        ),
    }
