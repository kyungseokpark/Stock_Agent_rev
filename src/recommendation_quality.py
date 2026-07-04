"""Recommendation quality flags and adjusted ranking helpers."""

from __future__ import annotations

import logging

import pandas as pd


LOGGER = logging.getLogger(__name__)


CHART_TYPE_KEYS = {
    "Box breakout": "breakout",
    "Breakout": "breakout",
    "Pullback rebound": "pullback",
    "20MA rebound": "ma20_reclaim",
    "MA20 recovery": "ma20_reclaim",
    "Near new high": "near_high",
    "Near high": "near_high",
    "Relative strength leader": "near_high",
    "Relative strength": "near_high",
    "Oversold rebound": "oversold_bounce",
    "Falling knife": "falling_knife",
    "Watchlist pattern": "unknown",
    "Excluded pattern": "unknown",
    "VCP breakout": "breakout",
    "VCP base": "near_high",
}


def chart_type_key(chart_type: str) -> str:
    return CHART_TYPE_KEYS.get(str(chart_type), "unknown")


def _to_float(value, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def build_quality_metrics(
    *,
    final_score: float,
    chart_type: str,
    targets: dict,
    filter_info: dict,
    is_sample_data: bool,
    data_source: str,
    data_quality: str,
    data_warning: str,
    config: dict,
) -> dict:
    adjustment_cfg = config.get("scoring_adjustment", {})
    risk_cfg = config.get("risk", {})
    chart_bonus = adjustment_cfg.get("chart_type_bonus", {})
    min_risk_reward = _to_float(risk_cfg.get("min_risk_reward", 1.2), 1.2)

    key = chart_type_key(chart_type)
    chart_type_penalty = _to_float(chart_bonus.get(key, chart_bonus.get("unknown", -2)), -2)

    quality_penalty = 0.0
    if is_sample_data:
        quality_penalty -= 100.0 if adjustment_cfg.get("exclude_sample_data", True) else 20.0
    if data_quality in {"failed", "insufficient_rows"}:
        quality_penalty -= 100.0

    risk_reward = _to_float(targets.get("risk_reward"), 0.0)
    passed_risk_reward = risk_reward >= min_risk_reward
    risk_reward_warning = "" if passed_risk_reward else f"손익비 기준 미달: {risk_reward:.2f} < {min_risk_reward:.2f}"

    passed_liquidity = bool(filter_info.get("passed", False))
    filter_reason = str(filter_info.get("reason", "") or "")
    liquidity_warning = "" if passed_liquidity else f"유동성 필터 미달: {filter_reason or '기준 미달'}"

    adjusted_score = _to_float(final_score) + chart_type_penalty + quality_penalty
    adjusted_score = max(0.0, min(100.0, adjusted_score))

    return {
        "score": _to_float(final_score),
        "adjusted_score": round(adjusted_score, 2),
        "chart_type_penalty": round(chart_type_penalty, 2),
        "quality_penalty": round(quality_penalty, 2),
        "is_sample_data": bool(is_sample_data),
        "data_source": data_source,
        "data_quality": data_quality,
        "data_warning": data_warning,
        "passed_liquidity_filter": passed_liquidity,
        "liquidity_warning": liquidity_warning,
        "filter_reason": filter_reason,
        "avg_dollar_volume_20d": _to_float(filter_info.get("avg_dollar_volume_20d")),
        "passed_risk_reward_filter": passed_risk_reward,
        "risk_reward_warning": risk_reward_warning,
    }


def _backfill_note(row: pd.Series, sort_score_col: str, min_score: float) -> str:
    reasons = []
    score = _to_float(row.get(sort_score_col))
    if min_score > 0 and score < min_score:
        reasons.append(f"점수 {score:.0f}점 < 기준 {min_score:.0f}점")
    risk_reward = _to_float(row.get("risk_reward"))
    if risk_reward < 1.0:
        reasons.append(f"손익비 {risk_reward:.2f} < 1.0")
    elif row.get("passed_risk_reward_filter") is False and str(row.get("risk_reward_warning") or ""):
        reasons.append(str(row.get("risk_reward_warning")))
    detail = ", ".join(reasons) if reasons else "선정 기준 미달"
    return f"기준 미달 보충 후보 ({detail})"


def select_top_candidates(full_df: pd.DataFrame, config: dict, top_n: int) -> pd.DataFrame:
    """Select top candidates, backfilling below-threshold rows so top_n is always met.

    Sample-data rows stay excluded. Rows that fail the score/risk-reward gates can
    still be selected as marked "보충 후보" (with the failed criteria recorded in
    ``selection_note``) so the final list is not silently shortened.
    """
    if full_df.empty:
        return full_df.copy()

    adjustment_cfg = config.get("scoring_adjustment", {})
    use_adjusted_score = bool(adjustment_cfg.get("use_adjusted_score", True))
    composite_cfg = config.get("composite", {})
    if bool(composite_cfg.get("enabled", False)) and "composite_score" in full_df.columns:
        sort_score_col = "composite_score"
    else:
        sort_score_col = "adjusted_score" if use_adjusted_score and "adjusted_score" in full_df.columns else "final_score"

    base_pool = full_df.copy()
    if bool(adjustment_cfg.get("exclude_sample_data", True)) and "is_sample_data" in base_pool.columns:
        base_pool = base_pool[~base_pool["is_sample_data"].fillna(False).astype(bool)]

    candidate_df = base_pool.copy()
    if bool(adjustment_cfg.get("exclude_low_risk_reward", False)) and "passed_risk_reward_filter" in candidate_df.columns:
        candidate_df = candidate_df[candidate_df["passed_risk_reward_filter"].fillna(False).astype(bool)]
    if "risk_reward" in candidate_df.columns:
        eligible = candidate_df[pd.to_numeric(candidate_df["risk_reward"], errors="coerce").fillna(0) >= 1.0]
        if len(eligible) >= top_n:
            candidate_df = eligible

    min_score = _to_float(config.get("screening", {}).get("min_score_for_candidate"), 0.0)
    if min_score > 0 and sort_score_col in candidate_df.columns:
        score_values = pd.to_numeric(candidate_df[sort_score_col], errors="coerce").fillna(0)
        candidate_df = candidate_df[score_values >= min_score]
        if len(candidate_df) < top_n:
            LOGGER.warning(
                "Candidate count below top_n after min score gate: %s/%s at %s >= %.2f",
                len(candidate_df),
                top_n,
                sort_score_col,
                min_score,
            )

    sort_cols = [sort_score_col]
    ascending = [False]
    if "risk_reward" in base_pool.columns:
        sort_cols.append("risk_reward")
        ascending.append(False)
    if sort_score_col != "final_score" and "final_score" in base_pool.columns:
        sort_cols.append("final_score")
        ascending.append(False)

    primary = candidate_df.sort_values(sort_cols, ascending=ascending).head(top_n).copy()
    primary["selection_note"] = ""

    if len(primary) < top_n:
        remaining = base_pool.drop(index=primary.index, errors="ignore")
        if not remaining.empty:
            backfill = remaining.sort_values(sort_cols, ascending=ascending).head(top_n - len(primary)).copy()
            backfill["selection_note"] = backfill.apply(
                lambda row: _backfill_note(row, sort_score_col, min_score), axis=1
            )
            LOGGER.info("Backfilled %s below-threshold candidates to reach top_n=%s", len(backfill), top_n)
            primary = pd.concat([primary, backfill])

    return primary


def select_force_leaders(full_df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    """세력 유입 점수(force_inflow_pct) 기준 상위 종목 선정 (세력주 Top N)."""
    if full_df.empty or "force_inflow_pct" not in full_df.columns:
        return full_df.head(0).copy()
    pool = full_df.copy()
    if "is_sample_data" in pool.columns:
        pool = pool[~pool["is_sample_data"].fillna(False).astype(bool)]
    force_values = pd.to_numeric(pool["force_inflow_pct"], errors="coerce")
    pool = pool[force_values.notna()]
    if pool.empty:
        return pool
    sort_cols = ["force_inflow_pct"]
    ascending = [False]
    for col in ("composite_score", "final_score"):
        if col in pool.columns:
            sort_cols.append(col)
            ascending.append(False)
    return pool.sort_values(sort_cols, ascending=ascending).head(top_n).copy()


def ranking_score_column(frame: pd.DataFrame, config: dict) -> str:
    adjustment_cfg = config.get("scoring_adjustment", {})
    if bool(config.get("composite", {}).get("enabled", False)) and "composite_score" in frame.columns:
        return "composite_score"
    if bool(adjustment_cfg.get("use_adjusted_score", True)) and "adjusted_score" in frame.columns:
        return "adjusted_score"
    return "final_score"


def apply_soft_candidate_filters(
    full_df: pd.DataFrame,
    config: dict,
    *,
    top_n: int,
    stats: dict | None = None,
    sort_score_col: str | None = None,
) -> pd.DataFrame:
    """Apply the live screener's soft RS/VCP filters before final ranking.

    RS and VCP are priority filters only when enough minimum-score candidates
    remain. This keeps backtests aligned with the production screener instead
    of treating those fields as hard gates.
    """
    if full_df.empty:
        return full_df.copy()
    stats = stats if stats is not None else {}
    candidate_pool = full_df.copy()
    sort_score_col = sort_score_col or ranking_score_column(candidate_pool, config)
    min_rs = _to_float(config.get("ranking", {}).get("min_rs_rank", 0), 0.0)
    min_vcp = _to_float(config.get("vcp", {}).get("min_score", 0), 0.0)
    min_candidate_score = _to_float(config.get("screening", {}).get("min_score_for_candidate", 0), 0.0)

    def has_min_score(frame: pd.DataFrame) -> bool:
        if frame.empty or sort_score_col not in frame.columns:
            return False
        values = pd.to_numeric(frame[sort_score_col], errors="coerce").fillna(0)
        return bool((values >= min_candidate_score).any())

    if min_rs and "rs_rank" in candidate_pool:
        rs_values = pd.to_numeric(candidate_pool["rs_rank"], errors="coerce").fillna(0)
        if (rs_values >= min_rs).any():
            rs_pool = candidate_pool[rs_values >= min_rs]
            if has_min_score(rs_pool):
                candidate_pool = rs_pool
            else:
                stats["rs_filter_note"] = "상대강도 필터를 적용하면 최소 점수 통과 후보가 없어 적용하지 않음"
        stats["candidate_after_rs_filter"] = len(candidate_pool)
    else:
        stats["candidate_after_rs_filter"] = len(candidate_pool)

    if min_vcp and "vcp_score" in candidate_pool:
        vcp_values = pd.to_numeric(candidate_pool["vcp_score"], errors="coerce").fillna(0)
        if (vcp_values >= min_vcp).any():
            vcp_pool = candidate_pool[vcp_values >= min_vcp]
            if has_min_score(vcp_pool):
                candidate_pool = vcp_pool
            else:
                stats["vcp_filter_note"] = "수축패턴 필터를 적용하면 최소 점수 통과 후보가 없어 우선순위 조건으로만 사용"
        stats["candidate_after_vcp_filter"] = len(candidate_pool)
    else:
        stats["candidate_after_vcp_filter"] = len(candidate_pool)

    stats["candidate_before_score_gate"] = len(candidate_pool)
    if sort_score_col in candidate_pool.columns:
        stats["candidate_after_score_gate"] = int(
            (pd.to_numeric(candidate_pool[sort_score_col], errors="coerce").fillna(0) >= min_candidate_score).sum()
        )
    else:
        stats["candidate_after_score_gate"] = len(candidate_pool)
    return candidate_pool
