"""Event-based backtests driven exclusively by the shared signal engine."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from .force_inflow import add_composite_score
from .portfolio import calculate_position_size
from .ranking import rank_relative_strength
from .recommendation_quality import apply_soft_candidate_filters, build_quality_metrics, ranking_score_column, select_top_candidates
from .regime import classify_regime
from .signal_engine import generate_signal


ProgressCallback = Callable[[float, str], None]


def _cost_rate(config: dict, market: str) -> float:
    cfg = config.get("backtest", {})
    commission = float(cfg.get("commission_pct", 0.03)) / 100
    slippage = float(cfg.get("slippage_pct", 0.05)) / 100
    tax = float(cfg.get("kr_sell_tax_pct", 0.18)) / 100 if market == "kr" else 0.0
    return commission * 2 + slippage * 2 + tax


def _trade_cost(entry: float, exit_price: float, shares: float, config: dict, market: str) -> float:
    cfg = config.get("backtest", {})
    commission = float(cfg.get("commission_pct", 0.03)) / 100
    slippage = float(cfg.get("slippage_pct", 0.05)) / 100
    tax = float(cfg.get("kr_sell_tax_pct", 0.18)) / 100 if market == "kr" else 0.0
    return entry * shares * (commission + slippage) + exit_price * shares * (commission + slippage + tax)


def _simulate_exit(
    df: pd.DataFrame,
    entry_idx: int,
    entry: float,
    risk: float,
    hold_days: int,
    target_r: float,
) -> dict:
    """Apply the shared stop/target/time-exit rules to one entered position."""
    stop = entry - risk
    target = entry + target_r * risk
    exit_idx = min(entry_idx + hold_days - 1, len(df) - 1)
    exit_price = float(df["Close"].iloc[exit_idx])
    reason = "time"
    ambiguous = False
    first_hit = "none"
    for index in range(entry_idx, exit_idx + 1):
        hit_stop = float(df["Low"].iloc[index]) <= stop
        hit_target = float(df["High"].iloc[index]) >= target
        if hit_stop and hit_target:
            exit_idx, exit_price, reason = index, stop, "stop"
            ambiguous = True
            first_hit = "ambiguous"
            break
        if hit_stop:
            exit_idx, exit_price, reason = index, stop, "stop"
            first_hit = "stop_first"
            break
        if hit_target:
            exit_idx, exit_price, reason = index, target, "target"
            first_hit = "target_first"
            break
    return {
        "exit_idx": exit_idx,
        "exit_price": exit_price,
        "exit_reason": reason,
        "ambiguous": ambiguous,
        "first_hit": first_hit,
        "stop_price": stop,
        "target_price": target,
    }


def _empty_summary() -> dict:
    return {
        "trade_count": 0,
        "win_rate": 0.0,
        "expected_r": 0.0,
        "profit_factor": 0.0,
        "mdd": 0.0,
        "sharpe": 0.0,
        "total_return_pct": 0.0,
        "benchmark_return_pct": 0.0,
        "oos_expected_r": 0.0,
        "ambiguous_count": 0,
        "ambiguous_rate": 0.0,
        "avg_positions": 0.0,
        "capital_exposure_pct": 0.0,
        "exposure_adjusted_return_pct": 0.0,
    }


def _summarize(trades_df: pd.DataFrame, equity_df: pd.DataFrame, base_equity: float) -> dict:
    if trades_df.empty:
        return _empty_summary()
    wins = trades_df.loc[trades_df["r_multiple"] > 0, "r_multiple"]
    losses = trades_df.loc[trades_df["r_multiple"] < 0, "r_multiple"]
    pf = float(wins.sum() / abs(losses.sum())) if not losses.empty and losses.sum() else float("inf")
    curve = pd.to_numeric(equity_df.get("equity"), errors="coerce").dropna()
    mdd = float(((curve / curve.cummax()) - 1).min() * 100) if not curve.empty else 0.0
    std = float(trades_df["r_multiple"].std(ddof=0))
    sample_std = float(trades_df["r_multiple"].std(ddof=1)) if len(trades_df) > 1 else 0.0
    expected_r = float(trades_df["r_multiple"].mean())
    ci_half_width = 1.96 * sample_std / np.sqrt(len(trades_df)) if len(trades_df) > 1 else 0.0
    sharpe = float(trades_df["r_multiple"].mean() / std * np.sqrt(len(trades_df))) if std > 0 else 0.0
    total_return = float((curve.iloc[-1] / base_equity - 1) * 100) if not curve.empty else 0.0
    benchmark_source = equity_df["benchmark_equity"] if "benchmark_equity" in equity_df else pd.Series(dtype=float)
    benchmark = pd.to_numeric(benchmark_source, errors="coerce").dropna()
    benchmark_return = float((benchmark.iloc[-1] / base_equity - 1) * 100) if not benchmark.empty else 0.0
    benchmark_mdd = float(((benchmark / benchmark.cummax()) - 1).min() * 100) if not benchmark.empty else 0.0
    oos = trades_df.loc[trades_df["sample"] == "OOS", "r_multiple"]
    avg_positions = float(pd.to_numeric(equity_df.get("open_positions"), errors="coerce").fillna(0).mean()) if "open_positions" in equity_df else 0.0
    exposure = float(pd.to_numeric(equity_df.get("capital_exposure_pct"), errors="coerce").fillna(0).mean()) if "capital_exposure_pct" in equity_df else 0.0
    ambiguous_count = int(trades_df.get("ambiguous", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
    return {
        "trade_count": len(trades_df),
        "win_rate": round(float((trades_df["r_multiple"] > 0).mean() * 100), 2),
        "expected_r": round(expected_r, 4),
        "expected_r_ci95_low": round(expected_r - ci_half_width, 4),
        "expected_r_ci95_high": round(expected_r + ci_half_width, 4),
        "profit_factor": round(pf, 3),
        "mdd": round(mdd, 2),
        "sharpe": round(sharpe, 3),
        "total_return_pct": round(total_return, 2),
        "benchmark_return_pct": round(benchmark_return, 2),
        "benchmark_mdd": round(benchmark_mdd, 2),
        "is_trade_count": int((trades_df["sample"] == "IS").sum()),
        "oos_trade_count": int((trades_df["sample"] == "OOS").sum()),
        "oos_expected_r": round(float(oos.mean()), 4) if not oos.empty else 0.0,
        "ambiguous_count": ambiguous_count,
        "ambiguous_rate": round(float(ambiguous_count / len(trades_df) * 100), 2),
        "avg_positions": round(avg_positions, 2),
        "capital_exposure_pct": round(exposure, 2),
        "exposure_adjusted_return_pct": round(total_return / (exposure / 100), 2) if exposure > 0 else 0.0,
    }


def _align_benchmark(equity_df: pd.DataFrame, base_equity: float) -> pd.DataFrame:
    if equity_df.empty or "benchmark_equity" not in equity_df or not equity_df["benchmark_equity"].notna().any():
        return equity_df
    first = float(equity_df["benchmark_equity"].dropna().iloc[0])
    if first:
        equity_df = equity_df.copy()
        equity_df["benchmark_equity"] = equity_df["benchmark_equity"] * (base_equity / first)
    return equity_df


def run_backtest(
    df: pd.DataFrame,
    config: dict,
    *,
    market: str = "us",
    context: dict | None = None,
) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    cfg = config.get("backtest", {})
    hold_days = int(cfg.get("max_holding_days", 5))
    target_r = float(cfg.get("target_r", 2.0))
    min_score = float(cfg.get("min_final_score", 50))
    min_vcp = float(cfg.get("min_vcp_score", config.get("vcp", {}).get("min_score", 70)))
    start = max(int(config.get("data", {}).get("min_rows", 120)), 60)
    trades = []
    base_equity = float(config.get("portfolio", {}).get("account_equity", 100_000))
    equity = base_equity
    equity_rows = []

    i = start
    while i < len(df) - 1:
        signal_context = dict(context or {})
        benchmark = signal_context.pop("benchmark_df", None)
        if benchmark is not None and not benchmark.empty:
            signal_context["regime"] = classify_regime(benchmark.loc[: df.index[i - 1]])
        signal = generate_signal(df, config, as_of_index=i - 1, context=signal_context)
        if not signal.get("valid_signal") or signal.get("final_score", 0) < min_score or signal.get("vcp_score", 0) < min_vcp:
            i += 1
            continue
        entry_idx = i
        entry = float(df["Open"].iloc[entry_idx])
        atr = float(signal.get("atr14", 0))
        risk = atr * float(config.get("risk", {}).get("atr_stop_multiplier", 1.5))
        if entry <= 0 or risk <= 0:
            i += 1
            continue
        outcome = _simulate_exit(df, entry_idx, entry, risk, hold_days, target_r)
        exit_idx = int(outcome["exit_idx"])
        exit_price = float(outcome["exit_price"])
        sizing = calculate_position_size(entry, atr, config)
        cost = _trade_cost(entry, exit_price, sizing["position_size"], config, market)
        net_r = (exit_price - entry) / risk - cost / max(sizing["position_size"], 1e-12) / risk
        pnl = (exit_price - entry) * sizing["position_size"] - cost
        equity += pnl
        trades.append(
            {
                "signal_date": df.index[i - 1], "entry_date": df.index[entry_idx], "exit_date": df.index[exit_idx],
                "entry_price": entry, "exit_price": exit_price, "stop_price": outcome["stop_price"],
                "target_price": outcome["target_price"], "exit_reason": outcome["exit_reason"],
                "ambiguous": outcome["ambiguous"], "first_hit": outcome["first_hit"],
                "r_multiple": round(net_r, 4), "final_score": signal.get("final_score", 0),
                "vcp_score": signal.get("vcp_score", 0), "regime_state": signal.get("regime_state"),
                "position_size": sizing["position_size"], "pnl": round(pnl, 2),
                "sample": "IS" if entry_idx < int(len(df) * 0.7) else "OOS",
            }
        )
        benchmark_equity = None
        if benchmark is not None and not benchmark.empty:
            bench_close = pd.to_numeric(benchmark.loc[: df.index[exit_idx], "Close"], errors="coerce").dropna()
            bench_start = pd.to_numeric(benchmark.loc[df.index[start] :, "Close"], errors="coerce").dropna()
            if not bench_close.empty and not bench_start.empty:
                benchmark_equity = base_equity * float(bench_close.iloc[-1] / bench_start.iloc[0])
        equity_rows.append({"date": df.index[exit_idx], "equity": round(equity, 2), "benchmark_equity": benchmark_equity, "open_positions": 0, "capital_exposure_pct": 0.0})
        i = exit_idx + 1

    trades_df = pd.DataFrame(trades)
    equity_df = _align_benchmark(pd.DataFrame(equity_rows), base_equity)
    return trades_df, _summarize(trades_df, equity_df, base_equity), equity_df


def _notify(progress_cb: ProgressCallback | None, fraction: float, message: str) -> None:
    if progress_cb is not None:
        progress_cb(max(0.0, min(1.0, fraction)), message)


def _load_histories(
    universe: Sequence[str], lookback_period: str, config: dict, progress_cb: ProgressCallback | None
) -> dict[str, pd.DataFrame]:
    # Local import keeps network I/O replaceable in tests and avoids a module cycle.
    from .data_loader import fetch_ohlcv

    histories: dict[str, pd.DataFrame] = {}
    timeout = int(config.get("data", {}).get("request_timeout_seconds", 600))
    total = max(len(universe), 1)
    for number, ticker in enumerate(universe, 1):
        frame = fetch_ohlcv(str(ticker), period=lookback_period, interval="1d", timeout=timeout)
        if frame is not None and not frame.empty:
            histories[str(ticker)] = frame.sort_index()
        _notify(progress_cb, number / total * 0.25, f"시세 불러오는 중 ({number}/{total})")
    return histories


def _limit_histories(histories: dict[str, pd.DataFrame], max_universe: int) -> dict[str, pd.DataFrame]:
    if max_universe <= 0 or len(histories) <= max_universe:
        return histories
    liquidity = {}
    for ticker, frame in histories.items():
        close = pd.to_numeric(frame.get("Close"), errors="coerce")
        volume = pd.to_numeric(frame.get("Volume"), errors="coerce")
        liquidity[ticker] = float((close * volume).tail(20).mean())
    selected = sorted(histories, key=lambda ticker: liquidity.get(ticker, 0), reverse=True)[:max_universe]
    return {ticker: histories[ticker] for ticker in selected}


def _backtest_candidate_row(ticker: str, entry_idx: int, signal: dict, config: dict) -> dict:
    targets = {
        "risk_reward": signal.get("risk_reward", 0),
        "valid": signal.get("valid", signal.get("valid_signal", False)),
    }
    quality = build_quality_metrics(
        final_score=float(signal.get("final_score", 0)),
        chart_type=str(signal.get("chart_type", "")),
        targets=targets,
        filter_info={"passed": True, "avg_dollar_volume_20d": 0},
        is_sample_data=bool(signal.get("is_sample_data", False)),
        data_source=str(signal.get("data_source", "backtest")),
        data_quality=str(signal.get("data_quality_flag", "normal")),
        data_warning=str(signal.get("data_quality_reasons", "")),
        config=config,
    )
    row = {
        **signal,
        **quality,
        "ticker": ticker,
        "entry_idx": entry_idx,
    }
    row.update(add_composite_score(row, config))
    return row


def run_picks_backtest(
    universe: Sequence[str],
    config: dict,
    *,
    market: str = "us",
    top_n_per_day: int = 3,
    lookback_period: str = "2y",
    progress_cb: ProgressCallback | None = None,
    data_by_ticker: Mapping[str, pd.DataFrame] | None = None,
    benchmark_df: pd.DataFrame | None = None,
    sector_by_ticker: Mapping[str, str] | None = None,
) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Replay daily ranked picks, using D-1 data and entering at D open.

    ``data_by_ticker`` is an optional preloaded/cacheable input for Streamlit and
    deterministic tests. Without it, every ticker is downloaded exactly once.
    """
    if top_n_per_day < 1:
        raise ValueError("top_n_per_day must be at least 1")
    tickers = list(dict.fromkeys(str(ticker) for ticker in universe if str(ticker).strip()))
    max_universe = int(config.get("backtest", {}).get("max_universe", 100))
    if data_by_ticker is None:
        histories = _load_histories(tickers, lookback_period, config, progress_cb)
    else:
        histories = {
            ticker: data_by_ticker[ticker].sort_index().copy()
            for ticker in tickers
            if ticker in data_by_ticker and data_by_ticker[ticker] is not None and not data_by_ticker[ticker].empty
        }
        _notify(progress_cb, 0.25, f"캐시 시세 {len(histories)}개 준비 완료")
    histories = _limit_histories(histories, max_universe)
    sector_by_ticker = {str(k): str(v or "") for k, v in (sector_by_ticker or {}).items()}
    min_rows = max(int(config.get("data", {}).get("min_rows", 120)), 60)
    histories = {ticker: frame for ticker, frame in histories.items() if len(frame) > min_rows}
    if not histories:
        return pd.DataFrame(), _empty_summary(), pd.DataFrame()

    cfg = config.get("backtest", {})
    min_score = float(cfg.get("min_final_score", 50))
    allowed_regimes = {str(value) for value in cfg.get("allowed_regimes", []) if str(value).strip()}
    hold_days = int(cfg.get("max_holding_days", 5))
    target_r = float(cfg.get("target_r", 2.0))
    stop_mult = float(config.get("risk", {}).get("atr_stop_multiplier", 1.5))
    portfolio_cfg = config.get("portfolio", {})
    sector_cap = int(portfolio_cfg.get("max_per_sector", 0) or 0)
    cap_unknown_sector = bool(portfolio_cfg.get("cap_unknown_sector", False))
    base_equity = float(config.get("portfolio", {}).get("account_equity", 100_000))
    all_dates = sorted(set().union(*(set(frame.index[min_rows:]) for frame in histories.values())))
    if not all_dates:
        return pd.DataFrame(), _empty_summary(), pd.DataFrame()

    positions: dict[str, dict] = {}
    cash = base_equity
    trades: list[dict] = []
    equity_rows: list[dict] = []
    first_trade_date = None
    benchmark_base = None
    baseline_recorded = False

    for day_number, day in enumerate(all_dates):
        # Signals and ranks use slices ending strictly before today's entry bar.
        visible = {ticker: frame.loc[frame.index < day] for ticker, frame in histories.items()}
        visible = {ticker: frame for ticker, frame in visible.items() if len(frame) >= min_rows}
        benchmark_visible = benchmark_df.loc[benchmark_df.index < day] if benchmark_df is not None and not benchmark_df.empty else None
        rs_ranks = rank_relative_strength(visible, benchmark_visible)
        regime = classify_regime(benchmark_visible) if benchmark_visible is not None and not benchmark_visible.empty else None
        candidates = []
        for ticker, frame in histories.items():
            if ticker in positions or day not in frame.index or ticker not in visible:
                continue
            entry_idx = int(frame.index.get_loc(day))
            context = {"rs_rank": rs_ranks.get(ticker, 0.0)}
            if regime is not None:
                context["regime"] = regime
            signal = generate_signal(frame, config, as_of_index=entry_idx - 1, context=context)
            if (
                signal.get("valid_signal")
                and float(signal.get("final_score", 0)) >= min_score
                and (not allowed_regimes or str(signal.get("regime_state")) in allowed_regimes)
            ):
                row = _backtest_candidate_row(ticker, entry_idx, signal, config)
                row["sector"] = sector_by_ticker.get(ticker, "")
                candidates.append(row)
        if candidates:
            candidate_df = pd.DataFrame(candidates)
            sort_col = ranking_score_column(candidate_df, config)
            candidate_df = apply_soft_candidate_filters(candidate_df, config, top_n=top_n_per_day, sort_score_col=sort_col)
            candidate_df = select_top_candidates(candidate_df, config, len(candidate_df))
            candidates = [
                (str(row["ticker"]), int(row["entry_idx"]), row.to_dict())
                for _, row in candidate_df.iterrows()
            ]

        slots = max(0, top_n_per_day - len(positions))
        account_equity = cash
        for ticker, position in positions.items():
            frame = histories[ticker]
            if day in frame.index:
                mark_price = float(frame.loc[day, "Open"])
            else:
                prior_close = pd.to_numeric(frame.loc[frame.index < day, "Close"], errors="coerce").dropna()
                mark_price = float(prior_close.iloc[-1]) if not prior_close.empty else float(position["entry"])
            account_equity += mark_price * float(position["shares"])
        slot_allocation = account_equity / top_n_per_day
        sector_counts: dict[str, int] = {}
        if sector_cap > 0:
            for position in positions.values():
                sector = str(position.get("sector") or "Unknown")
                if sector != "Unknown" or cap_unknown_sector:
                    sector_counts[sector] = sector_counts.get(sector, 0) + 1
        opened = 0
        for ticker, entry_idx, signal in candidates:
            if opened >= slots:
                break
            sector = str(signal.get("sector") or "Unknown")
            if sector_cap > 0 and (sector != "Unknown" or cap_unknown_sector) and sector_counts.get(sector, 0) >= sector_cap:
                continue
            frame = histories[ticker]
            entry = float(frame["Open"].iloc[entry_idx])
            risk = float(signal.get("atr14", 0)) * stop_mult
            if entry <= 0 or risk <= 0 or cash <= 0:
                continue
            allocation = min(cash, slot_allocation)
            shares = allocation / entry
            if shares <= 0:
                continue
            outcome = _simulate_exit(frame, entry_idx, entry, risk, hold_days, target_r)
            cash -= entry * shares
            positions[ticker] = {
                "ticker": ticker, "entry_idx": entry_idx, "entry": entry, "risk": risk, "shares": shares,
                "signal": signal, "outcome": outcome, "entry_value": entry * shares,
                "sector": sector,
                "sample": "IS" if day_number < int(len(all_dates) * 0.7) else "OOS",
            }
            if sector_cap > 0 and (sector != "Unknown" or cap_unknown_sector):
                sector_counts[sector] = sector_counts.get(sector, 0) + 1
            opened += 1
            first_trade_date = first_trade_date or day

        if first_trade_date is not None and not baseline_recorded:
            equity_rows.append(
                {
                    "date": first_trade_date,
                    "equity": base_equity,
                    "benchmark_equity": base_equity if benchmark_df is not None and not benchmark_df.empty else None,
                }
            )
            baseline_recorded = True

        # Intraday exits happen after the open, so their slots become available tomorrow.
        for ticker, position in list(positions.items()):
            frame = histories[ticker]
            exit_idx = int(position["outcome"]["exit_idx"])
            if frame.index[exit_idx] != day:
                continue
            exit_price = float(position["outcome"]["exit_price"])
            shares = float(position["shares"])
            entry = float(position["entry"])
            cost = _trade_cost(entry, exit_price, shares, config, market)
            cash += exit_price * shares - cost
            pnl = (exit_price - entry) * shares - cost
            signal = position["signal"]
            trades.append({
                "ticker": ticker, "signal_date": frame.index[position["entry_idx"] - 1],
                "entry_date": frame.index[position["entry_idx"]], "exit_date": day,
                "entry_price": entry, "exit_price": exit_price,
                "stop_price": position["outcome"]["stop_price"], "target_price": position["outcome"]["target_price"],
                "exit_reason": position["outcome"]["exit_reason"],
                "ambiguous": position["outcome"]["ambiguous"], "first_hit": position["outcome"]["first_hit"],
                "r_multiple": round((exit_price - entry) / position["risk"] - cost / shares / position["risk"], 4),
                "final_score": signal.get("final_score", 0), "vcp_score": signal.get("vcp_score", 0),
                "adjusted_score": signal.get("adjusted_score", signal.get("final_score", 0)),
                "composite_score": signal.get("composite_score", signal.get("adjusted_score", signal.get("final_score", 0))),
                "chart_type": signal.get("chart_type"), "sector": signal.get("sector", ""),
                "rs_rank": signal.get("rs_rank", 0), "regime_state": signal.get("regime_state"),
                "position_size": shares, "pnl": round(pnl, 2), "sample": position["sample"],
            })
            del positions[ticker]

        marked_value = cash
        exposure_value = 0.0
        for ticker, position in positions.items():
            frame = histories[ticker]
            available_close = pd.to_numeric(frame.loc[frame.index <= day, "Close"], errors="coerce").dropna()
            position_value = float(available_close.iloc[-1]) * float(position["shares"]) if not available_close.empty else position["entry_value"]
            marked_value += position_value
            exposure_value += position_value
        benchmark_equity = None
        if first_trade_date is not None and benchmark_df is not None and not benchmark_df.empty:
            bench = pd.to_numeric(benchmark_df.loc[benchmark_df.index <= day, "Close"], errors="coerce").dropna()
            if benchmark_base is None:
                base_values = pd.to_numeric(benchmark_df.loc[benchmark_df.index >= first_trade_date, "Close"], errors="coerce").dropna()
                benchmark_base = float(base_values.iloc[0]) if not base_values.empty else None
            if not bench.empty and benchmark_base:
                benchmark_equity = base_equity * float(bench.iloc[-1] / benchmark_base)
        if first_trade_date is not None:
            equity_rows.append(
                {
                    "date": day,
                    "equity": round(marked_value, 2),
                    "benchmark_equity": benchmark_equity,
                    "open_positions": len(positions),
                    "capital_exposure_pct": round(exposure_value / marked_value * 100, 4) if marked_value else 0.0,
                }
            )
        _notify(progress_cb, 0.25 + 0.75 * (day_number + 1) / len(all_dates), f"과거 픽 재생 중 ({day_number + 1}/{len(all_dates)})")

    trades_df = pd.DataFrame(trades)
    equity_df = _align_benchmark(pd.DataFrame(equity_rows), base_equity)
    summary = _summarize(trades_df, equity_df, base_equity)
    summary.update(
        {
            "effective_replay_days": int(len(all_dates)),
            "data_start": min(frame.index.min() for frame in histories.values()).strftime("%Y-%m-%d"),
            "data_asof": max(frame.index.max() for frame in histories.values()).strftime("%Y-%m-%d"),
        }
    )
    return trades_df, summary, equity_df


def parameter_sensitivity(df: pd.DataFrame, config: dict, market: str = "us") -> pd.DataFrame:
    rows = []
    for threshold in [50, 60, 70, 80]:
        for target_r in [1.5, 2.0, 2.5]:
            local = {**config, "backtest": {**config.get("backtest", {}), "min_final_score": threshold, "target_r": target_r}}
            _, summary, _ = run_backtest(df, local, market=market)
            rows.append({"min_score": threshold, "target_r": target_r, "expected_r": summary["expected_r"], "trades": summary["trade_count"]})
    return pd.DataFrame(rows)
