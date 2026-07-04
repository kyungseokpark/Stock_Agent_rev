import numpy as np
import pandas as pd


def _ohlcv(close, volume):
    close = pd.Series(close, dtype=float)
    idx = pd.date_range("2025-01-01", periods=len(close), freq="B")
    return pd.DataFrame(
        {
            "Open": (close.shift(1).fillna(close.iloc[0]) * 0.995).to_numpy(),
            "High": (close * 1.02).to_numpy(),
            "Low": (close * 0.98).to_numpy(),
            "Close": close.to_numpy(),
            "Volume": pd.Series(volume, dtype=float).to_numpy(),
        },
        index=idx,
    )


def test_force_inflow_rewards_base_accumulation_more_than_top_distribution():
    from src.force_inflow import compute_force_inflow

    base_close = np.r_[np.linspace(120, 90, 80), np.linspace(90, 96, 80)]
    base_volume = np.r_[np.full(80, 1000), np.tile([2800, 900, 2600, 850], 20)]
    top_close = np.r_[np.linspace(60, 120, 140), np.linspace(114, 118, 19), 117]
    top_volume = np.r_[np.full(140, 1200), np.full(19, 1500), 4200]

    config = {"force_inflow": {"prefer_real_data": False, "window_days": 20}}
    base = compute_force_inflow("BASE", _ohlcv(base_close, base_volume), config)
    top = compute_force_inflow("TOP", _ohlcv(top_close, top_volume), config)

    assert base["force_position"] in {"base", "neutral"}
    assert top["force_position"] in {"top", "overheated"}
    assert base["force_inflow_pct"] > top["force_inflow_pct"]
    assert top["force_penalty"] > 0


def test_composite_score_blends_adjusted_score_and_force_score():
    from src.force_inflow import add_composite_score

    row = {"adjusted_score": 80, "final_score": 70, "force_inflow_pct": 50}
    config = {"composite": {"enabled": True, "mode": "blend", "w_chart": 0.6, "w_force": 0.4}}

    result = add_composite_score(row, config)

    assert result["chart_score"] == 80
    assert result["composite_score"] == 68
    assert result["composite_source"] == "blend"


def test_kr_real_force_inflow_uses_flow_chain(monkeypatch, tmp_path):
    import src.force_inflow as force

    monkeypatch.setattr(force, "FLOW_CACHE_DIR", tmp_path)
    monkeypatch.setattr(force, "FLOW_SOURCE_STATE", tmp_path / "_source.json")

    def fake_fetch(ticker, trade_date, window, config=None):
        dates = pd.date_range("2025-03-03", periods=20, freq="B")
        return (
            pd.DataFrame(
                {
                    "date": dates,
                    "foreign": np.full(20, 10_000_000.0),
                    "inst": np.full(20, 7_000_000.0),
                    "retail": np.full(20, -4_000_000.0),
                    "close": np.full(20, 10_000.0),
                    "source": "pykrx",
                }
            ),
            [],
        )

    monkeypatch.setattr(force, "_fetch_real_flow_chain", fake_fetch)
    result = force.compute_force_inflow(
        "005930.KS",
        _ohlcv(np.linspace(90000, 95000, 80), np.full(80, 1_000_000)),
        {"market": {"region": "kr"}, "force_inflow": {"prefer_real_data": True, "window_days": 20}},
    )

    assert result["force_inflow_source"] == "real"
    assert result["force_flow_source"] == "pykrx"
    assert result["fi_foreign_streak"] == 20


def test_kr_real_force_inflow_falls_back_to_proxy(monkeypatch, tmp_path):
    import src.force_inflow as force

    monkeypatch.setattr(force, "FLOW_CACHE_DIR", tmp_path)
    monkeypatch.setattr(force, "FLOW_SOURCE_STATE", tmp_path / "_source.json")
    monkeypatch.setattr(force, "_fetch_real_flow_chain", lambda ticker, trade_date, window, config=None: (None, ["pykrx: 네트워크 차단"]))

    result = force.compute_force_inflow(
        "005930.KS",
        _ohlcv(np.linspace(90000, 95000, 80), np.full(80, 1_000_000)),
        {"market": {"region": "kr"}, "force_inflow": {"prefer_real_data": True, "window_days": 20}},
    )

    assert result["force_inflow_source"] == "proxy"
