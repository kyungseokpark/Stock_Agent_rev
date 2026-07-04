"""Single signal-generation entry point for live screening and backtests."""

from __future__ import annotations

import pandas as pd

from .analysis_enrichment import risk_reward_status
from .calibration import expected_r_for_score
from .chart_classifier import classify_chart_type
from .data_quality import normalize_ohlcv
from .event_filter import earnings_context
from .indicators import build_indicator_snapshot
from .mtf import weekly_trend_context
from .regime import regime_from_market_summary
from .scoring import calculate_score
from .target_price import calculate_targets
from .vcp import score_vcp


def generate_signal(
    df: pd.DataFrame,
    config: dict,
    as_of_index: int | None = None,
    *,
    context: dict | None = None,
) -> dict:
    """Generate one signal using only data available through ``as_of_index``."""

    if as_of_index is None:
        visible = df.copy()
    else:
        if as_of_index < 0:
            raise ValueError("as_of_index must be non-negative")
        visible = df.iloc[: as_of_index + 1].copy()
    clean, quality = normalize_ohlcv(visible, apply_adjustment=bool(config.get("data", {}).get("auto_adjust", True)))
    min_rows = int(config.get("data", {}).get("min_rows", 120))
    if len(clean) < min_rows:
        return {"valid_signal": False, "exclude_reason": "insufficient_rows", **quality}

    context = context or {}
    snapshot = build_indicator_snapshot(clean)
    vcp = score_vcp(clean, snapshot, config)
    mtf = weekly_trend_context(clean, config)
    regime = context.get("regime") or regime_from_market_summary(context.get("market_summary"))
    rs_rank = float(context.get("rs_rank", 0.0))
    targets = calculate_targets(snapshot, config)
    score_context = {**vcp, **mtf, **regime, "rs_rank": rs_rank}
    try:
        score = calculate_score(snapshot, targets, context=score_context, config=config)
    except TypeError as exc:
        # Streamlit can retain a previously imported two-argument scorer while
        # hot-reloading this module. Keep an existing session usable until the
        # process has fully reloaded, but never mask unrelated TypeErrors.
        if "unexpected keyword argument" not in str(exc):
            raise
        score = calculate_score(snapshot, targets)
    chart_type = classify_chart_type(snapshot, vcp)
    event = earnings_context(
        clean.index[-1],
        context.get("earnings_dates"),
        window_days=int(config.get("event_filter", {}).get("window_days", 5)),
    )
    expected_r = expected_r_for_score(score["final_score"], context.get("calibration"))

    enabled_regime = bool(config.get("regime", {}).get("enabled", True))
    enabled_mtf = bool(config.get("mtf", {}).get("enabled", True))
    enabled_events = bool(config.get("event_filter", {}).get("enabled", True))
    valid = bool(targets.get("valid", False))
    if enabled_regime and regime["regime_state"] == "risk_off":
        valid = False
    if enabled_mtf and not mtf["weekly_trend_ok"]:
        valid = False
    if enabled_events and event["earnings_in_window"]:
        valid = False

    result = {key: value for key, value in snapshot.items() if key != "history"}
    result.update(targets)
    result.update(vcp)
    result.update(mtf)
    result.update(regime)
    result.update(score)
    result.update(event)
    result.update(quality)
    result.update(risk_reward_status(targets.get("risk_reward", 0)))
    result.update(
        {
            "chart_type": chart_type,
            "rs_rank": round(rs_rank, 2),
            "expected_r": expected_r,
            "valid_signal": valid,
            "signal_date": clean.index[-1],
            "is_sample_data": bool(context.get("is_sample_data", False)),
        }
    )
    return result
