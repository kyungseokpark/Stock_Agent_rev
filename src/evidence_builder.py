"""선정 근거와 주의 요인 문장을 생성합니다."""

from __future__ import annotations


CHART_TYPE_LABELS = {
    "Pullback rebound": "눌림목 반등",
    "Breakout": "박스권 돌파",
    "Box breakout": "박스권 돌파",
    "MA20 recovery": "20일선 회복",
    "20MA rebound": "20일선 회복",
    "Near high": "신고가 근접",
    "Near new high": "신고가 근접",
    "Oversold rebound": "과매도 반등",
    "Relative strength": "상대강도 우위",
    "Relative strength leader": "상대강도 우위",
    "Watchlist pattern": "관찰 패턴",
    "Excluded pattern": "제외 패턴",
}


def korean_chart_type(chart_type: str) -> str:
    return CHART_TYPE_LABELS.get(chart_type, chart_type)


def build_evidence(snapshot: dict, score: dict, targets: dict, chart_type: str) -> dict:
    """기술적 지표 스냅샷을 사람이 읽기 쉬운 한국어 문장으로 변환합니다."""
    evidence = []
    risks = []
    cp = snapshot.get("current_price", 0)

    if cp > snapshot.get("ma20", 0) and cp > snapshot.get("ma50", 0):
        evidence.append("현재가가 20일선과 50일선 위에 있어 단기 추세가 양호합니다.")
    if snapshot.get("ma20", 0) > snapshot.get("ma50", 0):
        evidence.append("20일 이동평균선이 50일 이동평균선 위에 있어 상승 추세가 유지되고 있습니다.")
    if 45 <= snapshot.get("rsi14", 0) <= 65:
        evidence.append("RSI가 45~65 구간에 있어 과열 부담이 크지 않습니다.")
    if snapshot.get("volume_ratio", 0) >= 1.0:
        evidence.append("현재 거래량이 20일 평균 이상이거나 비슷한 수준이라 신호의 신뢰도를 보강합니다.")
    if snapshot.get("macd", 0) > snapshot.get("macd_signal", 0):
        evidence.append("MACD가 시그널선 위에 있어 모멘텀이 개선되고 있습니다.")
    if targets.get("risk_reward", 0) >= 1.5:
        evidence.append("손익비가 1.5 이상으로 단기 관찰 조건이 비교적 양호합니다.")

    if snapshot.get("rsi14", 0) >= 70:
        risks.append("RSI가 70 이상이라 단기 과열 가능성을 확인해야 합니다.")
    if snapshot.get("return_5d", 0) >= 10:
        risks.append("5일 수익률이 10% 이상이라 추격 매수 부담이 있습니다.")
    if snapshot.get("volume_ratio", 0) < 1.0:
        risks.append("거래량이 20일 평균보다 낮아 돌파 신뢰도가 약할 수 있습니다.")
    if cp < snapshot.get("ma20", 0):
        risks.append("현재가가 20일선 아래에 있어 단기 추세가 약합니다.")
    if targets.get("risk_reward", 0) < 1.2:
        risks.append("손익비가 1.2 미만이라 매매 조건의 질이 낮습니다.")
    if snapshot.get("atr_pct", 0) >= 7:
        risks.append("ATR 비율이 높아 변동성이 크고 손절 관리 부담이 있습니다.")

    if not evidence:
        evidence.append("현재 규칙 기준으로 뚜렷한 긍정적 기술 신호는 제한적입니다.")
    if not risks:
        risks.append("규칙 기반의 주요 위험 신호는 크지 않지만, 시장 상황과 뉴스 리스크는 별도 확인이 필요합니다.")

    chart_label = korean_chart_type(chart_type)
    return {
        "evidence_points": evidence,
        "risk_points": risks,
        "summary": f"{chart_label} 유형이며 점수는 {score.get('final_score', 0)}점, 손익비는 {targets.get('risk_reward', 0)}입니다.",
    }
