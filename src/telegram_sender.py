"""Telegram message creation and optional delivery."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
import requests

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


def _chart(value) -> str:
    return CHART_TYPE_LABELS.get(str(value), str(value))


def build_telegram_message(top5_df: pd.DataFrame, stats: dict | None = None) -> str:
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
    lines.append("")
    lines.extend(
        [
            "[품질 경고]",
            "- 샘플 데이터 기반 종목은 Top 5 후보에서 제외했습니다.",
            "- 유동성 미달 종목은 경고 표시했습니다.",
            "- 손익비 기준 미달 종목은 주의 표시했습니다.",
            "- 낙폭과대 착시형 차트는 점수 페널티를 적용했습니다.",
            "",
        ]
    )
    if top5_df.empty:
        lines.append("선정된 후보 종목이 없습니다.")
    for idx, row in top5_df.reset_index(drop=True).iterrows():
        lines.extend(
            [
                f"{idx + 1}. {row.get('ticker')} / {row.get('final_score')}점 / {_chart(row.get('chart_type'))}",
                f"- RSI: {row.get('rsi14')}",
                f"- 거래량 비율: {row.get('volume_ratio')}배",
                f"- 손절가: {row.get('stop_loss')}",
                f"- 1차 목표가: {row.get('target1')}",
                f"- 2차 목표가: {row.get('target2')}",
                f"- 손익비: {row.get('risk_reward')}",
                "",
            ]
        )
    lines.append("Claude 모바일 복붙용 프롬프트가 이어서 전송됩니다.")
    if stats and (stats.get("market_regime") or stats.get("market_comment")):
        lines.append("")
        lines.append(f"시장 분위기: {stats.get('market_regime', '-')}. {stats.get('market_comment', '')}")
    caution_lines = []
    for _, row in top5_df.reset_index(drop=True).iterrows():
        caution = row.get("caution") or row.get("chase_risk_warning") or row.get("risk_reward_message")
        if caution:
            caution_lines.append(f"{row.get('name', row.get('ticker'))}: {caution}")
    if caution_lines:
        lines.append("")
        lines.append("[핵심 주의점]")
        lines.extend(caution_lines[:5])
    if stats and stats.get("performance_summary_text"):
        lines.append(stats["performance_summary_text"])
        lines.append("")
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
