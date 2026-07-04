"""Shared US/KR universe loading and filtering helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .kr_universe_fallback import create_default_kr_universe_csv
from .sector_loader import attach_sectors, apply_sector_filter


UNIVERSE_LABELS = {
    ("us", "custom"): "\uad00\uc2ec\uc885\ubaa9",
    ("us", "sp500"): "\uc5d0\uc2a4\uc564\ud53c 500",
    ("us", "nasdaq100"): "\ub098\uc2a4\ub2e5 100",
    ("us", "sp500_nasdaq100"): "\uc5d0\uc2a4\uc564\ud53c 500 + \ub098\uc2a4\ub2e5 100",
    ("us", "combined"): "\uad00\uc2ec\uc885\ubaa9 + \uc5d0\uc2a4\uc564\ud53c 500 + \ub098\uc2a4\ub2e5 100",
    ("us", "all_us"): "\ubbf8\uad6d \uc804\uccb4 \ud30c\uc77c",
    ("kr", "custom_kr"): "\uad6d\ub0b4 \uad00\uc2ec\uc885\ubaa9",
    ("kr", "kospi"): "\ucf54\uc2a4\ud53c",
    ("kr", "kosdaq"): "\ucf54\uc2a4\ub2e5",
    ("kr", "kospi_kosdaq"): "\ucf54\uc2a4\ud53c + \ucf54\uc2a4\ub2e5",
    ("kr", "combined_kr"): "\uad6d\ub0b4 \uad00\uc2ec\uc885\ubaa9 + \ucf54\uc2a4\ud53c + \ucf54\uc2a4\ub2e5",
}


def normalize_us_ticker(ticker) -> str:
    return str(ticker).strip().upper().replace(".", "-")


def normalize_kr_ticker(ticker, market: str | None = None) -> str:
    raw = str(ticker).strip().upper()
    if not raw:
        return ""
    if raw.endswith(".KS") or raw.endswith(".KQ"):
        return raw
    digits = raw.zfill(6) if raw.isdigit() else raw
    market_upper = str(market or "").strip().upper()
    if len(digits) == 6 and digits.isdigit():
        if market_upper == "KOSDAQ":
            return f"{digits}.KQ"
        return f"{digits}.KS"
    return raw


def get_universe_label(region: str, mode: str) -> str:
    return UNIVERSE_LABELS.get((region, mode), mode)


def load_universe_file(path: str, source_name: str, region: str = "us") -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"{path} 파일이 없습니다.")
    df = pd.read_csv(file_path, dtype={"ticker": str})
    if "ticker" not in df.columns:
        raise ValueError(f"{path} 파일에 ticker 컬럼이 없습니다.")

    out = pd.DataFrame()
    market_series = df["market"] if "market" in df.columns else ("US" if region == "us" else "")
    if region == "kr":
        out["ticker"] = [normalize_kr_ticker(t, m) for t, m in zip(df["ticker"], market_series)]
    else:
        out["ticker"] = df["ticker"].map(normalize_us_ticker)
    out["name"] = df["name"] if "name" in df.columns else out["ticker"]
    out["market"] = market_series
    out["sector"] = df["sector"] if "sector" in df.columns else ""
    out["source"] = df["source"] if "source" in df.columns else source_name
    out["source"] = out["source"].fillna(source_name).replace("", source_name)
    out = out.dropna(subset=["ticker"])
    out = out[out["ticker"].astype(str).str.len() > 0]
    return out[["ticker", "name", "market", "sector", "source"]]


def merge_universes(list_of_dataframes: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [df for df in list_of_dataframes if df is not None and not df.empty]
    if not frames:
        return pd.DataFrame(columns=["ticker", "name", "market", "sector", "source"])
    df = pd.concat(frames, ignore_index=True)

    def first_non_empty(values: pd.Series) -> str:
        for value in values:
            if pd.notna(value) and str(value).strip():
                return str(value).strip()
        return ""

    return (
        df.groupby("ticker", as_index=False)
        .agg(
            name=("name", first_non_empty),
            market=("market", first_non_empty),
            sector=("sector", first_non_empty),
            source=("source", lambda values: ";".join(sorted({str(v).strip() for v in values if str(v).strip()}))),
        )
        .sort_values("ticker")
        .reset_index(drop=True)
    )


def load_universe(config: dict) -> tuple[pd.DataFrame, dict]:
    market_cfg = config.get("market", {})
    region = market_cfg.get("region", "us")
    universe_cfg = config.get("universe", {})
    mode = universe_cfg.get("mode", "custom" if region == "us" else "custom_kr")

    if region == "us":
        custom = universe_cfg.get("custom_file", "tickers.csv")
        sp500 = universe_cfg.get("sp500_file", "data/universe_sp500.csv")
        nasdaq100 = universe_cfg.get("nasdaq100_file", "data/universe_nasdaq100.csv")
        combined = universe_cfg.get("combined_file", "data/universe_us_combined.csv")
        all_us = universe_cfg.get("all_us_file", "data/universe_all_us.csv")
        if mode == "custom":
            frames = [load_universe_file(custom, "custom", region)]
        elif mode == "sp500":
            frames = [load_universe_file(sp500, "sp500", region)]
        elif mode == "nasdaq100":
            frames = [load_universe_file(nasdaq100, "nasdaq100", region)]
        elif mode == "sp500_nasdaq100":
            frames = [load_universe_file(sp500, "sp500", region), load_universe_file(nasdaq100, "nasdaq100", region)]
        elif mode == "combined":
            if Path(combined).exists():
                frames = [load_universe_file(combined, "combined", region)]
            else:
                frames = [load_universe_file(custom, "custom", region), load_universe_file(sp500, "sp500", region), load_universe_file(nasdaq100, "nasdaq100", region)]
        elif mode == "all_us":
            if not Path(all_us).exists():
                raise FileNotFoundError("data/universe_all_us.csv 파일이 없습니다. all_us 모드를 사용하려면 해당 CSV를 먼저 생성해야 합니다.")
            frames = [load_universe_file(all_us, "all_us", region)]
        else:
            raise ValueError(f"Unsupported US universe mode: {mode}")
    elif region == "kr":
        custom = universe_cfg.get("custom_file", "tickers_kr.csv")
        kospi = universe_cfg.get("kospi_file", "data/universe_kospi.csv")
        kosdaq = universe_cfg.get("kosdaq_file", "data/universe_kosdaq.csv")
        combined = universe_cfg.get("combined_file", "data/universe_kr_combined.csv")
        if mode == "custom_kr":
            frames = [load_universe_file(custom, "custom_kr", region)]
        elif mode == "kospi":
            frames = [load_universe_file(kospi, "코스피", region)]
        elif mode == "kosdaq":
            frames = [load_universe_file(kosdaq, "코스닥", region)]
        elif mode == "kospi_kosdaq":
            frames = [load_universe_file(kospi, "코스피", region), load_universe_file(kosdaq, "코스닥", region)]
        elif mode == "combined_kr":
            if not Path(combined).exists() and Path(combined).name == "universe_kr.csv":
                create_default_kr_universe_csv(combined)
            if Path(combined).exists():
                frames = [load_universe_file(combined, "combined_kr", region)]
            else:
                frames = [load_universe_file(custom, "custom_kr", region), load_universe_file(kospi, "코스피", region), load_universe_file(kosdaq, "코스닥", region)]
        else:
            raise ValueError(f"Unsupported KR universe mode: {mode}")
    else:
        raise ValueError(f"Unsupported market region: {region}")

    raw_count = sum(len(frame) for frame in frames)
    universe = merge_universes(frames)
    pre_sector_filter_count = len(universe)
    sector_filter_enabled = False
    selected_sectors: list[str] = []
    if region == "kr":
        universe = attach_sectors(universe, config)
        selected_sectors = [str(value) for value in config.get("sector_filter", {}).get("include", []) if str(value).strip()]
        sector_filter_enabled = bool(config.get("sector_filter", {}).get("enabled", False)) and bool(selected_sectors)
        universe = apply_sector_filter(universe, config)
    stats = {
        "market_region": region,
        "market_label": market_cfg.get("label", "미국장" if region == "us" else "한국장"),
        "currency": market_cfg.get("currency", "USD" if region == "us" else "KRW"),
        "universe_mode": mode,
        "universe_label": get_universe_label(region, mode),
        "raw_tickers_loaded": raw_count,
        "unique_tickers": len(universe),
        "pre_sector_filter_count": pre_sector_filter_count,
        "sector_filter_enabled": sector_filter_enabled,
        "selected_sectors": selected_sectors,
        "passed_liquidity_filter": 0,
        "selected_top_candidates": 0,
    }
    return universe, stats


def liquidity_metrics(df: pd.DataFrame, config: dict) -> dict:
    filters = config.get("filters", {})
    min_price = float(filters.get("min_price", 5))
    min_dollar_volume = float(filters.get("min_avg_dollar_volume_20d", 20_000_000))
    min_history_days = int(filters.get("min_history_days", 60))

    if df is None or df.empty:
        return {"passed": False, "reason": "데이터 없음", "avg_dollar_volume_20d": 0.0}
    if len(df) < min_history_days:
        return {"passed": False, "reason": f"{min_history_days}거래일 미만", "avg_dollar_volume_20d": 0.0}
    if "Close" not in df.columns or "Volume" not in df.columns:
        return {"passed": False, "reason": "가격/거래량 컬럼 없음", "avg_dollar_volume_20d": 0.0}

    close = pd.to_numeric(df["Close"], errors="coerce")
    volume = pd.to_numeric(df["Volume"], errors="coerce")
    latest_close = float(close.iloc[-1])
    avg_dollar_volume = float((close.tail(20) * volume.tail(20)).mean())
    reasons = []
    if latest_close < min_price:
        reasons.append(f"현재가 {min_price:g} 미만")
    if volume.tail(20).isna().any() or (volume.tail(20) <= 0).any():
        reasons.append("거래량 비정상")
    if avg_dollar_volume < min_dollar_volume:
        reasons.append("20일 평균 거래대금 부족")
    return {
        "passed": not reasons,
        "reason": "; ".join(reasons),
        "avg_dollar_volume_20d": round(avg_dollar_volume, 2),
    }

