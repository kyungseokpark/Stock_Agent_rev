import numpy as np
import pandas as pd
import yaml


def test_regime_detects_short_break_under_ma50():
    from src.regime import classify_regime

    close = np.r_[np.linspace(100, 130, 190), np.linspace(130, 116, 10)]
    df = pd.DataFrame({"Close": close}, index=pd.date_range("2025-01-01", periods=len(close), freq="B"))

    result = classify_regime(df)

    assert result["regime_state"] == "risk_off"
    assert result["regime_score"] == 0.0


def test_wo007_falling_pullback_is_demoted_to_excluded():
    from src.scoring import calculate_score

    snapshot = {
        "current_price": 98,
        "ma20": 99,
        "ma50": 100,
        "ma200": 90,
        "rsi14": 50,
        "volume_ratio": 1.5,
        "return_5d": 1,
        "return_20d": -8,
        "macd": 1,
        "macd_signal": 0,
        "macd_hist": 1,
        "macd_hist_prev": 0.5,
        "high20": 100,
        "high60": 101,
        "low20": 90,
        "atr_pct": 4,
    }
    targets = {"risk_reward": 17, "target1": 120, "stop_loss": 80, "valid": True}
    context = {"vcp_score": 70, "rs_rank": 40, "weekly_trend_ok": True, "regime_score": 0, "regime_state": "risk_off"}
    config = {
        "signal_weights": {"base": 0.70, "vcp": 0.15, "rs": 0.10, "mtf": 0.03, "regime": 0.02},
        "ranking": {"min_rs_rank": 70},
    }

    score = calculate_score(snapshot, targets, context=context, config=config)

    assert score["risk_penalty"] == -36
    assert score["final_score"] == 27
    assert score["decision"] == "Excluded"


def test_wo007_healthy_us_leader_keeps_high_score():
    from src.scoring import calculate_score

    snapshot = {
        "current_price": 110,
        "ma20": 105,
        "ma50": 100,
        "ma200": 90,
        "rsi14": 60,
        "volume_ratio": 1.5,
        "return_5d": 3,
        "return_20d": 10,
        "macd": 1,
        "macd_signal": 0,
        "macd_hist": 1,
        "macd_hist_prev": 0.5,
        "high20": 112,
        "high60": 114,
        "low20": 90,
        "atr_pct": 4,
    }
    targets = {"risk_reward": 2.3, "target1": 130, "stop_loss": 95, "valid": True}
    context = {"vcp_score": 95, "rs_rank": 88, "weekly_trend_ok": True, "regime_score": 1, "regime_state": "risk_on"}
    config = {
        "signal_weights": {"base": 0.70, "vcp": 0.15, "rs": 0.10, "mtf": 0.03, "regime": 0.02},
        "ranking": {"min_rs_rank": 70},
    }

    score = calculate_score(snapshot, targets, context=context, config=config)

    assert score["base_score"] == 96
    assert score["final_score"] == 95
    assert score["decision"] == "Strong Candidate"


def test_wo007_kr_weights_are_adjusted_without_changing_us_config():
    kr = yaml.safe_load(open("configs/config_kr.yaml", encoding="utf-8"))
    us = yaml.safe_load(open("configs/config_us.yaml", encoding="utf-8"))

    assert kr["signal_weights"] == {"base": 0.60, "vcp": 0.13, "rs": 0.20, "mtf": 0.02, "regime": 0.05}
    assert us["signal_weights"] == {"base": 0.70, "vcp": 0.15, "rs": 0.10, "mtf": 0.03, "regime": 0.02}
