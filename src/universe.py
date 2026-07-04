"""Universe loading, ticker normalization, and liquidity filters."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


MODE_LABELS = {
    "custom": "관심종목",
    "sp500": "S&P500",
    "nasdaq100": "Nasdaq100",
    "sp500_nasdaq100": "S&P500 + Nasdaq100",
    "combined": "관심종목 + S&P500 + Nasdaq100",
    "all_us": "미국장 전체 CSV",
}


def normalize_ticker(ticker: str) -> str:
    """Normalize symbols for yfinance compatibility."""
    return str(ticker).strip().upper().replace(".", "-")


def _empty_universe() -> pd.DataFrame:
    return pd.DataFrame(columns=["ticker", "name", "market", "sector", "source"])


def read_universe_csv(path: str, source: str) -> pd.DataFrame:
    """Read a flexible universe CSV. Only ticker is required."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(str(file_path))
    df = pd.read_csv(file_path)
    if "ticker" not in df.columns:
        raise ValueError(f"{path} must contain a ticker column")

    out = pd.DataFrame()
    out["ticker"] = df["ticker"].map(normalize_ticker)
    out["name"] = df["name"] if "name" in df.columns else out["ticker"]
    out["market"] = df["market"] if "market" in df.columns else "US"
    out["sector"] = df["sector"] if "sector" in df.columns else ""
    out["source"] = df["source"] if "source" in df.columns else source
    out["source"] = out["source"].fillna(source).replace("", source)
    out = out.dropna(subset=["ticker"])
    out = out[out["ticker"].astype(str).str.len() > 0]
    return out[["ticker", "name", "market", "sector", "source"]]


def merge_universes(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge universes, deduplicating tickers and joining source labels."""
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        return _empty_universe()

    df = pd.concat(frames, ignore_index=True)
    df["ticker"] = df["ticker"].map(normalize_ticker)

    def first_non_empty(series: pd.Series) -> str:
        for value in series:
            if pd.notna(value) and str(value).strip():
                return str(value).strip()
        return ""

    merged = (
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
    merged["name"] = merged["name"].where(merged["name"].astype(str).str.len() > 0, merged["ticker"])
    merged["market"] = merged["market"].where(merged["market"].astype(str).str.len() > 0, "US")
    return merged[["ticker", "name", "market", "sector", "source"]]


def load_universe(config: dict, tickers_override: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Load the configured universe and return metadata stats."""
    universe_cfg = config.get("universe", {})
    mode = universe_cfg.get("mode", "custom")
    custom_file = tickers_override or universe_cfg.get("custom_file", "tickers.csv")
    sp500_file = universe_cfg.get("sp500_file", "data/universe_sp500.csv")
    nasdaq100_file = universe_cfg.get("nasdaq100_file", "data/universe_nasdaq100.csv")
    all_us_file = universe_cfg.get("all_us_file", "data/universe_all_us.csv")
    combined_file = universe_cfg.get("combined_file", "data/universe_combined.csv")

    frames: list[pd.DataFrame]
    if mode == "custom":
        frames = [read_universe_csv(custom_file, "custom")]
    elif mode == "sp500":
        frames = [read_universe_csv(sp500_file, "sp500")]
    elif mode == "nasdaq100":
        frames = [read_universe_csv(nasdaq100_file, "nasdaq100")]
    elif mode == "sp500_nasdaq100":
        frames = [read_universe_csv(sp500_file, "sp500"), read_universe_csv(nasdaq100_file, "nasdaq100")]
    elif mode == "combined":
        combined_path = Path(combined_file)
        if combined_path.exists():
            frames = [read_universe_csv(combined_file, "combined")]
        else:
            frames = [
                read_universe_csv(custom_file, "custom"),
                read_universe_csv(sp500_file, "sp500"),
                read_universe_csv(nasdaq100_file, "nasdaq100"),
            ]
    elif mode == "all_us":
        if not Path(all_us_file).exists():
            raise FileNotFoundError("data/universe_all_us.csv 파일이 없습니다. all_us 모드를 사용하려면 해당 CSV를 먼저 생성해야 합니다.")
        frames = [read_universe_csv(all_us_file, "all_us")]
    else:
        raise ValueError(f"Unsupported universe mode: {mode}")

    raw_count = sum(len(frame) for frame in frames)
    universe = merge_universes(frames)
    stats = {
        "universe_mode": mode,
        "universe_label": MODE_LABELS.get(mode, mode),
        "raw_tickers_loaded": raw_count,
        "unique_tickers": len(universe),
        "passed_liquidity_filter": 0,
        "selected_top_candidates": 0,
    }
    return universe, stats


def passes_liquidity_filter(df: pd.DataFrame, config: dict) -> bool:
    """Apply liquidity filters to downloaded OHLCV data."""
    filters = config.get("filters", {})
    min_price = float(filters.get("min_price", 5))
    min_dollar_volume = float(filters.get("min_avg_dollar_volume_20d", 20_000_000))
    min_history_days = int(filters.get("min_history_days", 60))

    if df is None or df.empty or len(df) < min_history_days:
        return False
    if "Volume" not in df.columns or "Close" not in df.columns:
        return False
    latest_close = float(df["Close"].iloc[-1])
    if latest_close < min_price:
        return False
    volume = pd.to_numeric(df["Volume"], errors="coerce")
    close = pd.to_numeric(df["Close"], errors="coerce")
    if volume.tail(20).isna().any() or (volume.tail(20) <= 0).any():
        return False
    avg_dollar_volume = (close.tail(20) * volume.tail(20)).mean()
    return bool(avg_dollar_volume >= min_dollar_volume)
