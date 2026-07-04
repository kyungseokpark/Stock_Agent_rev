"""Ticker loading and OHLCV collection."""

from __future__ import annotations

import logging
import json
from hashlib import sha256
from pathlib import Path
from datetime import date

import numpy as np
import pandas as pd

from .data_quality import normalize_ohlcv

LOGGER = logging.getLogger(__name__)
REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
DEFAULT_CACHE_DIR = Path("data/cache/ohlcv")


def load_tickers(path: str | Path) -> pd.DataFrame:
    """Read a ticker universe CSV."""
    if path is None:
        raise ValueError("티커 CSV 경로가 없습니다. config 또는 universe 파일 경로를 확인하세요.")
    if not isinstance(path, (str, Path)):
        raise TypeError(
            "load_tickers()는 CSV 경로(str 또는 Path)를 받아야 합니다. "
            f"현재 전달된 값: {path} / 타입: {type(path)}"
        )
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"티커 CSV 파일을 찾을 수 없습니다: {path}")

    df = pd.read_csv(path, dtype={"ticker": str})
    required = {"ticker"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"{path} 파일에 필수 컬럼이 없습니다: {sorted(missing)}")
    for column in ["name", "market", "sector"]:
        if column not in df.columns:
            df[column] = ""
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    return df.dropna(subset=["ticker"]).drop_duplicates("ticker")


def _normalize_yfinance_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    if "Adj Close" not in df.columns and "Close" in df.columns:
        df["Adj Close"] = df["Close"]
    available = [col for col in REQUIRED_COLUMNS if col in df.columns]
    return df[available].dropna(subset=["Open", "High", "Low", "Close"])


def _safe_cache_key(ticker: str) -> str:
    return str(ticker).strip().upper().replace("/", "-").replace("\\", "-")


def _cache_paths(ticker: str, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> tuple[Path, Path]:
    base = Path(cache_dir)
    key = _safe_cache_key(ticker)
    return base / f"{key}.parquet", base / f"{key}.json"


def _today_key() -> str:
    return date.today().isoformat()


def _read_cache_meta(meta_path: Path) -> dict:
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _period_to_days(period: str) -> int | None:
    text = str(period).strip().lower()
    if text in {"max", "ytd"}:
        return None
    if text.endswith("mo"):
        try:
            return int(text[:-2]) * 31
        except (TypeError, ValueError):
            return None
    try:
        amount = int(text[:-1])
    except (TypeError, ValueError):
        return None
    unit = text[-1:]
    if unit == "d":
        return amount
    if unit == "mo":
        return amount * 31
    if unit == "y":
        return amount * 366
    return None


def _cache_period_covers(cached_period: str, requested_period: str) -> bool:
    cached_days = _period_to_days(cached_period)
    requested_days = _period_to_days(requested_period)
    if cached_days is None:
        return str(cached_period) == str(requested_period) or str(cached_period).lower() == "max"
    if requested_days is None:
        return False
    return cached_days >= requested_days


def _is_fresh_cache(meta: dict, *, period: str, interval: str) -> bool:
    return (
        meta.get("last_fetched") == _today_key()
        and _cache_period_covers(str(meta.get("period", "")), str(period))
        and meta.get("interval") == str(interval)
    )


def read_ohlcv_cache(
    ticker: str,
    *,
    period: str = "1y",
    interval: str = "1d",
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
) -> pd.DataFrame | None:
    data_path, meta_path = _cache_paths(ticker, cache_dir)
    if not data_path.exists():
        return None
    meta = _read_cache_meta(meta_path)
    if not _is_fresh_cache(meta, period=period, interval=interval):
        return None
    try:
        df = pd.read_parquet(data_path)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except Exception as exc:
        LOGGER.warning("Failed to read OHLCV cache for %s: %s", ticker, exc)
        return None


def write_ohlcv_cache(
    ticker: str,
    df: pd.DataFrame,
    *,
    period: str = "1y",
    interval: str = "1d",
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
) -> None:
    if df is None or df.empty:
        return
    data_path, meta_path = _cache_paths(ticker, cache_dir)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(data_path)
    meta = {
        "ticker": str(ticker),
        "last_fetched": _today_key(),
        "period": str(period),
        "interval": str(interval),
        "rows": int(len(df)),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_ticker_frame(batch_df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if batch_df is None or batch_df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    if not isinstance(batch_df.columns, pd.MultiIndex):
        return batch_df.copy()

    ticker_text = str(ticker)
    upper_ticker = ticker_text.upper()
    level0 = [str(value).upper() for value in batch_df.columns.get_level_values(0)]
    level1 = [str(value).upper() for value in batch_df.columns.get_level_values(1)]
    if upper_ticker in level0:
        actual = batch_df.columns.get_level_values(0)[level0.index(upper_ticker)]
        return batch_df.xs(actual, axis=1, level=0, drop_level=True)
    if upper_ticker in level1:
        actual = batch_df.columns.get_level_values(1)[level1.index(upper_ticker)]
        return batch_df.xs(actual, axis=1, level=1, drop_level=True)
    return pd.DataFrame(columns=REQUIRED_COLUMNS)


def fetch_ohlcv(ticker: str, period: str = "1y", interval: str = "1d", timeout: int | None = 600) -> pd.DataFrame:
    """Download OHLCV data with yfinance, returning an empty frame on failure."""
    try:
        import yfinance as yf
    except ImportError:
        LOGGER.warning("yfinance is not installed; cannot fetch %s", ticker)
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=timeout,
        )
        normalized = _normalize_yfinance_frame(df)
        cleaned, _ = normalize_ohlcv(normalized, apply_adjustment=False)
        return cleaned
    except Exception as exc:  # pragma: no cover - depends on network/provider
        LOGGER.warning("Failed to fetch %s: %s", ticker, exc)
        return pd.DataFrame(columns=REQUIRED_COLUMNS)


def fetch_ohlcv_batch(
    tickers: list[str],
    *,
    period: str = "1y",
    interval: str = "1d",
    timeout: int | None = 30,
    batch_size: int = 75,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Fetch OHLCV with a daily parquet cache and yfinance batch downloads."""
    try:
        import yfinance as yf
    except ImportError:
        LOGGER.warning("yfinance is not installed; cannot fetch ticker batch")
        return {}, {
            "cache_hits": 0,
            "cache_misses": len(tickers),
            "download_success": 0,
            "download_failed": len(tickers),
            "individual_retries": 0,
        }

    result: dict[str, pd.DataFrame] = {}
    stats = {
        "cache_hits": 0,
        "cache_misses": 0,
        "download_success": 0,
        "download_failed": 0,
        "individual_retries": 0,
    }
    missing: list[str] = []
    for ticker in tickers:
        cached = read_ohlcv_cache(ticker, period=period, interval=interval, cache_dir=cache_dir)
        if cached is not None and not cached.empty:
            result[ticker] = cached
            stats["cache_hits"] += 1
        else:
            missing.append(ticker)
            stats["cache_misses"] += 1

    total_missing = len(missing)
    for start in range(0, total_missing, batch_size):
        batch = missing[start : start + batch_size]
        LOGGER.info("Downloading OHLCV batch %s-%s/%s", start + 1, min(start + len(batch), total_missing), total_missing)
        failed: list[str] = []
        try:
            batch_df = yf.download(
                batch if len(batch) > 1 else batch[0],
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=True,
                timeout=timeout,
            )
            for ticker in batch:
                normalized = _normalize_yfinance_frame(_extract_ticker_frame(batch_df, ticker))
                cleaned, _ = normalize_ohlcv(normalized, apply_adjustment=False)
                if cleaned.empty:
                    failed.append(ticker)
                    continue
                result[ticker] = cleaned
                write_ohlcv_cache(ticker, cleaned, period=period, interval=interval, cache_dir=cache_dir)
                stats["download_success"] += 1
        except Exception as exc:  # pragma: no cover - depends on network/provider
            LOGGER.warning("Batch OHLCV download failed for %s tickers: %s", len(batch), exc)
            failed = list(batch)

        for ticker in failed:
            stats["individual_retries"] += 1
            df = fetch_ohlcv(ticker, period=period, interval=interval, timeout=timeout)
            if df.empty:
                stats["download_failed"] += 1
                continue
            result[ticker] = df
            write_ohlcv_cache(ticker, df, period=period, interval=interval, cache_dir=cache_dir)
            stats["download_success"] += 1

    return result, stats


def build_sample_ohlcv(ticker: str, rows: int = 260) -> pd.DataFrame:
    """Build deterministic sample daily bars for offline first-run validation."""
    seed = int(sha256(ticker.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=rows)
    base = 35 + (seed % 220)
    drift = rng.uniform(0.0002, 0.0016)
    volatility = rng.uniform(0.012, 0.028)
    returns = rng.normal(drift, volatility, rows)
    close = base * np.exp(np.cumsum(returns))
    open_ = close * (1 + rng.normal(0, 0.006, rows))
    high = np.maximum(open_, close) * (1 + rng.uniform(0.002, 0.025, rows))
    low = np.minimum(open_, close) * (1 - rng.uniform(0.002, 0.025, rows))
    volume = rng.integers(1_000_000, 30_000_000, rows)
    if rows > 30:
        volume[-5:] = (volume[-5:] * rng.uniform(1.05, 1.8)).astype(int)
    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Adj Close": close,
            "Volume": volume,
        },
        index=dates,
    )


def fetch_all_tickers(tickers: pd.DataFrame, config: dict) -> dict[str, pd.DataFrame]:
    """Fetch all ticker bars, skipping short series and optionally using sample fallback."""
    data_cfg = config.get("data", {})
    min_rows = int(data_cfg.get("min_rows", 120))
    use_fallback = bool(data_cfg.get("sample_fallback", True))
    result: dict[str, pd.DataFrame] = {}

    for ticker in tickers["ticker"]:
        df = fetch_ohlcv(
            ticker,
            period=data_cfg.get("period", "1y"),
            interval=data_cfg.get("interval", "1d"),
            timeout=int(data_cfg.get("request_timeout_seconds", 600)),
        )
        if len(df) < min_rows and use_fallback:
            LOGGER.warning("Using deterministic sample data for %s", ticker)
            df = build_sample_ohlcv(ticker, max(min_rows + 20, 260))
        if len(df) < min_rows:
            LOGGER.warning("Skipping %s: only %s rows", ticker, len(df))
            continue
        result[ticker] = df
    return result


def ensure_parent(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
