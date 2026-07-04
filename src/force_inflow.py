"""Force inflow and composite scoring helpers.

The real investor-flow lane is intentionally optional. When broker/exchange
flow data is unavailable, the screener falls back to OHLCV-derived proxy
signals so the output contract remains stable.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from io import StringIO

import numpy as np
import pandas as pd
import requests

from .indicators import add_indicators


FLOW_CACHE_DIR = Path("data/cache/flow")
FLOW_SOURCE_STATE = FLOW_CACHE_DIR / "_source.json"


def _num(value, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(value) else value


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _norm(value: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return max(0.0, min(1.0, value / denominator))


def _weighted_score(parts: dict[str, float], weights: dict[str, float]) -> float:
    available = {key: _num(parts.get(key)) for key in weights if key in parts}
    total_weight = sum(_num(weights.get(key)) for key in available)
    if total_weight <= 0:
        return 0.0
    return sum(available[key] * _num(weights.get(key)) for key in available) / total_weight * 100.0


def _default_proxy_weights() -> dict[str, float]:
    return {
        "cmf": 0.20,
        "obv": 0.16,
        "vol_asym": 0.18,
        "downvol_dry": 0.10,
        "accum_bars": 0.12,
        "vol_surge": 0.10,
        "box_breakout": 0.08,
        "sideways": 0.06,
    }


def _force_config(config: dict | None) -> dict:
    return (config or {}).get("force_inflow", {})


def _market_region(config: dict | None) -> str:
    return str((config or {}).get("market", {}).get("region", "")).lower()


def _ticker_base(ticker: str) -> str:
    return str(ticker).strip().upper().replace(".KS", "").replace(".KQ", "")


def _is_kr_ticker(ticker: str, config: dict | None) -> bool:
    if _market_region(config) == "kr":
        return True
    value = str(ticker).strip().upper()
    return value.endswith(".KS") or value.endswith(".KQ")


def _last_trade_date(ohlcv_df: pd.DataFrame | None = None) -> pd.Timestamp:
    if ohlcv_df is not None and not ohlcv_df.empty:
        idx = pd.to_datetime(ohlcv_df.index, errors="coerce")
        idx = idx[~pd.isna(idx)]
        if len(idx):
            return pd.Timestamp(idx[-1]).normalize()
    today = pd.Timestamp.today().normalize()
    return today - pd.offsets.BDay(1) if today.weekday() >= 5 else today


def _load_source_state() -> dict:
    if not FLOW_SOURCE_STATE.exists():
        return {}
    try:
        return json.loads(FLOW_SOURCE_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_source_state(source_name: str) -> None:
    FLOW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FLOW_SOURCE_STATE.write_text(
        json.dumps({"preferred_source": source_name, "updated_at": pd.Timestamp.now().isoformat()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _source_order() -> list[str]:
    preferred = _load_source_state().get("preferred_source")
    sources = ["pykrx", "naver", "krx"]
    if preferred in sources:
        return [preferred] + [source for source in sources if source != preferred]
    return sources


def _flow_cache_path(ticker: str) -> Path:
    return FLOW_CACHE_DIR / f"{_ticker_base(ticker)}.parquet"


def _read_cached_flow(ticker: str, trade_date: pd.Timestamp, window: int) -> pd.DataFrame | None:
    path = _flow_cache_path(ticker)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        if "date" not in df.columns:
            return None
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date")
        if df.empty or df["date"].max().normalize() < trade_date.normalize():
            return None
        return df.tail(max(window, 5)).copy()
    except Exception:
        return None


def _write_cached_flow(ticker: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    FLOW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_flow_cache_path(ticker), index=False)


def _normalize_flow_frame(df: pd.DataFrame, source: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "date" not in out.columns:
        out = out.reset_index().rename(columns={"index": "date"})
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for col in ["foreign", "inst", "retail", "close"]:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    out["source"] = source
    out = out.dropna(subset=["date"]).sort_values("date")
    return out[["date", "foreign", "inst", "retail", "close", "source"]]


def _fetch_flow_pykrx(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    try:
        from pykrx import stock
    except Exception as exc:
        raise RuntimeError("pykrx 미설치") from exc

    code = _ticker_base(ticker)
    raw = stock.get_market_trading_value_by_date(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
    if raw is None or raw.empty:
        raise RuntimeError("pykrx 응답 없음")
    raw = raw.reset_index().rename(columns={"날짜": "date"})
    cols = {str(col): col for col in raw.columns}
    foreign_col = cols.get("외국인합계") or cols.get("외국인")
    inst_col = cols.get("기관합계") or cols.get("기관")
    retail_col = cols.get("개인")
    if not foreign_col or not inst_col:
        raise RuntimeError("pykrx 응답 파싱 실패")
    return _normalize_flow_frame(
        pd.DataFrame(
            {
                "date": raw["date"],
                "foreign": raw[foreign_col],
                "inst": raw[inst_col],
                "retail": raw[retail_col] if retail_col else 0.0,
            }
        ),
        "pykrx",
    )


def _fetch_flow_naver(ticker: str, start: pd.Timestamp, end: pd.Timestamp, max_pages: int = 1) -> pd.DataFrame:
    code = _ticker_base(ticker)
    rows = []
    for page in range(1, max(1, int(max_pages)) + 1):
        url = f"https://finance.naver.com/item/frgn.naver?code={code}&page={page}"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text))
        if not tables:
            continue
        table = max(tables, key=len).dropna(how="all")
        if table.empty:
            continue
        table.columns = [str(col).replace(" ", "") for col in table.columns]
        date_col = next((col for col in table.columns if "날짜" in col), None)
        close_col = next((col for col in table.columns if "종가" in col), None)
        inst_col = next((col for col in table.columns if "기관" in col), None)
        foreign_col = next((col for col in table.columns if "외국인" in col and "보유" not in col), None)
        if not date_col or not foreign_col:
            continue
        work = pd.DataFrame(
            {
                "date": pd.to_datetime(table[date_col], errors="coerce"),
                "foreign": pd.to_numeric(table[foreign_col], errors="coerce").fillna(0.0),
                "inst": pd.to_numeric(table[inst_col], errors="coerce").fillna(0.0) if inst_col else 0.0,
                "close": pd.to_numeric(table[close_col], errors="coerce").fillna(0.0) if close_col else 0.0,
            }
        )
        rows.append(work)
    if not rows:
        raise RuntimeError("네이버 응답 파싱 실패")
    df = pd.concat(rows, ignore_index=True).dropna(subset=["date"])
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    if df.empty:
        raise RuntimeError("네이버 수급 데이터 없음")
    if "close" in df.columns:
        df["foreign"] = df["foreign"] * df["close"]
        df["inst"] = df["inst"] * df["close"]
    return _normalize_flow_frame(df, "naver")


def _fetch_flow_krx(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    try:
        from pykrx import stock
    except Exception as exc:
        raise RuntimeError("KRX 직접 호출 준비 실패") from exc
    code = _ticker_base(ticker)
    raw = stock.get_market_trading_volume_by_date(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
    if raw is None or raw.empty:
        raise RuntimeError("KRX 응답 없음")
    raw = raw.reset_index().rename(columns={"날짜": "date"})
    cols = {str(col): col for col in raw.columns}
    foreign_col = cols.get("외국인합계") or cols.get("외국인")
    inst_col = cols.get("기관합계") or cols.get("기관")
    retail_col = cols.get("개인")
    if not foreign_col or not inst_col:
        raise RuntimeError("KRX 응답 파싱 실패")
    return _normalize_flow_frame(
        pd.DataFrame(
            {
                "date": raw["date"],
                "foreign": raw[foreign_col],
                "inst": raw[inst_col],
                "retail": raw[retail_col] if retail_col else 0.0,
            }
        ),
        "krx",
    )


def _fetch_real_flow_chain(ticker: str, trade_date: pd.Timestamp, window: int, config: dict | None = None) -> tuple[pd.DataFrame | None, list[str]]:
    start = trade_date - pd.Timedelta(days=max(window * 3, 45))
    failures: list[str] = []
    naver_pages = int(_force_config(config).get("real_naver_pages", 1))
    fetchers = {
        "pykrx": _fetch_flow_pykrx,
        "naver": lambda ticker, start, end: _fetch_flow_naver(ticker, start, end, naver_pages),
        "krx": _fetch_flow_krx,
    }
    for source in _source_order():
        try:
            df = fetchers[source](ticker, start, trade_date)
            if df is not None and not df.empty:
                _write_cached_flow(ticker, df)
                _save_source_state(source)
                return df.tail(max(window, 5)).copy(), failures
            failures.append(f"{source}: 데이터 없음")
        except Exception as exc:
            failures.append(f"{source}: {exc}")
    return None, failures


def _ensure_indicators(ohlcv_df: pd.DataFrame) -> pd.DataFrame:
    needed = {"ma20", "ma50", "ma200", "atr14", "volume_avg20", "obv", "cmf20"}
    if needed.issubset(set(ohlcv_df.columns)):
        return ohlcv_df.copy()
    return add_indicators(ohlcv_df)


def _recent_window(ohlcv_df: pd.DataFrame, window: int) -> pd.DataFrame:
    return _ensure_indicators(ohlcv_df).dropna(subset=["Close", "Volume"]).tail(max(window, 5)).copy()


def position_context(ohlcv_df: pd.DataFrame) -> dict:
    """Classify current price location and return the WO-003 multiplier."""
    df = _ensure_indicators(ohlcv_df).dropna(subset=["Close"]).copy()
    if df.empty:
        return {"force_position": "unknown", "position_multiplier": 1.0, "price_percentile_252": np.nan}

    latest = df.iloc[-1]
    close = _num(latest["Close"])
    history = df["Close"].tail(252)
    low = _num(history.min(), close)
    high = _num(history.max(), close)
    pctile = 0.5 if high <= low else (close - low) / (high - low)
    ma200 = _num(latest.get("ma200"))
    rsi = _num(latest.get("rsi14"), 50)
    return_5d = close / _num(df["Close"].iloc[-6], close) - 1 if len(df) > 5 else 0.0
    atr_pct = _num(latest.get("atr14")) / close * 100 if close else 0.0
    ma200_distance = close / ma200 - 1 if ma200 else 0.0

    label = "neutral"
    multiplier = 1.0
    if pctile <= 0.35 and ma200_distance >= -0.08 and atr_pct <= 6:
        label = "base"
        multiplier = 1.2
    elif return_5d >= 0.12 or rsi >= 75:
        label = "overheated"
        multiplier = 0.8
    if pctile >= 0.88 and return_5d > -0.03:
        label = "top"
        multiplier = 0.6

    return {
        "force_position": label,
        "position_multiplier": multiplier,
        "price_percentile_252": round(pctile * 100, 2),
    }


def _box_breakout_score(df: pd.DataFrame) -> float:
    if len(df) < 25:
        return 0.0
    prev = df.iloc[:-1].tail(20)
    latest = df.iloc[-1]
    resistance = _num(prev["High"].max())
    close = _num(latest["Close"])
    volume_ratio = _num(latest.get("Volume")) / _num(prev["Volume"].mean(), 1.0)
    if close > resistance and volume_ratio >= 1.2:
        return 1.0
    if close > resistance:
        return 0.3
    return 0.0


def _sideways_score(df: pd.DataFrame) -> float:
    if len(df) < 20:
        return 0.0
    recent = df.tail(20)
    close = _num(recent["Close"].iloc[-1])
    high = _num(recent["High"].max())
    low = _num(recent["Low"].min())
    atr_pct = _num(recent["atr14"].iloc[-1]) / close if close else 0.0
    range_pct = (high - low) / close if close else 1.0
    if range_pct <= 0.12 and atr_pct <= 0.04:
        return 1.0
    if range_pct <= 0.18:
        return 0.5
    return 0.0


def compute_force_inflow_proxy(ohlcv_df: pd.DataFrame, config: dict | None = None) -> dict:
    """Compute OHLCV proxy accumulation signals on a 0-100 scale."""
    cfg = _force_config(config)
    window = int(cfg.get("window_days", 20))
    df = _recent_window(ohlcv_df, max(window + 20, 40))
    if len(df) < 20:
        return {
            "force_inflow_pct": 0.0,
            "force_inflow_source": "proxy",
            "force_inflow_grade": "insufficient",
        }

    recent = df.tail(window)
    prev = df.iloc[: -window].tail(window)
    close_diff = recent["Close"].diff()
    up_days = recent[close_diff > 0]
    down_days = recent[close_diff < 0]

    cmf20 = _num(recent["cmf20"].iloc[-1])
    obv = df["obv"].tail(window)
    avg_vol = _num(recent["Volume"].mean(), 1.0)
    obv_slope = np.polyfit(np.arange(len(obv)), obv.to_numpy(dtype=float), 1)[0] / avg_vol if len(obv) >= 3 else 0.0
    up_vol = _num(up_days["Volume"].mean())
    down_vol = _num(down_days["Volume"].mean())
    vol_asym = up_vol / down_vol if down_vol else (1.0 if up_vol else 0.0)
    prev_down_vol = _num(prev[prev["Close"].diff() < 0]["Volume"].mean(), down_vol or 1.0)
    downvol_dry = 1 - (down_vol / prev_down_vol) if prev_down_vol else 0.0
    accumulation_bars = ((recent["Volume"] >= recent["volume_avg20"] * 1.5) & (recent["Close"].rank(pct=True) >= 0.60)).mean()
    vol_surge = _num(recent["Volume"].tail(5).mean()) / _num(prev["Volume"].mean(), _num(recent["Volume"].mean(), 1.0)) - 1

    parts = {
        "cmf": _norm(cmf20, 0.15),
        "obv": _norm(obv_slope, 0.5),
        "vol_asym": _norm(vol_asym - 1, 1.0),
        "downvol_dry": _norm(downvol_dry, 0.4),
        "accum_bars": _norm(float(accumulation_bars), 0.4),
        "vol_surge": _norm(vol_surge, 1.5),
        "box_breakout": _box_breakout_score(df),
        "sideways": _sideways_score(df),
    }
    raw = _weighted_score(parts, cfg.get("weights_proxy", _default_proxy_weights()))
    return {
        "force_inflow_pct": round(_clip(raw), 1),
        "force_inflow_source": "proxy",
        "force_inflow_grade": force_grade(raw),
        "fi_cmf20": round(cmf20, 4),
        "fi_obv_slope": round(obv_slope, 4),
        "fi_vol_asym": round(vol_asym, 4),
        "fi_accum_bar_ratio": round(float(accumulation_bars), 4),
        "fi_box_breakout": round(parts["box_breakout"], 2),
    }


def distribution_penalty(ohlcv_df: pd.DataFrame, position: dict, config: dict | None = None) -> float:
    cfg = _force_config(config)
    penalty_cfg = cfg.get(
        "penalty",
        {"top_bear_vol": 15, "fall_no_dry": 10, "top_upperwick": 8, "failed_breakout": 7, "close_below_open_vol": 5},
    )
    df = _recent_window(ohlcv_df, 30)
    if len(df) < 10:
        return 0.0
    latest = df.iloc[-1]
    recent = df.tail(10)
    volume_ratio = _num(latest["Volume"]) / _num(df["Volume"].tail(20).mean(), 1.0)
    close = _num(latest["Close"])
    open_ = _num(latest["Open"], close)
    high = _num(latest["High"], close)
    low = _num(latest["Low"], close)
    range_ = max(high - low, 1e-9)
    upper_wick = (high - max(open_, close)) / range_
    falling = close < _num(df["Close"].iloc[-2], close)
    high_position = position.get("force_position") in {"top", "overheated"}

    penalty = 0.0
    if high_position and falling and volume_ratio >= 2.0:
        penalty += _num(penalty_cfg.get("top_bear_vol", 15))
    if falling and volume_ratio >= 1.1:
        penalty += _num(penalty_cfg.get("fall_no_dry", 10))
    if high_position and upper_wick >= 0.45:
        penalty += _num(penalty_cfg.get("top_upperwick", 8))
    if _box_breakout_score(df.iloc[:-1]) > 0 and close < _num(df["High"].iloc[:-1].tail(20).max()):
        penalty += _num(penalty_cfg.get("failed_breakout", 7))
    if close < open_ and volume_ratio >= 1.2:
        penalty += _num(penalty_cfg.get("close_below_open_vol", 5))

    if position.get("force_position") == "base":
        penalty *= 0.5
    return round(min(40.0, penalty), 1)


def sequence_bonus(ohlcv_df: pd.DataFrame, config: dict | None = None) -> float:
    cfg = _force_config(config)
    per_stage = _num(cfg.get("sequence", {}).get("per_stage", 2.5), 2.5)
    max_bonus = _num(cfg.get("sequence", {}).get("max", 15), 15)
    df = _recent_window(ohlcv_df, 60)
    if len(df) < 30:
        return 0.0
    stages = 0
    first = df.iloc[:20]
    mid = df.iloc[20:40]
    last = df.iloc[-20:]
    if _sideways_score(first) >= 0.5:
        stages += 1
    if _num(mid["Volume"].mean()) > _num(first["Volume"].mean()):
        stages += 1
    mid_down = _num(mid[mid["Close"].diff() < 0]["Volume"].mean())
    last_down = _num(last[last["Close"].diff() < 0]["Volume"].mean())
    if last_down and mid_down and last_down < mid_down:
        stages += 1
    if _box_breakout_score(df.iloc[:-3]) > 0:
        stages += 1
    breakout_level = _num(df["High"].iloc[:-5].tail(20).max())
    if breakout_level and _num(last["Close"].iloc[-1]) >= breakout_level * 0.98:
        stages += 1
    if _num(last["Volume"].tail(3).mean()) < _num(last["Volume"].head(10).mean()):
        stages += 1
    return round(min(max_bonus, stages * per_stage), 1)


def force_grade(value: float) -> str:
    value = _num(value)
    if value >= 75:
        return "strong_inflow"
    if value >= 60:
        return "inflow"
    if value >= 40:
        return "neutral"
    if value >= 25:
        return "weak"
    return "outflow"


def compute_force_inflow_real(
    ticker: str,
    window: int,
    config: dict | None = None,
    ohlcv_df: pd.DataFrame | None = None,
) -> dict | None:
    """Compute KR investor-flow score from foreign/institution net buying."""
    if not _is_kr_ticker(ticker, config):
        return None

    trade_date = _last_trade_date(ohlcv_df)
    df = _read_cached_flow(ticker, trade_date, window)
    failures: list[str] = []
    if df is None or df.empty:
        df, failures = _fetch_real_flow_chain(ticker, trade_date, window, config)
    if df is None or df.empty:
        return None

    recent = df.tail(max(window, 5)).copy()
    total_abs = (recent["foreign"].abs() + recent["inst"].abs() + recent["retail"].abs()).replace(0, np.nan)
    foreign_net = recent["foreign"]
    inst_net = recent["inst"]
    retail_net = recent["retail"]
    total_trade = float(total_abs.sum(skipna=True) or 1.0)
    foreign_sum = float(foreign_net.sum())
    inst_sum = float(inst_net.sum())
    retail_sum = float(retail_net.sum())

    foreign_streak = 0
    for value in reversed(foreign_net.tolist()):
        if _num(value) > 0:
            foreign_streak += 1
        else:
            break
    inst_streak = 0
    for value in reversed(inst_net.tolist()):
        if _num(value) > 0:
            inst_streak += 1
        else:
            break
    first_half = recent.head(max(1, len(recent) // 2))
    second_half = recent.tail(max(1, len(recent) // 2))
    accel = float((second_half["foreign"].sum() + second_half["inst"].sum()) - (first_half["foreign"].sum() + first_half["inst"].sum()))

    parts = {
        "foreign": _norm(foreign_sum, total_trade * 0.15),
        "inst": _norm(inst_sum, total_trade * 0.12),
        "foreign_streak": _norm(foreign_streak, 7),
        "foreign_share": _norm(foreign_sum / total_trade, 0.12),
        "inst_streak": _norm(inst_streak, 5),
        "accel": _norm(accel, total_trade * 0.08),
        "retail_light": _norm(-retail_sum, total_trade * 0.12),
    }
    weights = _force_config(config).get(
        "weights_real",
        {"foreign": 0.24, "inst": 0.18, "foreign_streak": 0.13, "foreign_share": 0.13, "inst_streak": 0.08, "accel": 0.08, "retail_light": 0.08},
    )
    raw = _weighted_score(parts, weights)
    source_name = str(recent["source"].dropna().iloc[-1]) if "source" in recent and not recent["source"].dropna().empty else "real"
    return {
        "force_inflow_pct": round(_clip(raw), 1),
        "force_inflow_source": "real",
        "force_inflow_grade": force_grade(raw),
        "force_flow_source": source_name,
        "force_flow_date": trade_date.strftime("%Y-%m-%d"),
        "fi_foreign_pct": round(foreign_sum / total_trade * 100, 2),
        "fi_inst_pct": round(inst_sum / total_trade * 100, 2),
        "fi_foreign_streak": foreign_streak,
        "fi_retail_light": round(parts["retail_light"], 4),
    }


def compute_force_inflow(ticker: str, ohlcv_df: pd.DataFrame, config: dict | None = None) -> dict:
    cfg = _force_config(config)
    if not bool(cfg.get("enabled", True)):
        return {
            "force_inflow_pct": np.nan,
            "force_inflow_grade": "disabled",
            "force_inflow_source": "disabled",
            "force_position": "disabled",
            "force_penalty": 0.0,
            "force_sequence": 0.0,
        }

    window = int(cfg.get("window_days", 20))
    real = compute_force_inflow_real(ticker, window, config, ohlcv_df) if bool(cfg.get("prefer_real_data", True)) else None
    base = real or compute_force_inflow_proxy(ohlcv_df, config)
    source = base.get("force_inflow_source", "proxy")
    position = position_context(ohlcv_df)
    penalty = distribution_penalty(ohlcv_df, position, config)
    bonus = sequence_bonus(ohlcv_df, config)
    raw = _num(base.get("force_inflow_pct"))
    multiplier = _num(position.get("position_multiplier"), 1.0)
    final = _clip(raw * multiplier - penalty + bonus)
    result = {
        **base,
        **position,
        "force_inflow_pct": round(final, 1),
        "force_inflow_grade": force_grade(final),
        "force_inflow_source": source,
        "force_penalty": penalty,
        "force_sequence": bonus,
    }
    return result


def add_composite_score(row: dict, config: dict | None = None) -> dict:
    composite_cfg = (config or {}).get("composite", {})
    if not bool(composite_cfg.get("enabled", True)):
        return {"composite_score": row.get("adjusted_score", row.get("final_score")), "composite_source": "disabled"}

    chart_score = _num(row.get("adjusted_score", row.get("final_score")))
    force_score = row.get("force_inflow_pct")
    if pd.isna(force_score):
        return {"chart_score": round(chart_score, 1), "composite_score": round(chart_score, 1), "composite_source": "chart_only"}

    force_score = _num(force_score)
    if composite_cfg.get("mode", "blend") == "gate" and force_score < _num(composite_cfg.get("gate_min_force", 40), 40):
        return {
            "chart_score": round(chart_score, 1),
            "composite_score": round(chart_score * 0.8, 1),
            "composite_source": "gate_penalty",
        }

    w_chart = _num(composite_cfg.get("w_chart", 0.6), 0.6)
    w_force = _num(composite_cfg.get("w_force", 0.4), 0.4)
    total = max(w_chart + w_force, 0.01)
    composite = (chart_score * w_chart + force_score * w_force) / total
    return {
        "chart_score": round(chart_score, 1),
        "composite_score": round(_clip(composite), 1),
        "composite_source": "blend",
    }
