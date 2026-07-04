
import pandas as pd


def test_select_top_candidates_applies_min_score_gate():
    from src.recommendation_quality import select_top_candidates

    df = pd.DataFrame(
        [
            {"ticker": "LOW", "adjusted_score": 79, "final_score": 82, "risk_reward": 2.0, "is_sample_data": False},
            {"ticker": "HIGH", "adjusted_score": 81, "final_score": 81, "risk_reward": 1.5, "is_sample_data": False},
        ]
    )
    config = {
        "screening": {"min_score_for_candidate": 80},
        "scoring_adjustment": {"use_adjusted_score": True, "exclude_sample_data": True},
    }

    selected = select_top_candidates(df, config, top_n=2)

    # 기준 통과 후보가 우선, 미달 후보는 사유가 표기된 보충 후보로 채워 top_n을 유지한다.
    assert selected["ticker"].tolist() == ["HIGH", "LOW"]
    assert selected.iloc[0]["selection_note"] == ""
    assert "기준 미달 보충 후보" in selected.iloc[1]["selection_note"]

    strict_pool = select_top_candidates(df, config, top_n=1)
    assert strict_pool["ticker"].tolist() == ["HIGH"]


def test_run_screen_calls_generate_signal_once_per_eligible_ticker(monkeypatch):
    import main
    from src.data_loader import build_sample_ohlcv

    tickers = pd.DataFrame(
        [
            {"ticker": "AAA", "name": "AAA Inc", "sector": "Tech", "market": "US", "source": "test"},
            {"ticker": "BBB", "name": "BBB Inc", "sector": "Tech", "market": "US", "source": "test"},
        ]
    )
    stats = {
        "market_region": "us",
        "market_label": "US Test",
        "currency": "USD",
        "universe_mode": "custom",
        "universe_label": "test",
        "raw_tickers_loaded": 2,
        "unique_tickers": 2,
    }
    histories = {ticker: build_sample_ohlcv(ticker, 160) for ticker in tickers["ticker"]}
    calls = []

    monkeypatch.setattr(main, "load_universe", lambda config: (tickers, stats.copy()))
    monkeypatch.setattr(main, "calculate_market_regime", lambda market: {"market_regime": "??", "market_comment": ""})
    monkeypatch.setattr(main, "write_market_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "fetch_ohlcv_batch", lambda ticker_list, **kwargs: (histories, {"cache_hits": 2, "cache_misses": 0, "download_success": 0, "download_failed": 0, "individual_retries": 0}))
    monkeypatch.setattr(main, "liquidity_metrics", lambda df, config: {"passed": True, "reason": "", "avg_dollar_volume_20d": 1_000_000})
    monkeypatch.setattr(main, "rank_relative_strength", lambda frames: {"AAA": 90.0, "BBB": 80.0})
    monkeypatch.setattr(main, "build_evidence", lambda *args, **kwargs: {"evidence_points": [], "risk_points": []})
    monkeypatch.setattr(main, "risk_reward_status", lambda value: {"risk_reward_status_label": "ok"})
    monkeypatch.setattr(main, "calculate_chase_risk", lambda snapshot: {})
    monkeypatch.setattr(main, "enrich_recommendation_text", lambda row: {"selection_reason": "", "caution": ""})
    monkeypatch.setattr(main, "add_consecutive_recommendations", lambda df, market: df)
    monkeypatch.setattr(main, "add_sector_concentration", lambda full, top: (full, top))
    monkeypatch.setattr(main, "apply_portfolio_constraints", lambda candidates, histories, config, top_n: candidates.head(top_n).copy())
    monkeypatch.setattr(main, "save_recommendations", lambda *args, **kwargs: 0)
    monkeypatch.setattr(main, "write_performance_outputs", lambda *args, **kwargs: {})
    monkeypatch.setattr(main, "write_outputs", lambda *args, **kwargs: {})

    def fake_generate_signal(df, config, context=None):
        calls.append(context.get("rs_rank"))
        return {
            "current_price": 100,
            "stop_loss": 90,
            "target1": 120,
            "target2": 130,
            "risk_reward": 2.0,
            "chart_type": "Breakout",
            "final_score": 80,
            "decision": "Candidate",
            "valid_signal": True,
        }

    monkeypatch.setattr(main, "generate_signal", fake_generate_signal)

    config = {
        "market": {"region": "us", "label": "US Test", "currency": "USD"},
        "data": {"min_rows": 120, "sample_fallback": False, "request_timeout_seconds": 30},
        "screening": {"top_n": 2, "full_result_limit": 10, "min_score_for_candidate": 0},
        "scoring_adjustment": {"use_adjusted_score": True, "exclude_sample_data": True, "chart_type_bonus": {"breakout": 0, "unknown": 0}},
        "risk": {"min_risk_reward": 1.0},
        "ranking": {"min_rs_rank": 0},
        "vcp": {"min_score": 0},
        "regime": {"enabled": False},
        "performance": {"auto_update_tracking": False},
        "output": {"output_dir": "output/test"},
    }

    main.run_screen(config, top_n=2)

    assert calls == [90.0, 80.0]
