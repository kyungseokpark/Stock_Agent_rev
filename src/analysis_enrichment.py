"""Additional analysis fields for StockAgent outputs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .data_loader import fetch_ohlcv


def _num(value, default: float = 0.0) -> float:
    try:
        value = float(value)
        if pd.isna(value):
            return default
        return value
    except (TypeError, ValueError):
        return default


def _pct(numerator: float, denominator: float) -> float:
    return round((numerator / denominator - 1) * 100, 2) if denominator else 0.0


def calculate_market_regime(market_region: str) -> dict:
    tickers = ["SPY", "QQQ"] if market_region == "us" else ["^KS11", "^KQ11"]
    frames = []
    for ticker in tickers:
        try:
            df = fetch_ohlcv(ticker, period="1y", interval="1d")
            if len(df) >= 80:
                frames.append(df)
        except Exception:
            continue
    if not frames:
        return {
            "market_regime": "데이터 없음",
            "market_comment": "시장 분위기 데이터를 가져오지 못했습니다.",
            "market_return_5d": 0.0,
            "market_above_ma20": False,
            "market_above_ma60": False,
            "market_above_ma200": False,
        }

    metrics = []
    for df in frames:
        close = pd.to_numeric(df["Close"], errors="coerce").dropna()
        last_close = float(close.iloc[-1])
        ma20 = float(close.tail(20).mean())
        ma60 = float(close.tail(60).mean())
        ma200 = float(close.tail(200).mean()) if len(close) >= 200 else float(close.mean())
        return_5d = _pct(last_close, float(close.iloc[-6])) if len(close) > 5 else 0.0
        metrics.append(
            {
                "return_5d": return_5d,
                "above_ma20": last_close > ma20,
                "above_ma60": last_close > ma60,
                "above_ma200": last_close > ma200,
            }
        )

    avg_return_5d = round(sum(item["return_5d"] for item in metrics) / len(metrics), 2)
    above_ma20 = sum(item["above_ma20"] for item in metrics) >= 1
    above_ma60 = sum(item["above_ma60"] for item in metrics) >= 1
    above_ma200 = sum(item["above_ma200"] for item in metrics) >= 1

    if above_ma20 and above_ma60 and avg_return_5d > 0:
        regime = "상승 우위"
        comment = "주요 지수가 단기 이동평균선 위에 있어 시장 분위기는 우호적입니다."
    elif not above_ma20 and not above_ma60 and avg_return_5d < -3:
        regime = "강한 하락"
        comment = "주요 지수가 단기 이동평균선을 밑돌고 최근 하락폭이 커 방어적으로 접근해야 합니다."
    elif not above_ma20 and avg_return_5d < 0:
        regime = "하락 주의"
        comment = "주요 지수의 단기 흐름이 약해 신규 진입은 보수적으로 판단해야 합니다."
    else:
        regime = "혼조"
        comment = "시장 방향성이 뚜렷하지 않아 종목별 선별이 중요합니다."

    return {
        "market_regime": regime,
        "market_comment": comment,
        "market_return_5d": avg_return_5d,
        "market_above_ma20": above_ma20,
        "market_above_ma60": above_ma60,
        "market_above_ma200": above_ma200,
    }


def calculate_chase_risk(snapshot: dict) -> dict:
    history = snapshot.get("history")
    current = _num(snapshot.get("current_price"))
    ma20 = _num(snapshot.get("ma20"))
    ma60 = _num(snapshot.get("ma50"))
    rsi = _num(snapshot.get("rsi14"), 50)
    prev_close = _num(snapshot.get("previous_close"))
    last_open = 0.0
    if isinstance(history, pd.DataFrame) and not history.empty and "Open" in history.columns:
        last_open = _num(history.iloc[-1].get("Open"))
    last_close = current
    last_day_return = _pct(last_close, prev_close) if prev_close else _num(snapshot.get("return_1d"))
    open_gap = _pct(last_open, prev_close) if prev_close and last_open else 0.0
    intraday_return = _pct(last_close, last_open) if last_open else 0.0
    distance_from_ma20 = _pct(last_close, ma20) if ma20 else 0.0
    distance_from_ma60 = _pct(last_close, ma60) if ma60 else 0.0

    warnings = []
    if last_day_return > 5:
        warnings.append("최근 하루 상승폭이 커서 바로 따라 사는 것은 위험할 수 있습니다.")
    if open_gap > 3:
        warnings.append("갭상승 출발 이력이 있어 추격 진입에 주의가 필요합니다.")
    if distance_from_ma20 > 10:
        warnings.append("20일 이동평균선보다 많이 위에 있어 단기 과열 가능성이 있습니다.")
    if rsi > 70:
        warnings.append("RSI가 높아 단기 과열 구간일 수 있습니다.")

    return {
        "prev_close": round(prev_close, 2),
        "last_open": round(last_open, 2),
        "last_close": round(last_close, 2),
        "last_day_return": round(last_day_return, 2),
        "open_gap": round(open_gap, 2),
        "intraday_return": round(intraday_return, 2),
        "distance_from_ma20": round(distance_from_ma20, 2),
        "distance_from_ma60": round(distance_from_ma60, 2),
        "chase_risk_warning": " ".join(warnings),
    }


def risk_reward_status(risk_reward: float) -> dict:
    rr = _num(risk_reward)
    if rr < 1.0:
        return {
            "risk_reward_status_code": "poor",
            "risk_reward_status_label": "부적합",
            "risk_reward_message": "기대 수익보다 손실 위험이 더 큽니다.",
            "risk_reward_detail": "손익비가 1.0 미만이라 후보 적합성이 낮습니다.",
        }
    if rr < 1.5:
        return {
            "risk_reward_status_code": "low",
            "risk_reward_status_label": "낮음",
            "risk_reward_message": "손익비가 낮습니다. 기대 수익 대비 손절 위험이 큰 편입니다.",
            "risk_reward_detail": "후보에는 남길 수 있지만 보수적인 접근이 필요합니다.",
        }
    if rr < 2.0:
        return {
            "risk_reward_status_code": "normal",
            "risk_reward_status_label": "무난",
            "risk_reward_message": "손익비는 무난한 편입니다.",
            "risk_reward_detail": "목표가와 손절가의 균형이 보통 수준입니다.",
        }
    return {
        "risk_reward_status_code": "good",
        "risk_reward_status_label": "양호",
        "risk_reward_message": "목표 수익 대비 손실 위험이 상대적으로 작습니다.",
        "risk_reward_detail": "손익비 기준으로는 우호적인 후보입니다.",
    }


def enrich_recommendation_text(row: dict) -> dict:
    reasons = []
    cautions = []
    if _num(row.get("volume_ratio")) >= 1:
        reasons.append("거래량이 충분합니다.")
    rsi = _num(row.get("rsi14"), 50)
    if 45 <= rsi <= 65:
        reasons.append("RSI가 과열 구간은 아닙니다.")
    if _num(row.get("risk_reward")) >= 1.5:
        reasons.append("손절가 대비 목표가의 손익비가 양호합니다.")
    if _num(row.get("current_price")) > _num(row.get("ma20")) > 0:
        reasons.append("현재가가 20일선 위에 있어 단기 추세가 양호합니다.")

    for key in ["risk_reward_message", "chase_risk_warning", "sector_concentration_warning", "consecutive_recommendation_comment"]:
        value = str(row.get(key, "") or "").strip()
        if value:
            cautions.append(value)

    return {
        "selection_reason": " ".join(reasons) or "기술적 지표 기준으로 관찰할 만한 후보입니다.",
        "caution": " ".join(cautions),
    }


def add_sector_concentration(full_df: pd.DataFrame, top5_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if full_df.empty or top5_df.empty:
        return full_df, top5_df
    sector_col = next((col for col in ["sector", "Sector", "업종", "industry"] if col in top5_df.columns), None)
    if sector_col is None:
        full_df["sector"] = full_df.get("sector", "Unknown")
        top5_df["sector"] = top5_df.get("sector", "Unknown")
        sector_col = "sector"

    counts = top5_df[sector_col].fillna("Unknown").astype(str).replace("", "Unknown").value_counts().to_dict()

    def warning(sector: str) -> str:
        count = int(counts.get(str(sector) or "Unknown", 0))
        if count >= 5:
            return f"오늘 후보가 {sector} 섹터에 모두 몰려 있습니다."
        if count >= 4:
            return f"오늘 후보가 {sector} 섹터에 강하게 몰려 있습니다."
        if count >= 3:
            return f"오늘 후보가 {sector} 섹터에 많이 몰려 있습니다."
        return ""

    for df in [full_df, top5_df]:
        df["sector_count_in_top5"] = df[sector_col].fillna("Unknown").astype(str).map(lambda value: int(counts.get(value or "Unknown", 0)))
        df["sector_concentration_warning"] = df[sector_col].fillna("Unknown").astype(str).map(warning)
    return full_df, top5_df


def add_consecutive_recommendations(df: pd.DataFrame, market_region: str) -> pd.DataFrame:
    out = df.copy()
    out["consecutive_recommendation_days"] = 0
    out["recommended_count_last_5_sessions"] = 0
    out["consecutive_recommendation_comment"] = ""
    path = Path("output/performance_tracking_kr.csv" if market_region == "kr" else "output/performance_tracking.csv")
    if not path.exists():
        return out
    try:
        hist = pd.read_csv(path, dtype={"ticker": str})
    except Exception:
        return out
    if hist.empty or "ticker" not in hist.columns:
        return out
    counts = hist["ticker"].astype(str).value_counts().to_dict()
    out["recommended_count_last_5_sessions"] = out["ticker"].astype(str).map(lambda value: min(int(counts.get(value, 0)), 5))
    out["consecutive_recommendation_days"] = out["recommended_count_last_5_sessions"].clip(upper=2)
    out["consecutive_recommendation_comment"] = out["recommended_count_last_5_sessions"].map(
        lambda count: f"최근 5거래일 중 {int(count)}회 추천된 종목입니다." if int(count) >= 2 else ""
    )
    return out


def write_market_summary(market: dict, output_dir: str = "output") -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([market]).to_csv(path / "market_summary.csv", index=False, encoding="utf-8-sig")
