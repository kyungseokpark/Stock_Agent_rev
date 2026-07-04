"""Map signal scores to empirically observed expectancy and win rate."""

from __future__ import annotations

from pathlib import Path
import pandas as pd


SCORE_BINS = [0, 50, 60, 70, 80, 90, 101]


def build_calibration(trades: pd.DataFrame, score_column: str = "final_score") -> pd.DataFrame:
    if trades.empty or score_column not in trades or "r_multiple" not in trades:
        return pd.DataFrame(columns=["score_bucket", "trade_count", "expected_r", "win_rate"])
    work = trades.copy()
    work["score_bucket"] = pd.cut(pd.to_numeric(work[score_column], errors="coerce"), SCORE_BINS, right=False)
    result = work.groupby("score_bucket", observed=True)["r_multiple"].agg(["count", "mean", lambda s: (s > 0).mean() * 100]).reset_index()
    result.columns = ["score_bucket", "trade_count", "expected_r", "win_rate"]
    result["score_bucket"] = result["score_bucket"].astype(str)
    return result.round({"expected_r": 3, "win_rate": 2})


def save_calibration(table: pd.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False, encoding="utf-8-sig")


def expected_r_for_score(score: float, table: pd.DataFrame | None) -> float | None:
    if table is None or table.empty:
        return None
    bucket = pd.cut(pd.Series([float(score)]), SCORE_BINS, right=False).astype(str).iloc[0]
    match = table[table["score_bucket"].astype(str) == bucket]
    return None if match.empty else float(match.iloc[0]["expected_r"])
