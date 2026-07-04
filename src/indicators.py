"""Technical indicator calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _last(series: pd.Series, default: float = np.nan) -> float:
    series = series.dropna()
    return float(series.iloc[-1]) if not series.empty else default


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI using Wilder's smoothing."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50).clip(0, 100)


def calculate_macd(close: pd.Series) -> pd.DataFrame:
    """Calculate MACD, signal, and histogram."""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return pd.DataFrame({"macd": macd, "macd_signal": signal, "macd_hist": hist})


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range."""
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def calculate_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Calculate On-Balance Volume."""
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume.fillna(0)).cumsum()


def calculate_cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Calculate Chaikin Money Flow."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    volume = df["Volume"].fillna(0)
    spread = (high - low).replace(0, np.nan)
    multiplier = (((close - low) - (high - close)) / spread).fillna(0)
    money_flow_volume = multiplier * volume
    return money_flow_volume.rolling(period).sum() / volume.rolling(period).sum().replace(0, np.nan)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return OHLCV data with moving averages and indicators."""
    out = df.copy()
    out["ma20"] = out["Close"].rolling(20).mean()
    out["ma50"] = out["Close"].rolling(50).mean()
    out["ma200"] = out["Close"].rolling(200).mean()
    out["rsi14"] = calculate_rsi(out["Close"], 14)
    out = out.join(calculate_macd(out["Close"]))
    out["atr14"] = calculate_atr(out, 14)
    out["volume_avg20"] = out["Volume"].rolling(20).mean()
    out["obv"] = calculate_obv(out["Close"], out["Volume"])
    out["cmf20"] = calculate_cmf(out, 20)
    return out


def build_indicator_snapshot(df: pd.DataFrame) -> dict:
    """Build the latest indicator snapshot used by scoring."""
    enriched = add_indicators(df)
    latest = enriched.iloc[-1]
    prev = enriched.iloc[-2] if len(enriched) > 1 else latest
    close = enriched["Close"]
    volume_avg20 = float(latest.get("volume_avg20", np.nan))
    volume = float(latest["Volume"])
    current = float(latest["Close"])
    atr14 = float(latest.get("atr14", np.nan))
    snapshot = {
        "current_price": current,
        "previous_close": float(prev["Close"]),
        "return_1d": (current / float(prev["Close"]) - 1) * 100 if prev["Close"] else 0.0,
        "return_5d": (current / float(close.iloc[-6]) - 1) * 100 if len(close) > 5 else 0.0,
        "return_20d": (current / float(close.iloc[-21]) - 1) * 100 if len(close) > 20 else 0.0,
        "ma20": _last(enriched["ma20"]),
        "ma50": _last(enriched["ma50"]),
        "ma200": _last(enriched["ma200"]),
        "rsi14": float(latest["rsi14"]),
        "macd": float(latest["macd"]),
        "macd_signal": float(latest["macd_signal"]),
        "macd_hist": float(latest["macd_hist"]),
        "macd_hist_prev": float(prev["macd_hist"]),
        "atr14": atr14,
        "atr_pct": atr14 / current * 100 if current and not np.isnan(atr14) else np.nan,
        "volume": volume,
        "volume_avg20": volume_avg20,
        "volume_ratio": volume / volume_avg20 if volume_avg20 else 0.0,
        "cmf20": _last(enriched["cmf20"]),
        "obv": _last(enriched["obv"]),
        "high20": float(close.tail(20).max()),
        "high60": float(close.tail(60).max()),
        "high252": float(close.tail(252).max()),
        "low20": float(close.tail(20).min()),
        "low60": float(close.tail(60).min()),
        "history": enriched,
    }
    return snapshot
