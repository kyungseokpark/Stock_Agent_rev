"""Telegram message creation and optional delivery."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
import requests

from src.report_builder import display_label

LOGGER = logging.getLogger(__name__)

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


DECISION_LABELS = {
    "Strong Candidate": "강한 후보",
    "Candidate": "관심 후보",
    "Watchlist": "관찰 후보",
    "Excluded": "제외",
}

FORCE_GRADE_LABELS = {
    "strong_inflow": "강한 유입",
    "inflow": "유입",
    "neutral": "중립",
    "weak": "약함",
    "outflow": "유출",
    "insufficient": "데이터 부족",
    "disabled": "",
}


def _chart(value) -> str:
    return CHART_TYPE_LABELS.get(str(value), str(value))


def _decision(value) -> str:
    return DECISION_LABELS.get(str(value), str(value))


def _force_grade(value) -> str:
    text = str(value or "").strip()
    if text in {"", "nan", "None", "-"}:
        return ""
    if text in FORCE_GRADE_LABELS:
        return FORCE_GRADE_LABELS[text]
    if any("a" <= ch.lower() <= "z" for ch in text):
        return "미분류"
    return text


def _has_value(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text not in {"", "nan", "None", "-"}


def _num(value, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:,.{digits}f}"


def build_telegram_message(
    top5_df: pd.DataFrame,
    stats: dict | None = None,
    force_top5_df: pd.DataFrame | None = None,
) -> str:
    """Build a Korean Telegram summary message."""
    market_label = stats.get("market_label", "") if stats else ""
    title = f"[{market_label} 전일 차트 기반 Top 5 스크리닝]" if market_label else "[전일 차트 기반 Top 5 스크리닝]"
    lines = [title]
    if stats:
        lines.extend(
            [
                f"분석 대상: {stats.get('universe_label', stats.get('universe_mode', 'custom'))}",
                f"전체 로드 종목 수: {stats.get('raw_tickers_loaded', 0)}개",
                f"중복 제거 후 종목 수: {stats.get('unique_tickers', 0)}개",
                f"필터 통과 종목 수: {stats.get('passed_liquidity_filter', 0)}개",
                f"최종 후보: Top {stats.get('selected_top_candidates', len(top5_df))}",
            ]
        )
        if stats.get("regime_note"):
            lines.append(f"장세 안내: {stats['regime_note']}")
    lines.append("")
    lines.extend(
        [
            "[품질 경고]",
            "- 샘플 데이터 기반 종목은 Top 5 후보에서 제외했습니다.",
            "- 유동성 미달 종목은 경고 표시했습니다.",
            "- 손익비 기준 미달 종목은 주의 표시했습니다.",
            "- 낙폭과대 착시형 차트는 점수 페널티를 적용했습니다.",
            "- 후보 5개 확보를 위해 기준 미달 종목은 '보충 후보'로 사유와 함께 표기했습니다.",
            "",
        ]
    )
    if top5_df.empty:
        lines.append("선정된 후보 종목이 없습니다.")
    for idx, row in top5_df.reset_index(drop=True).iterrows():
        # 기본 점수 추출
        composite = row.get("composite_score")
        chart = row.get("chart_score") or row.get("adjusted_score") or row.get("final_score")
        force = row.get("force_inflow_pct")
        force_grade_val = row.get("force_inflow_grade")

        score_parts = []
        if composite is not None and not pd.isna(composite):
            score_parts.append(f"종합 {composite}점")
        if chart is not None and not pd.isna(chart):
            score_parts.append(f"차트 {chart}점")
        if force is not None and not pd.isna(force):
            score_parts.append(f"세력 {force}점")

        score_str = " | ".join(score_parts) if score_parts else f"점수 {row.get('final_score')}점"
        ticker_line = f"{idx + 1}. {display_label(row)} ({score_str}) / {_chart(row.get('chart_type'))}"
        if _has_value(row.get("decision")):
            ticker_line += f" [{_decision(row.get('decision'))}]"
        lines.append(ticker_line)

        # 보충 후보 표기 (점수·손익비·분산·장세 기준 미달 사유)
        if _has_value(row.get("selection_note")):
            lines.append(f"  - 참고: {row.get('selection_note')}")

        # 현재가 및 최근 흐름
        price_details = []
        if _has_value(row.get("current_price")):
            price_details.append(f"현재가 {_num(row.get('current_price'))}")
        if _has_value(row.get("return_1d")):
            price_details.append(f"전일 {float(row.get('return_1d')):+.2f}%")
        if _has_value(row.get("return_5d")):
            price_details.append(f"5일 {float(row.get('return_5d')):+.2f}%")
        if _has_value(row.get("sector")) and str(row.get("sector")) != "Unknown":
            price_details.append(f"섹터 {row.get('sector')}")
        if price_details:
            lines.append(f"  - 시세: {', '.join(price_details)}")

        # 핵심 지표 정보
        metrics = []
        if not pd.isna(row.get("rsi14")):
            metrics.append(f"RSI: {row.get('rsi14')}")
        if not pd.isna(row.get("volume_ratio")):
            metrics.append(f"거래비율: {row.get('volume_ratio')}배")
        if not pd.isna(row.get("vcp_score")) and float(row.get("vcp_score")) > 0:
            metrics.append(f"VCP수축: {row.get('vcp_score')}점")
        if not pd.isna(row.get("rs_rank")) and float(row.get("rs_rank")) > 0:
            metrics.append(f"상대강도: {row.get('rs_rank')}위")
        if metrics:
            lines.append(f"  - 지표: {', '.join(metrics)}")

        # 세부 세력 유입 정보 (외인/기관 비율 등이 있을 경우)
        inflow_details = []
        if not pd.isna(row.get("fi_foreign_pct")):
            inflow_details.append(f"외인 {row.get('fi_foreign_pct')}%")
        if not pd.isna(row.get("fi_inst_pct")):
            inflow_details.append(f"기관 {row.get('fi_inst_pct')}%")
        if not pd.isna(row.get("fi_foreign_streak")) and int(row.get("fi_foreign_streak", 0)) > 0:
            inflow_details.append(f"외인연속 {int(row.get('fi_foreign_streak'))}일")
        force_grade_text = _force_grade(force_grade_val)
        if _has_value(force_grade_text):
            inflow_details.append(f"등급: {force_grade_text}")
        if inflow_details:
            lines.append(f"  - 세력: {', '.join(inflow_details)}")

        # 거래 설정 가격 (1차/2차 목표가, 손절가, 손익비, 기대수익률)
        target1_txt = _num(row.get("target1"))
        target2_txt = _num(row.get("target2"))
        stop_txt = _num(row.get("stop_loss"))
        if _has_value(row.get("expected_return_1")):
            target1_txt += f"({float(row.get('expected_return_1')):+.2f}%)"
        if _has_value(row.get("expected_return_2")):
            target2_txt += f"({float(row.get('expected_return_2')):+.2f}%)"
        if _has_value(row.get("downside_risk")):
            stop_txt += f"(-{abs(float(row.get('downside_risk'))):.2f}%)"
        lines.append(f"  - 가격: 1차 {target1_txt} / 2차 {target2_txt} / 손절 {stop_txt} (손익비: {row.get('risk_reward')})")

        # 포지션 제안 (계좌·리스크 설정 기반)
        if _has_value(row.get("position_size")) and float(row.get("position_size") or 0) > 0:
            lines.append(f"  - 포지션 제안: {_num(row.get('position_size'))}주 (약 {_num(row.get('position_value'))})")

        # 개별 종목 분석 의견 및 주의점
        reason = row.get("selection_reason")
        caution_val = row.get("caution")
        if reason and str(reason) != "nan" and reason != "-":
            lines.append(f"  - 분석: {reason}")
        if caution_val and str(caution_val) != "nan" and caution_val != "-":
            lines.append(f"  - 주의: {caution_val}")
        if _has_value(row.get("consecutive_recommendation_comment")):
            lines.append(f"  - 연속추천: {row.get('consecutive_recommendation_comment')}")
        if _has_value(row.get("sector_concentration_warning")):
            lines.append(f"  - 섹터집중: {row.get('sector_concentration_warning')}")
        if _has_value(row.get("liquidity_warning")):
            lines.append(f"  - 유동성: {row.get('liquidity_warning')}")
        lines.append("")

    # 세력 점수 기준 별도 랭킹 (종합 Top 5와 독립)
    if force_top5_df is not None and not force_top5_df.empty:
        composite_tickers = set(top5_df["ticker"].astype(str)) if "ticker" in top5_df.columns else set()
        lines.append(f"[세력주 Top {len(force_top5_df)}] (세력 점수 기준 정렬)")
        for idx, row in force_top5_df.reset_index(drop=True).iterrows():
            overlap = " ★종합 Top5 포함" if str(row.get("ticker")) in composite_tickers else ""
            grade = row.get("force_inflow_grade")
            grade_text = _force_grade(grade)
            grade_txt = f", 등급 {grade_text}" if _has_value(grade_text) else ""
            lines.append(
                f"{idx + 1}. {display_label(row)} — 세력 {row.get('force_inflow_pct')}점{grade_txt}"
                f" / 종합 {row.get('composite_score')}점 / {_chart(row.get('chart_type'))}{overlap}"
            )
            force_details = []
            if not pd.isna(row.get("fi_foreign_pct")):
                force_details.append(f"외인 {row.get('fi_foreign_pct')}%")
            if not pd.isna(row.get("fi_inst_pct")):
                force_details.append(f"기관 {row.get('fi_inst_pct')}%")
            if not pd.isna(row.get("fi_foreign_streak")) and int(row.get("fi_foreign_streak", 0)) > 0:
                force_details.append(f"외인연속 {int(row.get('fi_foreign_streak'))}일")
            if _has_value(row.get("current_price")):
                force_details.append(f"현재가 {_num(row.get('current_price'))}")
            if _has_value(row.get("risk_reward")):
                force_details.append(f"손익비 {row.get('risk_reward')}")
            if force_details:
                lines.append(f"  - {', '.join(force_details)}")
        lines.append("")

    if not top5_df.empty:
        lines.append("Claude 모바일 복붙용 프롬프트가 이어서 전송됩니다.")
    if stats and (stats.get("market_regime") or stats.get("market_comment")):
        lines.append("")
        lines.append(f"시장 분위기: {stats.get('market_regime', '-')}. {stats.get('market_comment', '')}")
    caution_lines = []
    for _, row in top5_df.reset_index(drop=True).iterrows():
        caution = row.get("caution") or row.get("chase_risk_warning") or row.get("risk_reward_message")
        if caution:
            caution_lines.append(f"{display_label(row)}: {caution}")
    if caution_lines:
        lines.append("")
        lines.append("[핵심 주의점 요약]")
        lines.extend(caution_lines[:5])
    if stats and stats.get("performance_summary_text"):
        lines.append("")
        lines.append(stats["performance_summary_text"])
        lines.append("")
    return "\n".join(lines)


def build_compact_telegram_message(
    top5_df: pd.DataFrame,
    stats: dict | None = None,
    force_top5_df: pd.DataFrame | None = None,
) -> str:
    """Build the single short Telegram message sent for one market run."""
    market_label = stats.get("market_label", "") if stats else ""
    selected = stats.get("selected_top_candidates", len(top5_df)) if stats else len(top5_df)
    title = f"[{market_label} Top {selected} 요약]" if market_label else f"[Top {selected} 요약]"
    lines = [title]

    if stats:
        universe = stats.get("universe_label", stats.get("universe_mode", "custom"))
        loaded = stats.get("unique_tickers", stats.get("raw_tickers_loaded", 0))
        passed = stats.get("passed_liquidity_filter", 0)
        lines.append(f"Universe: {universe} / loaded {loaded} / passed {passed}")
        if stats.get("market_regime") or stats.get("market_comment"):
            lines.append(f"Market: {stats.get('market_regime', '-')}. {stats.get('market_comment', '')}".strip())

    if top5_df.empty:
        lines.append("No selected candidates.")
    else:
        for idx, row in top5_df.reset_index(drop=True).iterrows():
            score = row.get("composite_score")
            if not _has_value(score):
                score = row.get("final_score")
            parts = []
            if _has_value(score):
                parts.append(f"score {_num(score)}")
            if _has_value(row.get("current_price")):
                parts.append(f"price {_num(row.get('current_price'))}")
            if _has_value(row.get("risk_reward")):
                parts.append(f"RR {row.get('risk_reward')}")
            if _has_value(row.get("target1")) and _has_value(row.get("stop_loss")):
                parts.append(f"T1 {_num(row.get('target1'))} / SL {_num(row.get('stop_loss'))}")
            suffix = f" ({', '.join(parts)})" if parts else ""
            lines.append(f"{idx + 1}. {display_label(row)}{suffix}")

    if force_top5_df is not None and not force_top5_df.empty:
        force_names = [display_label(row) for _, row in force_top5_df.reset_index(drop=True).head(5).iterrows()]
        lines.append(f"Force leaders: {', '.join(force_names)}")

    return "\n".join(lines)


def get_telegram_credentials(config: dict) -> tuple[str, str]:
    telegram = config.get("telegram", {})
    token = os.getenv("TELEGRAM_BOT_TOKEN") or telegram.get("bot_token", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or telegram.get("chat_id", "")
    return token, chat_id


def send_telegram_message(message: str, token: str, chat_id: str) -> bool:
    """Send a plain text Telegram message without parse_mode."""
    if not token or not chat_id:
        LOGGER.info("Telegram token/chat_id is not configured; skipping message send.")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=15,
        )
        response.raise_for_status()
        LOGGER.info("Telegram summary message sent.")
        return True
    except Exception as exc:  # pragma: no cover - network dependent
        LOGGER.warning("Telegram message send failed: %s", exc)
        return False


def split_text_messages(text: str, max_chars: int = 3800) -> list[str]:
    """Split long plain text into Telegram-safe message chunks."""
    if len(text) <= max_chars:
        return [text]

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        for start in range(0, len(paragraph), max_chars):
            chunks.append(paragraph[start : start + max_chars])
    if current:
        chunks.append(current)

    total = len(chunks)
    if total <= 1:
        return chunks

    prefixed_chunks = []
    for idx, chunk in enumerate(chunks, start=1):
        prefix = f"[{idx}/{total}]\n"
        prefixed_chunks.append(prefix + chunk[: max_chars - len(prefix)])
    return prefixed_chunks


def send_text_messages(text: str, token: str, chat_id: str, max_chars: int = 3800) -> bool:
    """Send plain text, splitting into multiple Telegram messages when needed."""
    chunks = split_text_messages(text, max_chars=max_chars)
    all_sent = True
    for chunk in chunks:
        all_sent = send_telegram_message(chunk, token, chat_id) and all_sent
    LOGGER.info("Telegram text chunks sent: %s", len(chunks))
    return all_sent


def send_document(file_path: str, token: str, chat_id: str, caption: str = "") -> bool:
    """Send a document through Telegram Bot API sendDocument."""
    if not token or not chat_id:
        LOGGER.info("Telegram token/chat_id is not configured; skipping document send.")
        return False

    path = Path(file_path)
    if not path.exists():
        LOGGER.warning("Telegram document file does not exist: %s", file_path)
        return False
    if not path.is_file():
        LOGGER.warning("Telegram document path is not a file: %s", file_path)
        return False

    try:
        with path.open("rb") as document:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (path.name, document, "text/markdown")},
                timeout=30,
            )
        response.raise_for_status()
        LOGGER.info("Telegram document sent: %s", file_path)
        return True
    except Exception as exc:  # pragma: no cover - network dependent
        LOGGER.warning("Telegram document send failed: %s", exc)
        return False
