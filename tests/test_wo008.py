import pandas as pd


def _bars(base: float, rows: int = 135) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=rows)
    close = pd.Series([base + i * 0.1 for i in range(rows)], index=dates)
    return pd.DataFrame(
        {
            "Open": close + 0.1,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Adj Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )


def test_picks_backtest_uses_adjusted_score_and_soft_vcp(monkeypatch):
    import src.backtest as backtest

    def fake_signal(frame, config, as_of_index=None, context=None):
        last_close = float(frame["Close"].iloc[as_of_index])
        if last_close < 100:
            return {
                "valid_signal": True,
                "final_score": 60,
                "vcp_score": 40,
                "rs_rank": 0,
                "regime_state": "neutral",
                "atr14": 1.0,
                "risk_reward": 2.0,
                "chart_type": "Falling knife",
            }
        return {
            "valid_signal": True,
            "final_score": 58,
            "vcp_score": 20,
            "rs_rank": 0,
            "regime_state": "neutral",
            "atr14": 1.0,
            "risk_reward": 2.0,
            "chart_type": "Breakout",
        }

    monkeypatch.setattr(backtest, "generate_signal", fake_signal)
    config = {
        "data": {"min_rows": 120},
        "screening": {"min_score_for_candidate": 50},
        "scoring_adjustment": {
            "use_adjusted_score": True,
            "exclude_sample_data": True,
            "chart_type_bonus": {"breakout": 5, "falling_knife": -10, "unknown": -2},
        },
        "composite": {"enabled": False},
        "vcp": {"min_score": 70},
        "ranking": {"min_rs_rank": 0},
        "backtest": {"max_universe": 10, "max_holding_days": 1, "target_r": 2.0, "min_final_score": 50, "min_vcp_score": 0},
        "risk": {"atr_stop_multiplier": 1.0, "min_risk_reward": 1.2},
        "portfolio": {"account_equity": 100_000},
    }

    trades, summary, _ = backtest.run_picks_backtest(
        ["LOW_FINAL_BETTER_CHART", "HIGH_FINAL_WEAKER_CHART"],
        config,
        top_n_per_day=1,
        data_by_ticker={
            "LOW_FINAL_BETTER_CHART": _bars(120),
            "HIGH_FINAL_WEAKER_CHART": _bars(50),
        },
    )

    assert not trades.empty
    assert trades.iloc[0]["ticker"] == "LOW_FINAL_BETTER_CHART"
    assert float(trades.iloc[0]["vcp_score"]) < 70
    assert summary["trade_count"] > 0


def test_simulate_exit_marks_same_bar_stop_target_as_ambiguous():
    from src.backtest import _simulate_exit, _summarize

    df = pd.DataFrame(
        {
            "Open": [10.0],
            "High": [12.5],
            "Low": [8.5],
            "Close": [10.5],
        },
        index=pd.bdate_range("2025-01-01", periods=1),
    )

    outcome = _simulate_exit(df, entry_idx=0, entry=10.0, risk=1.0, hold_days=1, target_r=2.0)

    assert outcome["exit_reason"] == "stop"
    assert outcome["ambiguous"] is True
    assert outcome["first_hit"] == "ambiguous"

    trades = pd.DataFrame({"r_multiple": [-1.0], "sample": ["OOS"], "ambiguous": [True]})
    equity = pd.DataFrame({"equity": [100_000.0], "open_positions": [0], "capital_exposure_pct": [0.0]})
    summary = _summarize(trades, equity, 100_000.0)
    assert summary["ambiguous_count"] == 1
    assert summary["ambiguous_rate"] == 100.0


def test_cache_period_covers_shorter_requests_only():
    from src.data_loader import _cache_period_covers

    assert _cache_period_covers("2y", "1y")
    assert not _cache_period_covers("1y", "2y")


def test_picks_backtest_applies_sector_cap(monkeypatch):
    import src.backtest as backtest

    def fake_signal(frame, config, as_of_index=None, context=None):
        return {
            "valid_signal": True,
            "final_score": 80,
            "vcp_score": 0,
            "rs_rank": 0,
            "regime_state": "neutral",
            "atr14": 1.0,
            "risk_reward": 2.0,
            "chart_type": "Breakout",
        }

    monkeypatch.setattr(backtest, "generate_signal", fake_signal)
    config = {
        "data": {"min_rows": 120},
        "screening": {"min_score_for_candidate": 50},
        "scoring_adjustment": {"use_adjusted_score": True, "chart_type_bonus": {"breakout": 0, "unknown": 0}},
        "composite": {"enabled": False},
        "vcp": {"min_score": 0},
        "ranking": {"min_rs_rank": 0},
        "backtest": {"max_universe": 10, "max_holding_days": 10, "target_r": 10.0, "min_final_score": 50, "min_vcp_score": 0},
        "risk": {"atr_stop_multiplier": 100.0, "min_risk_reward": 1.2},
        "portfolio": {"account_equity": 100_000, "max_per_sector": 1},
    }

    _, _, equity = backtest.run_picks_backtest(
        ["AAA", "BBB", "CCC"],
        config,
        top_n_per_day=3,
        data_by_ticker={"AAA": _bars(100), "BBB": _bars(101), "CCC": _bars(102)},
        sector_by_ticker={"AAA": "Technology", "BBB": "Technology", "CCC": "Technology"},
    )

    assert int(equity["open_positions"].max()) == 1
