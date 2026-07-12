import numpy as np
import pandas as pd
import pytest

from src.indicators import build_indicator_snapshot
from src.scoring import calculate_score, dema_stoch_bonus
from src.signals import dema_stoch_signals
from src.evidence_builder import build_evidence


def _ohlcv(rows: int) -> pd.DataFrame:
    close = pd.Series(np.arange(100, 100 + rows, dtype=float))
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(rows, 1_000_000.0),
        }
    )


def test_snapshot_populates_dema_and_stochastic_values_from_config():
    config = {"indicators": {"dema_period": 5, "stoch_period": 5, "stoch_d_smooth": 3}}
    snapshot = build_indicator_snapshot(_ohlcv(12), config)

    assert all(snapshot[key] is not None for key in ("dema60", "dema60_prev", "stoch_k", "stoch_d", "stoch_d_prev"))
    assert snapshot["dema60"] > snapshot["dema60_prev"]
    assert snapshot["stoch_d"] == snapshot["stoch_d_prev"] == pytest.approx(83.33333333333333)


def test_snapshot_returns_none_when_dema_stochastic_history_is_insufficient():
    config = {"indicators": {"dema_period": 60, "stoch_period": 60, "stoch_d_smooth": 3}}
    snapshot = build_indicator_snapshot(_ohlcv(62), config)

    assert {key: snapshot[key] for key in ("dema60", "dema60_prev", "stoch_k", "stoch_d", "stoch_d_prev")} == {
        "dema60": None,
        "dema60_prev": None,
        "stoch_k": None,
        "stoch_d": None,
        "stoch_d_prev": None,
    }


def test_dema_stoch_signals_are_config_driven_and_safe_for_missing_values():
    config = {
        "scoring": {
            "dema_stoch": {
                "enabled": True,
                "vol_surge_mult": 1.5,
                "overheat_gap_pct": 8.0,
                "candle_return_pct": 5.0,
                "atr_stop_excess_mult": 2.5,
            }
        }
    }
    snapshot = {
        "current_price": 110,
        "previous_close": 99,
        "dema60": 105,
        "dema60_prev": 100,
        "stoch_d": 55,
        "stoch_d_prev": 45,
        "volume_ratio": 1.6,
        "ma20": 100,
        "rsi14": 50,
        "atr14": 2,
        "stop_loss": 104,
    }

    signals = dema_stoch_signals(snapshot, config)

    assert signals == {
        "dema60_breakout": True,
        "dema60_slope_up": True,
        "stoch_d_cross_50_up": True,
        "vol_surge": True,
        "index_above": False,
        "candle_overheat": True,
        "atr_stop_excess": True,
    }
    assert not any(dema_stoch_signals({}, config).values())


def test_dema_stoch_bonus_applies_configured_cap_and_can_be_disabled():
    signals = {
        "dema60_breakout": True,
        "dema60_slope_up": True,
        "stoch_d_cross_50_up": True,
        "vol_surge": True,
        "index_above": False,
        "candle_overheat": True,
        "atr_stop_excess": False,
    }
    config = {
        "scoring": {
            "dema_stoch": {
                "enabled": True,
                "net_cap": 3,
                "net_floor": -2,
                "weights": {
                    "dema60_breakout": 2,
                    "dema60_slope_up": 1,
                    "stoch_d_cross_50_up": 1,
                    "vol_surge": 2,
                    "candle_overheat": -1,
                },
            }
        }
    }

    assert dema_stoch_bonus(signals, config) == (3.0, ["dema60_breakout", "dema60_slope_up", "stoch_d_cross_50_up", "vol_surge", "candle_overheat"])
    assert dema_stoch_bonus(signals, {"scoring": {"dema_stoch": {"enabled": False}}}) == (0.0, [])


def test_calculate_score_exposes_dema_stoch_bonus_without_changing_disabled_score():
    snapshot = {
        "current_price": 110,
        "previous_close": 99,
        "ma20": 100,
        "ma50": 95,
        "ma200": 90,
        "rsi14": 55,
        "volume_ratio": 1.6,
        "return_5d": 2,
        "return_20d": 4,
        "macd": 2,
        "macd_signal": 1,
        "macd_hist": 1,
        "macd_hist_prev": 0,
        "high20": 110,
        "high60": 110,
        "low20": 90,
        "atr_pct": 2,
        "atr14": 2,
        "dema60": 105,
        "dema60_prev": 100,
        "stoch_d": 55,
        "stoch_d_prev": 45,
    }
    targets = {"valid": True, "risk_reward": 2, "target1": 120, "stop_loss": 104}
    enabled = {
        "scoring": {
            "dema_stoch": {
                "enabled": True,
                "vol_surge_mult": 1.5,
                "overheat_gap_pct": 20,
                "candle_return_pct": 20,
                "atr_stop_excess_mult": 10,
                "net_cap": 3,
                "net_floor": -2,
                "weights": {"dema60_breakout": 2, "dema60_slope_up": 1, "stoch_d_cross_50_up": 1, "vol_surge": 2},
            }
        }
    }

    with_bonus = calculate_score(snapshot, targets, config=enabled)
    without_bonus = calculate_score(snapshot, targets, config={"scoring": {"dema_stoch": {"enabled": False}}})

    assert with_bonus["dema_stoch_bonus"] == 3.0
    assert with_bonus["final_score"] == min(100, without_bonus["final_score"] + 3)
    assert without_bonus["dema_stoch_bonus"] == 0.0


def test_evidence_mentions_only_active_dema_stoch_signals():
    snapshot = {"current_price": 100, "ma20": 90, "ma50": 80, "rsi14": 55, "volume_ratio": 1.6, "macd": 1, "macd_signal": 0}
    score = {
        "final_score": 75,
        "dema_stoch_signals": {
            "dema60_breakout": True,
            "dema60_slope_up": False,
            "stoch_d_cross_50_up": True,
            "vol_surge": True,
            "candle_overheat": True,
            "atr_stop_excess": False,
        },
    }

    evidence = build_evidence(snapshot, score, {"risk_reward": 1.5}, "Breakout")

    assert any("DEMA(60) 상향 돌파" in point for point in evidence["evidence_points"])
    assert any("스토캐스틱 %D" in point for point in evidence["evidence_points"])
    assert any("돌파봉" in point for point in evidence["risk_points"])
    assert not any("ATR 대비 손절폭" in point for point in evidence["risk_points"])
