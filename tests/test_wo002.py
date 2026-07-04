
import pandas as pd


def test_kr_config_defaults_to_kospi_kosdaq():
    from src.market_config import load_config

    config = load_config("configs/config_kr.yaml")

    assert config["universe"]["mode"] == "kospi_kosdaq"
    assert config["sector_filter"]["enabled"] is False


def test_attach_sectors_and_sector_filter(monkeypatch):
    from src import sector_loader
    from src.sector_loader import attach_sectors, apply_sector_filter

    monkeypatch.setattr(
        sector_loader,
        "build_kr_sector_map",
        lambda force_refresh=False, refresh_days=7: pd.DataFrame(
            [
                {"ticker": "005930", "ticker_base": "005930", "sector": "???", "industry": "?????????", "sector_source": "test", "updated_at": "now"},
                {"ticker": "068270", "ticker_base": "068270", "sector": "??????", "industry": "??", "sector_source": "test", "updated_at": "now"},
            ]
        ),
    )
    universe = pd.DataFrame(
        [
            {"ticker": "005930.KS", "name": "????", "market": "KOSPI", "sector": ""},
            {"ticker": "068270.KS", "name": "????", "market": "KOSPI", "sector": ""},
        ]
    )
    config = {"sector_filter": {"enabled": True, "include": ["???"], "refresh_days": 7}}

    attached = attach_sectors(universe, config)
    filtered = apply_sector_filter(attached, config)

    assert attached.set_index("ticker").loc["005930.KS", "sector"] == "???"
    assert filtered["ticker"].tolist() == ["005930.KS"]
    assert filtered["sector"].unique().tolist() == ["???"]
