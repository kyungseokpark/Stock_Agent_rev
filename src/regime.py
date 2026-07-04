"""Market regime gate shared by screening and backtesting."""

from __future__ import annotations

import pandas as pd


def classify_regime(index_df: pd.DataFrame | None) -> dict:
    if index_df is None or index_df.empty or "Close" not in index_df:
        return {"regime_state": "neutral", "regime_score": 0.5, "regime_message": "시장 레짐 데이터가 없습니다."}
    close = pd.to_numeric(index_df["Close"], errors="coerce").dropna()
    if len(close) < 60:
        return {"regime_state": "neutral", "regime_score": 0.5, "regime_message": "시장 레짐 이력이 부족합니다."}
    last = float(close.iloc[-1])
    ma20 = float(close.tail(20).mean())
    ma50 = float(close.tail(50).mean())
    has_ma200 = len(close) >= 200
    ma200 = float(close.tail(200).mean()) if has_ma200 else None
    ma50_prev = float(close.iloc[:-20].tail(50).mean()) if len(close) >= 80 else ma50
    ret10 = float(close.iloc[-1] / close.iloc[-11] - 1) if len(close) > 11 else 0.0
    drawdown = last / float(close.tail(20).max()) - 1
    short_break = (last < ma20) or (ret10 <= -0.05) or (drawdown <= -0.07)
    if has_ma200 and ma200 is not None and last > ma200 and ma50 > ma50_prev and not short_break:
        return {"regime_state": "risk_on", "regime_score": 1.0, "regime_message": "주요 지수가 장기 추세 위에 있어 롱 후보를 활성화합니다."}
    if ((has_ma200 and ma200 is not None and last < ma200 and ma50 < ma50_prev) or (short_break and last < ma50)):
        return {"regime_state": "risk_off", "regime_score": 0.0, "regime_message": "주요 지수의 장기 추세가 약해 롱 후보를 축소합니다."}
    return {"regime_state": "neutral", "regime_score": 0.5, "regime_message": "시장 방향이 혼조여서 선별적으로 접근합니다."}


def regime_from_market_summary(summary: dict | None) -> dict:
    summary = summary or {}
    label = str(summary.get("market_regime", ""))
    if label in {"상승 우위", "risk_on"}:
        state = "risk_on"
    elif label in {"강한 하락", "하락 주의", "risk_off"}:
        state = "risk_off"
    else:
        state = "neutral"
    return {
        "regime_state": state,
        "regime_score": {"risk_on": 1.0, "neutral": 0.5, "risk_off": 0.0}[state],
        "regime_message": summary.get("market_comment", "시장 방향이 혼조입니다."),
    }
