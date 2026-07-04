"""CLI runner for US picks backtests using the shared backtest engine."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.backtest import run_picks_backtest
from src.data_loader import _cache_paths, fetch_ohlcv, fetch_ohlcv_batch, read_ohlcv_cache, write_ohlcv_cache
from src.universe_loader import load_universe


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run US picks backtest.")
    parser.add_argument("--config", default="configs/config_us.yaml")
    parser.add_argument("--label", default="backtest")
    parser.add_argument("--lookback", default="2y")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--holding-days", type=int, default=None, help="Override backtest.max_holding_days.")
    parser.add_argument(
        "--allowed-regimes",
        default=None,
        help="Comma-separated regime states allowed for entries, e.g. neutral,risk_on.",
    )
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--max-tickers", type=int, default=0, help="0 means no CLI cap.")
    parser.add_argument("--offline", action="store_true", help="Read parquet cache directly and skip network.")
    parser.add_argument("--out", default="output/backtest")
    parser.add_argument("--compare", default=None, help="Path to baseline summary.json.")
    return parser.parse_args()


def _load_config(path: str) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _offline_cache(ticker: str, cache_dir: str | Path) -> pd.DataFrame | None:
    data_path, _ = _cache_paths(ticker, cache_dir)
    if not data_path.exists():
        return None
    try:
        frame = pd.read_parquet(data_path)
    except Exception as exc:
        print(f"[WARN] cache read failed for {ticker}: {exc}")
        return None
    if frame is None or frame.empty:
        return None
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame.sort_index()


def _load_one_history(ticker: str, config: dict, lookback: str, offline: bool) -> pd.DataFrame | None:
    data_cfg = config.get("data", {})
    cache_dir = data_cfg.get("cache_dir", "data/cache/ohlcv")
    interval = data_cfg.get("interval", "1d")
    if offline:
        return _offline_cache(ticker, cache_dir)
    cached = read_ohlcv_cache(ticker, period=lookback, interval=interval, cache_dir=cache_dir)
    if cached is not None and not cached.empty:
        return cached.sort_index()
    fetched = fetch_ohlcv(
        ticker,
        period=lookback,
        interval=interval,
        timeout=int(data_cfg.get("request_timeout_seconds", 30)),
    )
    if fetched is not None and not fetched.empty:
        write_ohlcv_cache(ticker, fetched, period=lookback, interval=interval, cache_dir=cache_dir)
    return fetched.sort_index() if fetched is not None and not fetched.empty else None


def _load_histories(tickers: list[str], config: dict, lookback: str, offline: bool) -> dict[str, pd.DataFrame]:
    if not offline:
        data_cfg = config.get("data", {})
        histories, stats = fetch_ohlcv_batch(
            tickers,
            period=lookback,
            interval=data_cfg.get("interval", "1d"),
            timeout=int(data_cfg.get("request_timeout_seconds", 30)),
            batch_size=int(data_cfg.get("batch_size", 75)),
            cache_dir=data_cfg.get("cache_dir", "data/cache/ohlcv"),
        )
        print(
            "[LOAD] batch "
            f"hits={stats.get('cache_hits', 0)} misses={stats.get('cache_misses', 0)} "
            f"success={stats.get('download_success', 0)} failed={stats.get('download_failed', 0)} "
            f"ready={len(histories)}"
        )
        return {ticker: frame.sort_index() for ticker, frame in histories.items() if frame is not None and not frame.empty}

    histories: dict[str, pd.DataFrame] = {}
    total = max(len(tickers), 1)
    for number, ticker in enumerate(tickers, 1):
        frame = _load_one_history(ticker, config, lookback, offline)
        if frame is not None and not frame.empty:
            histories[ticker] = frame
        if number == 1 or number == total or number % 25 == 0:
            print(f"[LOAD] {number}/{total} tickers, ready={len(histories)}")
    return histories


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def _save_outputs(out_dir: Path, label: str, trades: pd.DataFrame, equity: pd.DataFrame, summary: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out_dir / f"{label}_trades.csv", index=False, encoding="utf-8-sig")
    equity.to_csv(out_dir / f"{label}_equity.csv", index=False, encoding="utf-8-sig")
    (out_dir / f"{label}_summary.json").write_text(
        json.dumps(_json_ready(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _git_hash() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def _print_summary(summary: dict) -> None:
    fields = [
        ("trade_count", "trades"),
        ("win_rate", "win_rate_pct"),
        ("expected_r", "expected_r"),
        ("expected_r_ci95_low", "expected_r_ci95_low"),
        ("expected_r_ci95_high", "expected_r_ci95_high"),
        ("profit_factor", "profit_factor"),
        ("mdd", "mdd_pct"),
        ("benchmark_mdd", "benchmark_mdd_pct"),
        ("sharpe", "sharpe"),
        ("total_return_pct", "total_return_pct"),
        ("benchmark_return_pct", "benchmark_return_pct"),
        ("capital_exposure_pct", "capital_exposure_pct"),
        ("exposure_adjusted_return_pct", "exposure_adjusted_return_pct"),
        ("ambiguous_rate", "ambiguous_rate_pct"),
        ("effective_replay_days", "effective_replay_days"),
        ("data_asof", "data_asof"),
        ("is_trade_count", "is_trades"),
        ("oos_trade_count", "oos_trades"),
        ("oos_expected_r", "oos_expected_r"),
    ]
    print("\n[SUMMARY]")
    for key, label in fields:
        print(f"{label}: {summary.get(key, 0)}")


def _print_compare(current: dict, baseline_path: str) -> None:
    path = Path(baseline_path)
    if not path.exists():
        print(f"\n[COMPARE] baseline not found: {path}")
        return
    baseline = json.loads(path.read_text(encoding="utf-8"))
    print("\n[COMPARE] baseline -> current (delta)")
    for key in ["expected_r", "oos_expected_r", "win_rate", "profit_factor", "mdd", "total_return_pct", "benchmark_return_pct"]:
        base_value = baseline.get(key, 0)
        current_value = current.get(key, 0)
        try:
            delta = float(current_value) - float(base_value)
            print(f"{key}: {base_value} -> {current_value} ({delta:+.4f})")
        except (TypeError, ValueError):
            print(f"{key}: {base_value} -> {current_value}")


def main() -> int:
    args = _parse_args()
    config = _load_config(args.config)
    config.setdefault("market", {})["region"] = "us"
    if args.holding_days is not None:
        if args.holding_days < 1:
            raise ValueError("--holding-days must be at least 1")
        config.setdefault("backtest", {})["max_holding_days"] = args.holding_days
    if args.allowed_regimes:
        config.setdefault("backtest", {})["allowed_regimes"] = [
            item.strip() for item in args.allowed_regimes.split(",") if item.strip()
        ]

    universe, stats = load_universe(config)
    tickers = universe["ticker"].astype(str).tolist()
    sector_by_ticker = {}
    if "sector" in universe.columns:
        sector_by_ticker = universe.set_index("ticker")["sector"].fillna("").astype(str).to_dict()
    if args.max_tickers > 0:
        tickers = tickers[: args.max_tickers]
    print(f"[UNIVERSE] {stats.get('universe_label')} loaded={len(universe)} used={len(tickers)}")

    histories = _load_histories(tickers, config, args.lookback, args.offline)
    benchmark_df = _load_one_history(args.benchmark, config, args.lookback, args.offline)
    if benchmark_df is None or benchmark_df.empty:
        print(f"[WARN] benchmark history unavailable: {args.benchmark}")
        benchmark_df = None

    trades, summary, equity = run_picks_backtest(
        tickers,
        config,
        market="us",
        top_n_per_day=args.top_n,
        lookback_period=args.lookback,
        data_by_ticker=histories,
        benchmark_df=benchmark_df,
        sector_by_ticker=sector_by_ticker,
        progress_cb=lambda fraction, message: print(f"[RUN] {fraction:.0%} {message}") if int(fraction * 100) % 10 == 0 else None,
    )
    summary = {
        **summary,
        "label": args.label,
        "config": args.config,
        "lookback": args.lookback,
        "top_n": args.top_n,
        "holding_days": config.get("backtest", {}).get("max_holding_days"),
        "allowed_regimes": config.get("backtest", {}).get("allowed_regimes"),
        "benchmark": args.benchmark,
        "offline": bool(args.offline),
        "requested_tickers": len(tickers),
        "loaded_tickers": len(histories),
        "git_hash": _git_hash(),
        "config_snapshot": config,
    }
    _save_outputs(Path(args.out), args.label, trades, equity, summary)
    _print_summary(summary)
    if args.compare:
        _print_compare(summary, args.compare)
    print(f"\n[OUT] saved to {Path(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
