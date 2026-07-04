"""Portfolio concentration limits and ATR-based position sizing."""

from __future__ import annotations

import math
import pandas as pd


def calculate_position_size(entry_price: float, atr: float, config: dict) -> dict:
    cfg = config.get("portfolio", {})
    equity = float(cfg.get("account_equity", 100_000))
    risk_pct = float(cfg.get("risk_per_trade_pct", 1.0)) / 100
    stop_mult = float(config.get("risk", {}).get("atr_stop_multiplier", 1.5))
    risk_per_share = max(float(atr) * stop_mult, 0.0)
    shares = math.floor(equity * risk_pct / risk_per_share) if risk_per_share > 0 else 0
    return {
        "position_size": max(0, shares),
        "position_value": round(max(0, shares) * float(entry_price), 2),
        "risk_amount": round(max(0, shares) * risk_per_share, 2),
    }


def apply_portfolio_constraints(
    candidates: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    config: dict,
    top_n: int,
) -> pd.DataFrame:
    if candidates.empty:
        return candidates.copy()
    cfg = config.get("portfolio", {})
    sector_cap = int(cfg.get("max_per_sector", 2))
    corr_cap = float(cfg.get("max_correlation", 0.8))
    cap_unknown_sector = bool(cfg.get("cap_unknown_sector", False))
    selected_rows = []
    sector_counts: dict[str, int] = {}
    selected_tickers: list[str] = []
    skipped: list[tuple[pd.Series, str]] = []
    for _, row in candidates.iterrows():
        sector = str(row.get("sector") or "Unknown")
        if (sector != "Unknown" or cap_unknown_sector) and sector_counts.get(sector, 0) >= sector_cap:
            skipped.append((row, f"섹터({sector}) 집중 한도 초과"))
            continue
        ticker = str(row.get("ticker"))
        frame = histories.get(ticker)
        correlated = False
        if frame is not None and not frame.empty:
            returns = pd.to_numeric(frame["Close"], errors="coerce").pct_change().tail(60)
            for chosen in selected_tickers:
                other = histories.get(chosen)
                if other is None or other.empty:
                    continue
                other_returns = pd.to_numeric(other["Close"], errors="coerce").pct_change().tail(60)
                if returns.corr(other_returns) > corr_cap:
                    correlated = True
                    break
        if correlated:
            skipped.append((row, "기존 후보와 상관관계 높음"))
            continue
        enriched = row.copy()
        sizing = calculate_position_size(row.get("current_price", 0), row.get("atr14", 0), config)
        for key, value in sizing.items():
            enriched[key] = value
        selected_rows.append(enriched)
        selected_tickers.append(ticker)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected_rows) >= top_n:
            break
    # 분산 제약으로 top_n을 못 채우면 제외된 후보를 사유 표기 후 보충한다.
    for row, reason in skipped:
        if len(selected_rows) >= top_n:
            break
        enriched = row.copy()
        sizing = calculate_position_size(row.get("current_price", 0), row.get("atr14", 0), config)
        for key, value in sizing.items():
            enriched[key] = value
        note = str(row.get("selection_note") or "")
        enriched["selection_note"] = f"{note}; 분산 기준 예외 포함: {reason}" if note else f"분산 기준 예외 포함: {reason}"
        selected_rows.append(enriched)
    return pd.DataFrame(selected_rows).reset_index(drop=True)
