"""Shared command-line runner for US/KR stock screeners."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.analysis_enrichment import (
    add_consecutive_recommendations,
    add_sector_concentration,
    calculate_chase_risk,
    calculate_market_regime,
    enrich_recommendation_text,
    risk_reward_status,
    write_market_summary,
)
from src.data_loader import build_sample_ohlcv, fetch_ohlcv_batch
from src.evidence_builder import build_evidence
from src.force_inflow import add_composite_score, compute_force_inflow
from src.market_config import load_config, resolve_config_path
from src.performance_tracker import (
    build_performance_summary_text,
    get_tracking_table,
    save_recommendations,
    summarize_tracking_performance,
    update_tracking_results,
)
from src.recommendation_quality import (
    apply_soft_candidate_filters,
    build_quality_metrics,
    ranking_score_column,
    select_top_candidates,
)
from src.ranking import rank_relative_strength
from src.portfolio import apply_portfolio_constraints
from src.report_builder import write_outputs
from src.signal_engine import generate_signal
from src.telegram_sender import build_telegram_message, get_telegram_credentials, send_text_messages
from src.universe_loader import liquidity_metrics, load_universe


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        handlers=[logging.FileHandler("logs/run.log", encoding="utf-8"), logging.StreamHandler()],
    )


def build_row(meta: dict, snapshot: dict, targets: dict, score: dict, chart_type: str, evidence: dict) -> dict:
    row = {k: v for k, v in snapshot.items() if k != "history"}
    row.update(targets)
    row.update(score)
    row.update(evidence)
    row.update(chart_type=chart_type)
    row.update(meta)
    return row


def should_apply_liquidity_filter(config: dict, universe_mode: str) -> bool:
    custom_modes = {"custom", "custom_kr"}
    if universe_mode in custom_modes and not bool(config.get("filters", {}).get("apply_to_custom", False)):
        return False
    return True


def write_performance_outputs(config: dict, market_region: str) -> dict:
    output_cfg = config.get("output", {})
    output_dir = Path(output_cfg.get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_kr" if market_region == "kr" else ""
    tracking_path = Path(output_cfg.get("performance_tracking_csv", output_dir / f"performance_tracking{suffix}.csv"))
    summary_path = Path(output_cfg.get("performance_summary_txt", output_dir / f"performance_summary{suffix}.txt"))

    tracking_df = get_tracking_table(market_region)
    tracking_df.to_csv(tracking_path, index=False, encoding="utf-8-sig")
    summary = summarize_tracking_performance(market_region)
    summary_text = build_performance_summary_text(summary)
    summary_path.write_text(summary_text, encoding="utf-8")
    config["_performance_summary"] = summary
    config["_performance_summary_text"] = summary_text
    if "_run_stats" in config:
        config["_run_stats"]["performance_summary_text"] = summary_text
    return {
        "performance_tracking_csv": str(tracking_path),
        "performance_summary_txt": str(summary_path),
    }


def run_screen(config: dict, top_n: int | None = None, progress_cb=None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    tickers, stats = load_universe(config)
    universe_mode = stats["universe_mode"]
    market_region = stats["market_region"]
    market_summary = calculate_market_regime(market_region)
    calibration_path = Path(config.get("output", {}).get("output_dir", f"output/{market_region}")) / "score_calibration.csv"
    calibration_table = pd.read_csv(calibration_path) if calibration_path.exists() else pd.DataFrame()
    write_market_summary(market_summary, config.get("output", {}).get("output_dir", "output"))
    logging.info("Market: %s", stats["market_label"])
    logging.info("Universe mode: %s", universe_mode)
    logging.info("Raw tickers loaded: %s", stats["raw_tickers_loaded"])
    logging.info("Unique tickers: %s", stats["unique_tickers"])

    rows = []
    histories: dict[str, pd.DataFrame] = {}
    meta_by_ticker = tickers.set_index("ticker").to_dict("index")
    data_cfg = config.get("data", {})
    min_rows = int(data_cfg.get("min_rows", 120))
    timeout = int(data_cfg.get("request_timeout_seconds", 30))
    batch_size = int(data_cfg.get("batch_size", 75))
    cache_dir = data_cfg.get("cache_dir", "data/cache/ohlcv")
    use_fallback = bool(data_cfg.get("sample_fallback", True)) and universe_mode in {"custom", "custom_kr"}
    enforce_liquidity = should_apply_liquidity_filter(config, universe_mode)
    passed_liquidity = 0
    skipped_short = 0
    sample_fallback_count = 0

    ticker_list = tickers["ticker"].astype(str).tolist()
    if progress_cb:
        progress_cb(
            {
                "market": market_region,
                "stage": "데이터 수집",
                "current": 0,
                "total": len(ticker_list),
                "ticker": "",
            }
        )
    fetched_histories, fetch_stats = fetch_ohlcv_batch(
        ticker_list,
        period=data_cfg.get("period", "1y"),
        interval=data_cfg.get("interval", "1d"),
        timeout=timeout,
        batch_size=batch_size,
        cache_dir=cache_dir,
    )
    stats.update({f"ohlcv_{key}": value for key, value in fetch_stats.items()})
    benchmark_tickers = ["SPY", "QQQ", "^GSPC"] if market_region == "us" else ["^KS11", "^KQ11"]
    try:
        _, benchmark_stats = fetch_ohlcv_batch(
            benchmark_tickers,
            period=data_cfg.get("period", "1y"),
            interval=data_cfg.get("interval", "1d"),
            timeout=timeout,
            batch_size=len(benchmark_tickers),
            cache_dir=cache_dir,
        )
        stats.update({f"benchmark_cache_{key}": value for key, value in benchmark_stats.items()})
    except Exception as exc:
        logging.warning("Benchmark cache refresh skipped: %s", exc)

    data_meta: dict[str, dict] = {}
    liquidity_by_ticker: dict[str, dict] = {}
    eligible_tickers: list[str] = []

    for idx, ticker in enumerate(ticker_list, start=1):
        if progress_cb and (idx == 1 or idx == len(ticker_list) or idx % 5 == 0):
            progress_cb(
                {
                    "market": market_region,
                    "stage": "데이터 수집",
                    "current": idx,
                    "total": len(ticker_list),
                    "ticker": ticker,
                }
            )
        logging.info("Preparing %s/%s %s", idx, len(ticker_list), ticker)
        df = fetched_histories.get(ticker, pd.DataFrame())
        is_sample_data = False
        data_source = "real"
        data_quality = "normal"
        data_warning = ""
        if len(df) < min_rows and use_fallback:
            logging.warning("Using deterministic sample data for %s", ticker)
            df = build_sample_ohlcv(ticker, max(min_rows + 20, 260))
            is_sample_data = True
            data_source = "sample"
            data_quality = "fallback_used"
            data_warning = "샘플 데이터 사용"
            sample_fallback_count += 1
        if len(df) < min_rows:
            logging.warning("Skipping %s: only %s rows", ticker, len(df))
            skipped_short += 1
            continue

        histories[ticker] = df
        data_meta[ticker] = {
            "is_sample_data": is_sample_data,
            "data_source": data_source,
            "data_quality": data_quality,
            "data_warning": data_warning,
        }
        filter_info = liquidity_metrics(df, config)
        liquidity_by_ticker[ticker] = filter_info
        if filter_info["passed"]:
            passed_liquidity += 1
        if enforce_liquidity and not filter_info["passed"]:
            logging.info("Skipping %s: %s", ticker, filter_info["reason"])
            continue
        eligible_tickers.append(ticker)

    rs_ranks = rank_relative_strength(histories)
    stats["ohlcv_skipped_short"] = skipped_short
    stats["sample_fallback_count"] = sample_fallback_count

    if progress_cb:
        progress_cb(
            {
                "market": market_region,
                "stage": "신호 계산",
                "current": 0,
                "total": len(eligible_tickers),
                "ticker": "",
            }
        )

    force_cfg = config.get("force_inflow", {})
    real_fetch_limit = int(force_cfg.get("real_fetch_limit_per_run", 0) or 0)
    defer_real_flow = (
        market_region == "kr"
        and bool(force_cfg.get("prefer_real_data", True))
        and real_fetch_limit > 0
        and len(eligible_tickers) > real_fetch_limit
    )
    if defer_real_flow:
        stats["force_real_fetch_mode"] = f"상위 {real_fetch_limit}개 후보만 실수급 재조회"

    for idx, ticker in enumerate(eligible_tickers, start=1):
        if progress_cb and (idx == 1 or idx == len(eligible_tickers) or idx % 5 == 0):
            progress_cb(
                {
                    "market": market_region,
                    "stage": "신호 계산",
                    "current": idx,
                    "total": len(eligible_tickers),
                    "ticker": ticker,
                }
            )
        logging.info("Processing signal %s/%s %s", idx, len(eligible_tickers), ticker)
        try:
            df = histories[ticker]
            meta_info = data_meta[ticker]
            filter_info = liquidity_by_ticker[ticker]
            signal = generate_signal(
                df,
                config,
                context={
                    "market_summary": market_summary,
                    "is_sample_data": meta_info["is_sample_data"],
                    "rs_rank": rs_ranks.get(ticker, 0.0),
                    "calibration": calibration_table,
                },
            )
            if not signal.get("current_price"):
                continue
            snapshot = {**signal, "history": df}
            targets = signal
            score = signal
            chart_type = signal["chart_type"]
            evidence = build_evidence(snapshot, score, targets, chart_type)
            risk_reward_info = risk_reward_status(targets.get("risk_reward", 0))
            chase_risk = calculate_chase_risk(snapshot)
            quality = build_quality_metrics(
                final_score=score.get("final_score", 0),
                chart_type=chart_type,
                targets=targets,
                filter_info=filter_info,
                is_sample_data=meta_info["is_sample_data"],
                data_source=meta_info["data_source"],
                data_quality=signal.get("data_quality_flag", meta_info["data_quality"]),
                data_warning=signal.get("data_quality_reasons", meta_info["data_warning"]),
                config=config,
            )
            meta = {
                "ticker": ticker,
                "market_region": market_region,
                "universe_mode": universe_mode,
                **meta_by_ticker.get(ticker, {}),
            }
            row = build_row(meta, snapshot, targets, score, chart_type, evidence)
            row.update(market_summary)
            row.update(risk_reward_info)
            row.update(chase_risk)
            row.update(quality)
            if progress_cb:
                progress_cb(
                    {
                        "market": market_region,
                        "stage": "세력·종합",
                        "current": idx,
                        "total": len(eligible_tickers),
                        "ticker": ticker,
                    }
                )
            if bool(config.get("force_inflow", {}).get("run_with_screening", True)):
                force_config = config
                if defer_real_flow:
                    force_config = {**config, "force_inflow": {**force_cfg, "prefer_real_data": False}}
                row.update(compute_force_inflow(ticker, df, force_config))
            else:
                row.update(
                    {
                        "force_inflow_pct": pd.NA,
                        "force_inflow_grade": "disabled",
                        "force_inflow_source": "disabled",
                        "force_position": "disabled",
                        "force_penalty": 0.0,
                        "force_sequence": 0.0,
                    }
                )
            row.update(add_composite_score(row, config))
            row.update(enrich_recommendation_text(row))
            rows.append(row)
        except Exception as exc:
            logging.exception("Failed to process %s: %s", ticker, exc)

    stats["passed_liquidity_filter"] = passed_liquidity
    if progress_cb:
        progress_cb(
            {
                "market": market_region,
                "stage": "후보 선정",
                "current": 0,
                "total": max(len(rows), 1),
                "ticker": "",
            }
        )
    full_df = pd.DataFrame(rows)
    if full_df.empty:
        full_df = pd.DataFrame(
            columns=[
                "ticker",
                "name",
                "market_region",
                "universe_mode",
                "source",
                "passed_liquidity_filter",
                "filter_reason",
                "avg_dollar_volume_20d",
                "score",
                "adjusted_score",
                "is_sample_data",
                "data_source",
                "data_quality",
                "data_warning",
                "liquidity_warning",
                "passed_risk_reward_filter",
                "risk_reward_warning",
                "chart_type_penalty",
                "quality_penalty",
                "final_score",
                "decision",
            ]
        )
        top5_df = full_df.copy()
    else:
        numeric_cols = [
            "current_price",
            "return_1d",
            "return_5d",
            "return_20d",
            "ma20",
            "ma50",
            "ma200",
            "rsi14",
            "macd",
            "macd_signal",
            "macd_hist",
            "atr14",
            "atr_pct",
            "volume_ratio",
            "high20",
            "high60",
            "low20",
            "low60",
            "avg_dollar_volume_20d",
            "score",
            "adjusted_score",
            "chart_type_penalty",
            "quality_penalty",
            "market_return_5d",
            "prev_close",
            "last_open",
            "last_close",
            "last_day_return",
            "open_gap",
            "intraday_return",
            "distance_from_ma20",
            "distance_from_ma60",
            "chart_score",
            "force_inflow_pct",
            "force_penalty",
            "force_sequence",
            "composite_score",
            "fi_foreign_pct",
            "fi_inst_pct",
            "fi_foreign_streak",
            "fi_retail_light",
            "fi_cmf20",
            "fi_obv_slope",
            "fi_vol_asym",
            "fi_box_breakout",
            "fi_accum_bar_ratio",
        ]
        for col in numeric_cols:
            if col in full_df.columns:
                full_df[col] = pd.to_numeric(full_df[col], errors="coerce").round(2)
        limit = int(config.get("screening", {}).get("full_result_limit", 50))
        top_n = top_n or int(config.get("screening", {}).get("top_n", 5))
        sort_score_col = ranking_score_column(full_df, config)
        if defer_real_flow:
            real_targets = full_df.sort_values([sort_score_col, "risk_reward", "final_score"], ascending=False).head(real_fetch_limit).index
            real_updated = 0
            for row_idx in real_targets:
                ticker = str(full_df.at[row_idx, "ticker"])
                frame = histories.get(ticker)
                if frame is None or frame.empty:
                    continue
                flow = compute_force_inflow(ticker, frame, config)
                for key, value in flow.items():
                    full_df.at[row_idx, key] = value
                composite = add_composite_score(full_df.loc[row_idx].to_dict(), config)
                for key, value in composite.items():
                    full_df.at[row_idx, key] = value
                if flow.get("force_inflow_source") == "real":
                    real_updated += 1
            stats["force_real_fetch_count"] = real_updated
            for col in numeric_cols:
                if col in full_df.columns:
                    full_df[col] = pd.to_numeric(full_df[col], errors="coerce").round(2)
        full_df = full_df.sort_values([sort_score_col, "risk_reward", "final_score"], ascending=False).head(limit)
        full_df = add_consecutive_recommendations(full_df, market_region)
        stats["scored_result_count"] = len(full_df)
        candidate_pool = apply_soft_candidate_filters(full_df, config, top_n=top_n, stats=stats, sort_score_col=sort_score_col)
        if bool(config.get("regime", {}).get("enabled", True)) and market_summary.get("market_regime") in {"강한 하락", "하락 주의"}:
            top_n = min(top_n, int(config.get("regime", {}).get("risk_off_candidate_cap", 2)))
        ranked_candidates = select_top_candidates(candidate_pool, config, max(top_n * 3, top_n))
        top5_df = apply_portfolio_constraints(ranked_candidates, histories, config, top_n)
        full_df, top5_df = add_sector_concentration(full_df, top5_df)
        for frame in [full_df, top5_df]:
            for idx, row in frame.iterrows():
                frame.loc[idx, "selection_reason"] = enrich_recommendation_text(row.to_dict())["selection_reason"]
                frame.loc[idx, "caution"] = enrich_recommendation_text(row.to_dict())["caution"]
        full_df.insert(0, "rank", range(1, len(full_df) + 1))
        top5_df.insert(0, "rank", range(1, len(top5_df) + 1))

    stats["selected_top_candidates"] = len(top5_df)
    stats["market_regime"] = market_summary.get("market_regime")
    stats["market_comment"] = market_summary.get("market_comment")
    logging.info("Passed liquidity filter: %s", stats["passed_liquidity_filter"])
    logging.info("Selected top candidates: %s", stats["selected_top_candidates"])
    config["_run_stats"] = stats
    inserted = save_recommendations(datetime.now().strftime("%Y-%m-%d"), market_region, universe_mode, top5_df)
    logging.info("Recommendation history rows inserted: %s", inserted)
    tracking_updates = 0
    if bool(config.get("performance", {}).get("auto_update_tracking", False)):
        try:
            tracking_updates = update_tracking_results(market_region)
        except Exception as exc:
            logging.warning("Performance tracking update skipped: %s", exc)
    logging.info("Performance tracking rows updated: %s", tracking_updates)
    performance_paths = write_performance_outputs(config, market_region)
    paths = write_outputs(full_df, top5_df, config)
    paths.update(performance_paths)
    paths["stats"] = stats
    if progress_cb:
        progress_cb(
            {
                "market": market_region,
                "stage": "완료",
                "current": 1,
                "total": 1,
                "ticker": "",
            }
        )
    return full_df, top5_df, paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily chart-based stock Top 5 screener")
    parser.add_argument("--market", choices=["us", "kr", "both"], default="us")
    parser.add_argument("--config", default=None)
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--auto", action="store_true", help="Run unattended and exit with a scheduler-friendly status code.")
    parser.add_argument("--notify", choices=["telegram"], default=None)
    return parser.parse_args()


def _send_optional_notification(config: dict, top5_df: pd.DataFrame, paths: dict, notify: str | None) -> None:
    if notify != "telegram":
        return
    token, chat_id = get_telegram_credentials(config)
    message = build_telegram_message(top5_df, paths.get("stats", {}))
    send_text_messages(message, token, chat_id)


def run_from_args(args: argparse.Namespace) -> int:
    markets = ["kr", "us"] if args.market == "both" else [args.market]
    all_ok = True
    for market in markets:
        try:
            config_path = args.config if args.config and len(markets) == 1 else resolve_config_path(market)
            config = load_config(config_path)
            _, top5_df, paths = run_screen(config=config, top_n=args.top_n)
            _send_optional_notification(config, top5_df, paths, args.notify)
            logging.info("Processed %s output rows; selected %s rows", market, len(top5_df))

            print(f"Screener completed: {market}")
            for label, path in paths.items():
                print(f"- {label}: {path}")
        except Exception as exc:
            all_ok = False
            logging.exception("Screener failed for %s: %s", market, exc)
            print(f"Screener failed: {market}: {exc}", file=sys.stderr)
            if not args.auto:
                raise
    return 0 if all_ok else 1


def main() -> int:
    load_dotenv()
    setup_logging()
    return run_from_args(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
