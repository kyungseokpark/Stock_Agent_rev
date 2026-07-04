"""CSV, Telegram text, Claude Markdown, and mobile prompt builders."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

CHART_TYPE_LABELS = {
    "VCP breakout": "VCP 돌파 임박",
    "VCP base": "VCP 베이스 형성",
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

DECISION_LABELS = {
    "Strong Candidate": "강한 후보",
    "Candidate": "관심 후보",
    "Watchlist": "관찰 후보",
    "Excluded": "제외",
    "강한 후보": "강한 후보",
    "관심 후보": "관심 후보",
    "관찰 후보": "관찰 후보",
    "제외": "제외",
}

REASON_LABELS = {
    "weak trend": "추세 약화",
    "low volume": "거래량 부족",
    "low risk/reward": "손익비 부족",
    "overheated RSI": "RSI 과열",
    "invalid targets": "목표가 계산 불가",
    "ATR or current price is unavailable": "ATR 또는 현재가 부족",
    "score below threshold": "점수 기준 미달",
    "추세 약화": "추세 약화",
    "거래량 부족": "거래량 부족",
    "손익비 부족": "손익비 부족",
    "RSI 과열": "RSI 과열",
}


def _fmt(value, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return ""


def _chart(value) -> str:
    return CHART_TYPE_LABELS.get(str(value), str(value))


def _decision(value) -> str:
    return DECISION_LABELS.get(str(value), str(value))


def _reason(value) -> str:
    if not value:
        return "점수 기준 미달"
    parts = [part.strip() for part in str(value).split(";") if part.strip()]
    return "; ".join(REASON_LABELS.get(part, part) for part in parts) if parts else "점수 기준 미달"


def _first_points(value, limit: int = 2) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value[:limit]]
    return [str(value)] if value else []


def _stats(config: dict) -> dict:
    return config.get("_run_stats", {})


def _stats_markdown_lines(config: dict) -> list[str]:
    stats = _stats(config)
    if not stats:
        return []
    return [
        f"- 분석 대상: {stats.get('universe_label', stats.get('universe_mode', 'custom'))}",
        f"- 전체 로드 종목 수: {stats.get('raw_tickers_loaded', 0)}개",
        f"- 중복 제거 후 종목 수: {stats.get('unique_tickers', 0)}개",
        f"- 필터 통과 종목 수: {stats.get('passed_liquidity_filter', 0)}개",
        f"- 최종 후보 수: {stats.get('selected_top_candidates', 0)}개",
    ]


def build_report(full_df: pd.DataFrame, top5_df: pd.DataFrame, config: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    market_label = config.get("market", {}).get("label", "미국장")
    currency = config.get("market", {}).get("currency", "USD")
    lines = [
        f"# {market_label} 전일 차트 기반 Top 5 스크리닝 리포트",
        "",
        f"- 분석 시각: {now}",
        f"- 분석 대상 종목 수: {len(full_df)}",
        f"- 가격 기준 통화: {currency}",
        "- 목적: 기술적 지표 기반 후보를 선별하고 Claude 검수용 근거를 제공합니다.",
        "- 주의: 본 자료는 투자 조언이 아니며 자동매매나 주문 기능을 포함하지 않습니다.",
        "",
        "---",
        "",
        "## 1. 핵심 요약",
        "",
    ]
    stats_lines = _stats_markdown_lines(config)
    if stats_lines:
        lines.extend(stats_lines)
        lines.append("")
    lines.append(f"- 최종 Top 5: {', '.join(top5_df['ticker'].astype(str)) if not top5_df.empty else '없음'}")
    if not top5_df.empty:
        lines.extend(
            [
                f"- 손익비가 가장 좋은 후보: {top5_df.sort_values('risk_reward', ascending=False).iloc[0]['ticker']}",
                f"- 점수가 가장 높은 후보: {top5_df.sort_values('final_score', ascending=False).iloc[0]['ticker']}",
                f"- 우선 검토 후보: {top5_df.iloc[0]['ticker']}",
            ]
        )

    lines.extend(["", "---", "", "## 2. Top 5 요약표", ""])
    lines.append("| 순위 | 티커 | 종목명 | 점수 | 판단 | 차트 유형 | RSI | 거래량 비율 | 손절가 | 1차 목표가 | 2차 목표가 | 손익비 |")
    lines.append("|---:|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|")
    for _, row in top5_df.iterrows():
        lines.append(
            f"| {row['rank']} | {row['ticker']} | {row['name']} | {row['final_score']} | {_decision(row['decision'])} | "
            f"{_chart(row['chart_type'])} | {_fmt(row['rsi14'])} | {_fmt(row['volume_ratio'])} | {_fmt(row['stop_loss'])} | "
            f"{_fmt(row['target1'])} | {_fmt(row['target2'])} | {_fmt(row['risk_reward'])} |"
        )

    lines.extend(["", "---", "", "## 3. 종목별 상세 근거", ""])
    for _, row in top5_df.iterrows():
        lines.extend(
            [
                f"### {int(row['rank'])}) {row['ticker']} / {row['name']}",
                f"- 최종 점수: {row['final_score']}",
                f"- 판단 등급: {_decision(row['decision'])}",
                f"- 차트 유형: {_chart(row['chart_type'])}",
                f"- 현재가: {_fmt(row['current_price'])}",
                f"- 20일선 / 50일선 / 200일선: {_fmt(row['ma20'])} / {_fmt(row['ma50'])} / {_fmt(row['ma200'])}",
                f"- RSI 14: {_fmt(row['rsi14'])}",
                f"- MACD / 시그널: {_fmt(row['macd'])} / {_fmt(row['macd_signal'])}",
                f"- 거래량 비율: {_fmt(row['volume_ratio'])}배",
                f"- 5일 수익률 / 20일 수익률: {_fmt(row['return_5d'])}% / {_fmt(row['return_20d'])}%",
                f"- ATR 14 / ATR 비율: {_fmt(row['atr14'])} / {_fmt(row['atr_pct'])}%",
                f"- 최근 20일 고점 / 60일 고점: {_fmt(row['high20'])} / {_fmt(row['high60'])}",
                f"- 손절가 / 1차 목표가 / 2차 목표가: {_fmt(row['stop_loss'])} / {_fmt(row['target1'])} / {_fmt(row['target2'])}",
                f"- 1차 예상 수익률 / 2차 예상 수익률: {_fmt(row['expected_return_1'])}% / {_fmt(row['expected_return_2'])}%",
                f"- 손실 위험률 / 손익비: {_fmt(row['downside_risk'])}% / {_fmt(row['risk_reward'])}",
                "",
                "선정 근거:",
            ]
        )
        for point in row.get("evidence_points", []):
            lines.append(f"- {point}")
        lines.append("")
        lines.append("주의 요인:")
        for point in row.get("risk_points", []):
            lines.append(f"- {point}")
        lines.append("")

    lines.extend(["---", "", "## 4. 제외 또는 낮은 우선순위 종목", ""])
    excluded = full_df[full_df["decision"].eq("Excluded")].copy()
    if excluded.empty:
        lines.append("- 현재 점수 기준에서 제외 종목은 없습니다.")
    else:
        for _, row in excluded.sort_values("final_score", ascending=False).head(20).iterrows():
            lines.append(f"- {row['ticker']} / {row['name']}: {row['final_score']}점, {_reason(row.get('exclude_reason'))}")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 5. Claude 최종 검수 요청 프롬프트",
            "",
            "아래 데이터는 Python 스크리너가 전일 차트와 기술적 지표를 기준으로 계산한 결과입니다.",
            "다음 기준으로 최종 검수해 주세요.",
            "",
            "1. Top 5 종목의 실제 단기 관찰 우선순위를 다시 정렬",
            "2. 과열, 거래량 부족, 손익비 부족 후보는 제외 또는 우선순위 하향",
            "3. 각 종목의 진입 가능 구간, 손절가, 1차 목표가, 2차 목표가를 재검토",
            "4. 실제 판단 전 반드시 확인해야 할 차트 조건과 뉴스 조건 제시",
            "5. 최종적으로 공격 후보, 관심 후보, 관찰 후보, 제외 후보로 분류",
            "6. 모든 표현은 확정이 아니라 조건부 판단으로 정리",
        ]
    )
    return "\n".join(lines)


def display_label(row) -> str:
    """종목 표시명: 종목 이름 우선, 한국 종목은 접미사(.KS/.KQ) 없는 코드만 병기."""
    ticker = str(row.get("ticker") or "")
    name = row.get("name")
    try:
        has_name = name is not None and not pd.isna(name) and str(name).strip() not in {"", "nan", "None", "-"}
    except (TypeError, ValueError):
        has_name = bool(name)
    code = ticker
    upper = ticker.upper()
    if upper.endswith(".KS") or upper.endswith(".KQ"):
        code = ticker[: ticker.rfind(".")]
    if has_name and str(name) != ticker:
        return f"{name} ({code})"
    return ticker


def _selection_note(row) -> str:
    note = row.get("selection_note")
    if note is None or pd.isna(note):
        return ""
    text = str(note).strip()
    return "" if text in {"", "nan", "-"} else text


def build_claude_mobile_prompt(top5_df: pd.DataFrame, config: dict | None = None, max_chars: int = 3800) -> str:
    market_label = (config or {}).get("market", {}).get("label", "미국장")
    count = len(top5_df)
    lines = [
        "Claude 검수 요청",
        "",
        f"아래는 {market_label} 전일 차트 기반 상승 후보 Top {count} 결과다. 단기 차트 후보 검수 관점에서 판단해줘.",
        "투자 조언이 아니라 기술적 조건 검수용 자료입니다.",
        "각 종목을 공격 후보, 관심 후보, 관찰 후보, 제외 후보로 다시 분류하고, 실제 매수 전 확인해야 할 조건을 짧게 정리해 주세요.",
        "점수 기준 미달이지만 정보 제공을 위해 포함한 '보충 후보'는 참고 표기를 확인해 더 보수적으로 판단해 주세요.",
        "",
    ]
    if config:
        stats = _stats(config)
        if stats:
            lines.extend(
                [
                    f"분석 대상: {stats.get('universe_label', stats.get('universe_mode', 'custom'))}",
                    f"전체 로드 종목 수: {stats.get('raw_tickers_loaded', 0)}개",
                    f"필터 통과 종목 수: {stats.get('passed_liquidity_filter', 0)}개",
                ]
            )
            if stats.get("regime_note"):
                lines.append(f"장세 안내: {stats['regime_note']}")
            lines.append("")
    lines.extend([f"Top {count} 후보", ""])

    for idx, row in top5_df.reset_index(drop=True).iterrows():
        evidence = _first_points(row.get("evidence_points", []), 2)
        risks = _first_points(row.get("risk_points", []), 2)
        lines.extend(
            [
                f"{idx + 1}. {display_label(row)}",
                f"- 점수: {row.get('final_score')}점"
                + (f" (종합 {row.get('composite_score')}점)" if not pd.isna(row.get("composite_score", pd.NA)) else ""),
                f"- 판단: {_decision(row.get('decision'))}",
                f"- 차트 유형: {_chart(row.get('chart_type'))}",
                f"- 현재가: {_fmt(row.get('current_price'))}",
                f"- RSI: {_fmt(row.get('rsi14'), 1)}",
                f"- 거래량 비율: {_fmt(row.get('volume_ratio'))}배",
                f"- 손절가: {_fmt(row.get('stop_loss'))}",
                f"- 1차 목표가: {_fmt(row.get('target1'))}",
                f"- 2차 목표가: {_fmt(row.get('target2'))}",
                f"- 손익비: {_fmt(row.get('risk_reward'))}",
            ]
        )
        note = _selection_note(row)
        if note:
            lines.append(f"- 참고: {note}")
        lines.append("- 선정 근거:")
        lines.extend([f"  {point}" for point in evidence] or ["  뚜렷한 선정 근거가 제한적입니다."])
        lines.append("- 주의 요인:")
        lines.extend([f"  {point}" for point in risks] or ["  별도 주요 위험 신호는 제한적입니다."])
        lines.append("")

    lines.extend(
        [
            "검수 요청:",
            f"1. Top {count}의 우선순위를 다시 정렬해 주세요.",
            "2. 과열, 거래량 부족, 손익비 부족, 보충 후보는 제외 또는 하향해 주세요.",
            "3. 각 종목별 진입 전 확인 조건을 2~3개로 요약해 주세요.",
        ]
    )

    text = "\n".join(lines).strip()
    if len(text) <= max_chars:
        return text

    compact_lines = [
        "Claude 검수 요청",
        "전일 차트 기반 Top 5입니다. 각 종목을 공격/관심/관찰/제외로 재분류하고 진입 전 확인 조건을 짧게 정리해 주세요.",
        "",
    ]
    for idx, row in top5_df.reset_index(drop=True).iterrows():
        evidence = _first_points(row.get("evidence_points", []), 1)
        risks = _first_points(row.get("risk_points", []), 1)
        compact_lines.extend(
            [
                f"{idx + 1}. {display_label(row)}: {row.get('final_score')}점, {_decision(row.get('decision'))}, {_chart(row.get('chart_type'))}",
                f"현재가 {_fmt(row.get('current_price'))}, RSI {_fmt(row.get('rsi14'), 1)}, 거래량 {_fmt(row.get('volume_ratio'))}배, 손절 {_fmt(row.get('stop_loss'))}, 목표 {_fmt(row.get('target1'))}/{_fmt(row.get('target2'))}",
            ]
        )
        note = _selection_note(row)
        if note:
            compact_lines.append(f"참고: {note}")
        compact_lines.extend(
            [
                f"근거: {evidence[0] if evidence else '제한적'}",
                f"주의: {risks[0] if risks else '제한적'}",
                "",
            ]
        )
    return "\n".join(compact_lines).strip()[:max_chars]


def _quality_warning_text() -> str:
    return "\n".join(
        [
            "[품질 경고]",
            "- 샘플 데이터 기반 종목은 Top 5 후보에서 제외했습니다.",
            "- 유동성 미달 종목은 경고 표시했습니다.",
            "- 손익비 기준 미달 종목은 주의 표시했습니다.",
            "- 낙폭과대 착시형 차트는 점수 페널티를 적용했습니다.",
            "",
        ]
    )


def _analysis_summary_text(top5_df: pd.DataFrame, config: dict) -> str:
    stats = config.get("_run_stats", {})
    lines = ["## 추가 검수 포인트", ""]
    if stats.get("market_regime") or stats.get("market_comment"):
        lines.append(f"- 시장 분위기: {stats.get('market_regime', '-')}. {stats.get('market_comment', '')}")
    for _, row in top5_df.iterrows():
        ticker = row.get("ticker", "")
        name = row.get("name", "")
        lines.extend(
            [
                f"- {name} / {ticker}",
                f"  - 손익비 상태: {row.get('risk_reward_status_label', '-')}",
                f"  - 선정 이유: {row.get('selection_reason', '-')}",
                f"  - 주의 요인: {row.get('caution') or row.get('chase_risk_warning') or '특이사항 없음'}",
                f"  - 섹터 집중: {row.get('sector_concentration_warning') or '특이사항 없음'}",
                f"  - 연속 추천: {row.get('consecutive_recommendation_comment') or '특이사항 없음'}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(full_df: pd.DataFrame, top5_df: pd.DataFrame, config: dict) -> dict:
    output_cfg = config.get("output", {})
    out_dir = Path(output_cfg.get("output_dir", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)

    top5_path = Path(output_cfg.get("top5_csv", out_dir / "top5.csv"))
    full_path = Path(output_cfg.get("full_result_csv", out_dir / "full_result.csv"))
    report_path = Path(output_cfg.get("claude_report_md", out_dir / "claude_input_report.md"))

    performance_text = config.get("_performance_summary_text", "")
    report_extra = _quality_warning_text()
    report_extra += "\n" + _analysis_summary_text(top5_df, config)
    if performance_text:
        report_extra += "\n" + performance_text + "\n"
    report_path.write_text(build_report(full_df, top5_df, config) + "\n\n" + report_extra, encoding="utf-8")

    full_output_df = full_df.copy()
    top5_output_df = top5_df.copy()
    for output_df in [full_output_df, top5_output_df]:
        if "decision" in output_df.columns:
            output_df["decision"] = output_df["decision"].map(_decision)
        if "chart_type" in output_df.columns:
            output_df["chart_type"] = output_df["chart_type"].map(_chart)
        if "exclude_reason" in output_df.columns:
            output_df["exclude_reason"] = output_df["exclude_reason"].map(_reason)

    full_output_df.to_csv(full_path, index=False, encoding="utf-8-sig")
    top5_output_df.to_csv(top5_path, index=False, encoding="utf-8-sig")
    return {
        "top5_csv": str(top5_path),
        "full_result_csv": str(full_path),
        "claude_report_md": str(report_path),
    }
