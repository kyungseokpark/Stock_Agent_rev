"""\uc8fc\uc2dd \uc2a4\ud06c\ub9ac\ub108 \ub370\uc2a4\ud06c\ud1b1 \ud654\uba74."""

from __future__ import annotations

import logging
import json
import os
import queue
import shutil
import sys
import threading
import traceback
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
import tkinter.font as tkfont

import pandas as pd

SOURCE_DIR = Path(__file__).resolve().parent


def get_resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", SOURCE_DIR)).resolve()
    return SOURCE_DIR


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_path = path / ".write_test"
        test_path.write_text("ok", encoding="utf-8")
        test_path.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def get_base_dir() -> Path:
    if not getattr(sys, "frozen", False):
        return SOURCE_DIR
    exe_dir = Path(sys.executable).resolve().parent
    if _is_writable_dir(exe_dir):
        return exe_dir
    fallback = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "StockAgentDAD"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


RESOURCE_DIR = get_resource_dir()
APP_DIR = get_base_dir()


def _copy_missing_tree(src: Path, dst: Path) -> None:
    if not src.exists() or src.resolve() == dst.resolve():
        return
    for item in src.rglob("*"):
        relative = item.relative_to(src)
        target = dst / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def ensure_runtime_layout() -> None:
    if RESOURCE_DIR != APP_DIR:
        for folder_name in ["configs", "data"]:
            _copy_missing_tree(RESOURCE_DIR / folder_name, APP_DIR / folder_name)
        for file_name in ["tickers.csv", "tickers_kr.csv", "매뉴얼.html"]:
            source = RESOURCE_DIR / file_name
            target = APP_DIR / file_name
            if source.exists() and not target.exists():
                shutil.copy2(source, target)
    for folder in [APP_DIR / "logs", APP_DIR / "output", APP_DIR / "data" / "cache"]:
        folder.mkdir(parents=True, exist_ok=True)


ensure_runtime_layout()
os.chdir(APP_DIR)
SETTINGS_PATH = APP_DIR / "desktop_config.json"
ENV_PATH = APP_DIR / ".env"
TELEGRAM_MANUAL_PATH = APP_DIR / "docs" / "telegram_setup_manual.html"
MANUAL_PATH = APP_DIR / "매뉴얼.html"

try:
    import matplotlib

    matplotlib.rcParams["font.family"] = "Malgun Gothic"
    matplotlib.rcParams["axes.unicode_minus"] = False
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
except Exception:  # pragma: no cover - depends on local GUI packages
    Figure = None
    FigureCanvasTkAgg = None

from main import parse_args, run_from_args, run_screen, setup_logging
from src.backtest import run_picks_backtest
from src.data_loader import fetch_ohlcv
from src.indicators import add_indicators
from src.market_config import load_config
from src.performance_tracker import (
    build_performance_summary_text,
    get_recent_recommendations,
    get_tracking_table,
    summarize_tracking_performance,
    update_tracking_results,
)
from src.scheduler import (
    query_recommended_tasks,
    recommend_times,
    register_task,
    register_recommended_tasks,
    unregister_recommended_tasks,
)
from src.sector_loader import STANDARD_SECTORS
from src.telegram_sender import send_text_messages
from src.universe_loader import load_universe

try:  # pragma: no cover - optional desktop dependency
    import ttkbootstrap as tb
except Exception:  # pragma: no cover
    tb = None


LOGGER = logging.getLogger(__name__)

PALETTE = {
    "bg": "#1F2428",
    "surface": "#2A3036",
    "surface2": "#323941",
    "border": "#3D454E",
    "text": "#F2F4F6",
    "muted": "#B6BEC7",
    "accent": "#FB923C",
    "accent_strong": "#F97316",
    "selection": "#3A2E22",
    "positive": "#34D399",
    "negative": "#F87171",
    "warn": "#FBBF24",
}

MARKETS = {
    "미국": {"region": "us", "config": "configs/config_us.yaml"},
    "한국": {"region": "kr", "config": "configs/config_kr.yaml"},
}

UNIVERSE_OPTIONS = {
    "us": {
        "관심종목": "custom",
        "에스앤피 500": "sp500",
        "나스닥 100": "nasdaq100",
        "에스앤피 500 + 나스닥 100": "sp500_nasdaq100",
        "관심종목 + 주요 지수": "combined",
        "미국 전체 파일": "all_us",
    },
    "kr": {
        "관심종목": "custom_kr",
        "코스피": "kospi",
        "코스닥": "kosdaq",
        "코스피 + 코스닥": "kospi_kosdaq",
        "관심종목 + 코스피 + 코스닥": "combined_kr",
    },
}

TABLE_COLUMNS = [
    ("rank", "순위", 55),
    ("name", "종목명", 170),
    ("ticker", "티커", 105),
    ("decision", "판정", 120),
    ("adjusted_score", "조정점수", 90),
    ("composite_score", "종합점수", 90),
    ("force_inflow_pct", "세력유입%", 85),
    ("force_inflow_grade", "세력등급", 105),
    ("final_score", "최종점수", 90),
    ("vcp_score", "수축패턴", 90),
    ("rs_rank", "상대강도", 90),
    ("current_price", "현재가", 105),
    ("stop_loss", "손절가", 105),
    ("target1", "1차목표", 105),
    ("target2", "2차목표", 105),
    ("risk_reward", "손익비", 85),
    ("chart_type", "패턴", 150),
]

TRACKING_COLUMNS = [
    ("run_date", "추천일", 95),
    ("market_region", "시장", 70),
    ("ticker", "티커", 105),
    ("name", "종목명", 160),
    ("entry_price", "추천가", 95),
    ("target1_price", "1차목표", 95),
    ("target2_price", "2차목표", 95),
    ("stop_price", "손절가", 95),
    ("days_after", "경과일", 70),
    ("tracking_date", "추적일", 95),
    ("close_price", "종가", 95),
    ("return_pct", "수익률%", 85),
    ("max_return_pct", "최고수익%", 90),
    ("min_return_pct", "최저수익%", 90),
    ("hit_target1", "1차목표", 75),
    ("hit_stop", "손절", 70),
    ("first_hit", "첫 도달", 105),
    ("status", "상태", 85),
]

BACKTEST_COLUMNS = [
    ("ticker", "티커", 105),
    ("signal_date", "신호일", 95),
    ("entry_date", "진입일", 95),
    ("exit_date", "청산일", 95),
    ("entry_price", "진입가", 95),
    ("exit_price", "청산가", 95),
    ("exit_reason", "청산사유", 95),
    ("r_multiple", "R배수", 80),
    ("final_score", "기존점수", 85),
    ("vcp_score", "수축점수", 85),
    ("rs_rank", "상대강도", 85),
    ("pnl", "손익", 100),
    ("sample", "구간", 70),
]

DETAIL_FIELDS = [
    ("ticker", "티커"),
    ("name", "종목명"),
    ("decision", "판정"),
    ("adjusted_score", "조정점수"),
    ("chart_score", "차트점수"),
    ("force_inflow_pct", "세력유입%"),
    ("force_inflow_grade", "세력등급"),
    ("force_inflow_source", "세력자료 해석"),
    ("force_position", "가격위치"),
    ("force_penalty", "분산감점"),
    ("force_sequence", "흐름보너스"),
    ("composite_score", "종합점수"),
    ("composite_source", "종합점수 방식"),
    ("final_score", "최종점수"),
    ("vcp_score", "수축패턴 점수"),
    ("rs_rank", "상대강도"),
    ("market_regime", "시장 분위기"),
    ("current_price", "현재가"),
    ("stop_loss", "손절가"),
    ("target1", "1차 목표"),
    ("target2", "2차 목표"),
    ("risk_reward", "손익비"),
    ("selection_reason", "선정 이유"),
    ("caution", "주의 사항"),
]

TELEGRAM_MANUAL_HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>텔레그램 등록 방법</title>
  <style>
    body { font-family: "Malgun Gothic", Arial, sans-serif; margin: 32px; line-height: 1.7; color: #111827; }
    h1 { margin-top: 0; }
    code { background: #f3f4f6; padding: 2px 6px; border-radius: 4px; }
    .box { border: 1px solid #d1d5db; border-radius: 8px; padding: 16px; margin: 16px 0; }
    li { margin: 8px 0; }
  </style>
</head>
<body>
  <h1>텔레그램 등록 방법</h1>
  <div class="box">
    <h2>1. 봇 토큰 만들기</h2>
    <ol>
      <li>텔레그램에서 <code>@BotFather</code>를 검색합니다.</li>
      <li><code>/newbot</code>을 입력하고 봇 이름과 사용자 이름을 만듭니다.</li>
      <li>BotFather가 알려주는 긴 문자열이 <b>봇 토큰</b>입니다.</li>
    </ol>
  </div>
  <div class="box">
    <h2>2. 채팅방 아이디 확인</h2>
    <ol>
      <li>새로 만든 봇에게 아무 메시지나 한 번 보냅니다.</li>
      <li>브라우저에서 <code>https://api.telegram.org/bot봇토큰/getUpdates</code>를 엽니다.</li>
      <li>응답에서 <code>chat</code> 안의 <code>id</code> 값이 <b>채팅방 아이디</b>입니다.</li>
      <li>단체방이면 봇을 단체방에 초대하고 메시지를 보낸 뒤 같은 방법으로 확인합니다.</li>
    </ol>
  </div>
  <div class="box">
    <h2>3. Stock Agent에 저장</h2>
    <ol>
      <li>프로그램의 <b>텔레그램 전송</b> 탭에 봇 토큰과 채팅방 아이디를 입력합니다.</li>
      <li><b>설정 저장</b>을 누릅니다.</li>
      <li><b>테스트 전송</b>으로 메시지가 오는지 확인합니다.</li>
      <li>원하는 한국장/미국장 시간을 입력한 뒤 <b>텔레그램 스케줄 등록</b>을 누릅니다.</li>
    </ol>
  </div>
  <p>토큰은 비밀번호처럼 취급하세요. 외부에 공유하지 마세요.</p>
</body>
</html>
"""

class ToolTip:
    """Small tkinter tooltip for senior-friendly inline help."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _event=None) -> None:
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tip,
            text=self.text,
            justify="left",
            background="#111827",
            foreground=PALETTE["text"],
            relief="solid",
            borderwidth=1,
            padx=10,
            pady=7,
            font=("Malgun Gothic", 11),
            wraplength=360,
        )
        label.pack()

    def hide(self, _event=None) -> None:
        if self.tip:
            self.tip.destroy()
            self.tip = None


def format_value(value, digits: int = 2) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    display_map = {
        "Strong Candidate": "강력 후보",
        "Candidate": "후보",
        "Watchlist": "관찰",
        "Excluded": "제외",
        "Breakout": "박스권 돌파",
        "Box breakout": "박스권 돌파",
        "Pullback rebound": "눌림목 반등",
        "20MA rebound": "20일선 반등",
        "MA20 recovery": "20일선 회복",
        "Near new high": "신고가 근처",
        "Near high": "고점 근처",
        "Relative strength leader": "상대강도 상위",
        "Relative strength": "상대강도 우수",
        "Oversold rebound": "과매도 반등",
        "Falling knife": "급락 위험",
        "Watchlist pattern": "관찰 패턴",
        "Excluded pattern": "제외 패턴",
        "VCP breakout": "수축 후 돌파",
        "VCP base": "수축 기반 형성",
        "KOSPI": "코스피",
        "KOSDAQ": "코스닥",
        "KOSPI + KOSDAQ": "코스피 + 코스닥",
        "S&P 500": "에스앤피 500",
        "Nasdaq 100": "나스닥 100",
        "S&P 500 + Nasdaq 100": "에스앤피 500 + 나스닥 100",
        "strong_inflow": "강한 유입세",
        "inflow": "유입세",
        "neutral": "중립",
        "weak": "약함",
        "outflow": "이탈 또는 분산",
        "insufficient": "판단할 데이터 부족",
        "disabled": "사용 안 함",
        "proxy": "가격과 거래량으로 추정한 값",
        "real": "외국인과 기관 수급 데이터 기반",
        "mixed": "수급 데이터와 가격·거래량을 함께 사용",
        "chart_only": "차트 점수만 사용",
        "blend": "차트 점수와 세력 점수를 함께 반영",
        "gate_penalty": "세력 점수가 낮아 보수적으로 감점",
        "base": "바닥권",
        "overheated": "단기 급등 직후",
        "top": "고점권",
        "unknown": "판단 불가",
        "none": "아직 없음",
        "stop_first": "손절 먼저",
        "target1_first": "1차 목표 먼저",
        "target2_first": "2차 목표 먼저",
        "ambiguous": "동시 도달",
        "tracking": "추적 중",
        "completed": "추적 완료",
        "time": "기간 종료",
        "stop": "손절",
        "target": "목표 도달",
        "IS": "학습구간",
        "OOS": "검증구간",
    }
    if isinstance(value, str):
        text_value = value.strip()
        if text_value in display_map:
            return display_map[text_value]
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text


def numeric_sort_value(value):
    try:
        return float(str(value).replace(",", ""))
    except Exception:
        return str(value)


def read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_desktop_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        LOGGER.warning("\ub370\uc2a4\ud06c\ud1b1 \uc124\uc815 \ud30c\uc77c\uc744 \uc77d\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4: %s", SETTINGS_PATH)
        return {}


def save_desktop_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def load_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def save_env_values(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for raw_line in lines:
        if "=" not in raw_line or raw_line.strip().startswith("#"):
            output.append(raw_line)
            continue
        key = raw_line.split("=", 1)[0].strip()
        if key in updates:
            output.append(f'{key}="{updates[key]}"')
            seen.add(key)
        else:
            output.append(raw_line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f'{key}="{value}"')
    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


class StockAgentDesktop(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("\uc2a4\ud1a1 \uc5d0\uc774\uc804\ud2b8")
        self.geometry("1420x880")
        self.minsize(1180, 720)

        self.message_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False
        self.full_df = pd.DataFrame()
        self.top_df = pd.DataFrame()
        self.paths: dict = {}
        self.current_config: dict = {}
        self.settings: dict = load_desktop_settings()
        self.current_market_label = tk.StringVar(value="\ubbf8\uad6d")
        self.universe_label = tk.StringVar(value="")
        self.sector_filter_enabled = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar(value="\ub300\uae30 \uc911")
        self.progress_text = tk.StringVar(value="\ub300\uae30 \uc911")
        self.last_run_text = tk.StringVar(value="")
        self.schedule_status_text = tk.StringVar(value="")
        env_values = load_env_values()
        telegram_settings = self.settings.get("telegram", {})
        schedule_settings = self.settings.get("telegram_schedule", {})
        self.telegram_bot_token = tk.StringVar(
            value=env_values.get("TELEGRAM_BOT_TOKEN", telegram_settings.get("bot_token", ""))
        )
        self.telegram_chat_id = tk.StringVar(
            value=env_values.get("TELEGRAM_CHAT_ID", telegram_settings.get("chat_id", ""))
        )
        self.telegram_kr_time = tk.StringVar(value=schedule_settings.get("kr_time", "16:00"))
        self.telegram_us_time = tk.StringVar(value=schedule_settings.get("us_time", "08:00"))
        self.telegram_status_text = tk.StringVar(value="")
        self.search_text = tk.StringVar(value="")
        self.show_full_columns = tk.BooleanVar(value=False)
        self.regime_gate = tk.BooleanVar(value=True)
        self.sector_diversification = tk.BooleanVar(value=True)
        self.top_n = tk.IntVar(value=5)
        self.min_score = tk.DoubleVar(value=50)
        self.vcp_min_score = tk.DoubleVar(value=70)
        self.min_risk_reward = tk.DoubleVar(value=1.2)
        self.chart_canvas = None
        self.criteria_text = None
        self.breakdown_tree = None
        self.progress_started_at: datetime | None = None
        self.sort_state: dict[str, bool] = {}
        self.current_market_label.set("\ubbf8\uad6d")

        self._configure_fonts()
        self._configure_style()
        self._build_ui()
        self._load_market_defaults()
        self._load_cached_results()
        self.after(150, self._poll_queue)

    def _configure_fonts(self) -> None:
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkTooltipFont"):
            try:
                tkfont.nametofont(name).configure(family="Malgun Gothic", size=11)
            except Exception:
                pass
        self.option_add("*Font", ("Malgun Gothic", 11))

    def _add_tooltip(self, widget: tk.Widget, text: str) -> None:
        ToolTip(widget, text)

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            if tb is not None:
                style.theme_use("darkly")
            else:
                style.theme_use("clam")
        except tk.TclError:
            pass
        self.configure(bg=PALETTE["bg"])
        style.configure(".", font=("Malgun Gothic", 12), background=PALETTE["bg"], foreground=PALETTE["text"])
        style.configure("TFrame", background=PALETTE["bg"])
        style.configure("TLabelframe", background=PALETTE["bg"], foreground=PALETTE["text"])
        style.configure("TLabelframe.Label", background=PALETTE["bg"], foreground=PALETTE["text"], font=("Malgun Gothic", 12, "bold"))
        style.configure("Title.TLabel", font=("Malgun Gothic", 24, "bold"), background=PALETTE["bg"], foreground=PALETTE["text"])
        style.configure("Sub.TLabel", foreground=PALETTE["muted"], background=PALETTE["bg"], font=("Malgun Gothic", 12))
        style.configure("Status.TLabel", font=("Malgun Gothic", 12, "bold"), background=PALETTE["bg"], foreground=PALETTE["accent"])
        style.configure("Treeview", rowheight=38, background=PALETTE["surface"], fieldbackground=PALETTE["surface"], foreground=PALETTE["text"])
        style.configure("Treeview.Heading", font=("Malgun Gothic", 12, "bold"), background=PALETTE["surface2"], foreground=PALETTE["text"])
        style.map("Treeview", background=[("selected", PALETTE["selection"])], foreground=[("selected", PALETTE["text"])])
        style.configure(
            "Readable.TCombobox",
            fieldbackground=PALETTE["surface"],
            background=PALETTE["surface"],
            foreground=PALETTE["text"],
            selectbackground=PALETTE["selection"],
            selectforeground=PALETTE["text"],
            arrowcolor=PALETTE["accent"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            padding=4,
        )
        style.map(
            "Readable.TCombobox",
            fieldbackground=[("readonly", PALETTE["surface"]), ("!disabled", PALETTE["surface"])],
            foreground=[("readonly", PALETTE["text"]), ("!disabled", PALETTE["text"])],
            selectbackground=[("readonly", PALETTE["selection"])],
            selectforeground=[("readonly", PALETTE["text"])],
        )
        style.configure(
            "Readable.TSpinbox",
            font=("Malgun Gothic", 12),
            fieldbackground="#F4EBD8",
            background="#F4EBD8",
            foreground="#111111",
            selectbackground="#F7D9B5",
            selectforeground="#111111",
            insertcolor="#111111",
            arrowcolor="#111111",
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            padding=4,
        )
        style.map(
            "Readable.TSpinbox",
            fieldbackground=[("readonly", "#F4EBD8"), ("!disabled", "#F4EBD8")],
            foreground=[("readonly", "#111111"), ("!disabled", "#111111")],
            selectbackground=[("readonly", "#F7D9B5"), ("!disabled", "#F7D9B5")],
            selectforeground=[("readonly", "#111111"), ("!disabled", "#111111")],
        )
        style.configure(
            "Readable.TEntry",
            font=("Malgun Gothic", 12),
            fieldbackground="#F4EBD8",
            foreground="#111111",
            selectbackground="#F7D9B5",
            selectforeground="#111111",
            insertcolor="#111111",
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            padding=4,
        )
        style.map(
            "Readable.TEntry",
            fieldbackground=[("!disabled", "#F4EBD8")],
            foreground=[("!disabled", "#111111")],
            selectbackground=[("!disabled", "#F7D9B5")],
            selectforeground=[("!disabled", "#111111")],
        )
        for widget_style in ("TSpinbox", "TEntry"):
            style.configure(
                widget_style,
                fieldbackground="#F4EBD8",
                foreground="#111111",
                selectbackground="#F7D9B5",
                selectforeground="#111111",
                insertcolor="#111111",
            )
            style.map(
                widget_style,
                fieldbackground=[("!disabled", "#F4EBD8")],
                foreground=[("!disabled", "#111111")],
                selectbackground=[("!disabled", "#F7D9B5")],
                selectforeground=[("!disabled", "#111111")],
            )
        style.configure(
            "TNotebook",
            background=PALETTE["bg"],
            bordercolor=PALETTE["border"],
        )
        style.configure(
            "TNotebook.Tab",
            font=("Malgun Gothic", 12, "bold"),
            padding=(14, 8),
            background="#F4EBD8",
            foreground="#111111",
            bordercolor=PALETTE["border"],
        )
        style.map(
            "TNotebook.Tab",
            background=[
                ("selected", "#FB923C"),
                ("active", "#F7D9B5"),
                ("!selected", "#F4EBD8"),
            ],
            foreground=[
                ("selected", "#111111"),
                ("active", "#111111"),
                ("disabled", "#111111"),
                ("!selected", "#111111"),
            ],
        )
        style.configure("Accent.TButton", font=("Malgun Gothic", 12, "bold"), foreground=PALETTE["text"])

    def _build_ui(self) -> None:
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root, padding=(16, 12, 16, 8))
        header.pack(fill="x")
        ttk.Label(header, text="\uc2a4\ud1a1 \uc5d0\uc774\uc804\ud2b8", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="\ucf54\uc2a4\ud53c\u00b7\ucf54\uc2a4\ub2e5\uacfc \ubbf8\uad6d\uc7a5\uc744 \ud55c \ud654\uba74\uc5d0\uc11c \uc2a4\ud06c\ub9ac\ub2dd\ud558\ub294 \ub370\uc2a4\ud06c\ud1b1 \ub3c4\uad6c",
            style="Sub.TLabel",
        ).pack(side="left", padx=(14, 0), pady=(8, 0))
        ttk.Label(header, textvariable=self.status_text, style="Status.TLabel").pack(side="right", pady=(8, 0))

        content = ttk.PanedWindow(root, orient="horizontal")
        content.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        sidebar = ttk.Frame(content, width=300)
        main = ttk.Frame(content)
        content.add(sidebar, weight=0)
        content.add(main, weight=1)

        self._build_sidebar(sidebar)
        self._build_main(main)
        self._build_bottom_status(root)

    def _build_bottom_status(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent, padding=(14, 0, 14, 10))
        bar.pack(fill="x")
        self.bottom_progress = ttk.Progressbar(bar, mode="determinate", maximum=100, value=0)
        self.bottom_progress.pack(side="left", fill="x", expand=True)
        ttk.Label(bar, textvariable=self.progress_text, style="Status.TLabel", width=62, anchor="e").pack(side="right", padx=(12, 0))

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, padding=(4, 0, 12, 0))
        frame.pack(fill="both", expand=True)

        market_box = ttk.LabelFrame(frame, text="\uc2dc\uc7a5 \uc120\ud0dd", padding=10)
        market_box.pack(fill="x")
        for label in MARKETS:
            button = ttk.Radiobutton(
                market_box,
                text=label,
                value=label,
                variable=self.current_market_label,
                command=self._on_market_changed,
            )
            button.pack(side="left", padx=(0, 12))
            self._add_tooltip(button, "\ubd84\uc11d\ud560 \uc2dc\uc7a5\uc744 \uc120\ud0dd")

        universe_label = ttk.Label(frame, text="\ubd84\uc11d \ub300\uc0c1")
        universe_label.pack(anchor="w", pady=(12, 3))
        self._add_tooltip(universe_label, "\uc2a4\ud06c\ub9ac\ub2dd\ud560 \uc885\ubaa9 \ubc94\uc704")
        self.universe_combo = ttk.Combobox(frame, textvariable=self.universe_label, state="readonly", style="Readable.TCombobox")
        self.universe_combo.pack(fill="x")
        self.universe_combo.bind("<<ComboboxSelected>>", self._on_universe_changed)
        self.option_add("*TCombobox*Listbox.background", PALETTE["surface"])
        self.option_add("*TCombobox*Listbox.foreground", PALETTE["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", PALETTE["selection"])
        self.option_add("*TCombobox*Listbox.selectForeground", PALETTE["accent"])
        self._add_tooltip(self.universe_combo, "\uc2a4\ud06c\ub9ac\ub2dd\ud560 \uc885\ubaa9 \ubc94\uc704")

        sector_box = ttk.LabelFrame(frame, text="\ubd84\uc57c(\uc139\ud130)", padding=8)
        sector_box.pack(fill="x", pady=(12, 0))
        sector_check = ttk.Checkbutton(
            sector_box,
            text="\ubd84\uc57c \ud544\ud130 \uc0ac\uc6a9",
            variable=self.sector_filter_enabled,
        )
        sector_check.pack(anchor="w")
        self._add_tooltip(sector_check, "\ud2b9\uc815 \uc5c5\uc885\ub9cc \uace8\ub77c \uc2a4\ud06c\ub9ac\ub2dd")
        self.sector_listbox = tk.Listbox(
            sector_box,
            selectmode="multiple",
            height=6,
            exportselection=False,
            font=("Malgun Gothic", 11),
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            selectbackground=PALETTE["selection"],
            selectforeground=PALETTE["accent"],
            highlightbackground=PALETTE["border"],
        )
        self.sector_listbox.pack(fill="x", pady=(6, 0))
        self._add_tooltip(self.sector_listbox, "\ud2b9\uc815 \uc5c5\uc885\ub9cc \uace8\ub77c \uc2a4\ud06c\ub9ac\ub2dd")

        top_label = ttk.Label(frame, text="\ucd94\ucc9c \uc885\ubaa9 \uc218")
        top_label.pack(anchor="w", pady=(12, 3))
        self._add_tooltip(top_label, "\uacb0\uacfc \uc0c1\uc704 \ud6c4\ubcf4\ub85c \ubf51\uc744 \uc885\ubaa9 \uac1c\uc218")
        top_spin = ttk.Spinbox(frame, from_=1, to=20, textvariable=self.top_n, width=8, style="Readable.TSpinbox")
        top_spin.pack(anchor="w")
        self._add_tooltip(top_spin, "\uacb0\uacfc \uc0c1\uc704 \ud6c4\ubcf4\ub85c \ubf51\uc744 \uc885\ubaa9 \uac1c\uc218")

        self._add_scale(frame, "\ucd5c\uc18c \uc810\uc218", self.min_score, 0, 100, 1, "\uc774 \uc810\uc218 \ubbf8\ub9cc \uc885\ubaa9\uc740 \ud6c4\ubcf4\uc5d0\uc11c \uc81c\uc678")
        self._add_scale(frame, "\uc218\ucd95\ud328\ud134 \ucd5c\uc18c \uc810\uc218", self.vcp_min_score, 0, 100, 5, "\ubcc0\ub3d9\uc131 \uc218\ucd95 \ud328\ud134 \ucd5c\uc18c \uc810\uc218")
        self._add_scale(frame, "\ucd5c\uc18c \uc190\uc775\ube44", self.min_risk_reward, 0.5, 3.0, 0.1, "\uae30\ub300\uc218\uc775 \ub300\ube44 \uc190\uc2e4\uc704\ud5d8 \uae30\uc900")

        regime_check = ttk.Checkbutton(frame, text="\uc2dc\uc7a5 \ubd84\uc704\uae30 \uac8c\uc774\ud2b8", variable=self.regime_gate)
        regime_check.pack(anchor="w", pady=(10, 0))
        self._add_tooltip(regime_check, "\ud558\ub77d\uc7a5\uc774\uba74 \ud6c4\ubcf4 \uc218\ub97c \uc904\uc5ec \ubcf4\uc218\uc801\uc73c\ub85c \uc120\ud0dd")
        sector_div_check = ttk.Checkbutton(frame, text="\uc139\ud130 \ubd84\uc0b0 \uc801\uc6a9", variable=self.sector_diversification)
        sector_div_check.pack(anchor="w", pady=(4, 0))
        self._add_tooltip(sector_div_check, "\uac19\uc740 \uc5c5\uc885 \uc885\ubaa9\uc774 \ubab0\ub9ac\uc9c0 \uc54a\uac8c \ubd84\uc0b0")
        full_col_check = ttk.Checkbutton(frame, text="\uc804\uccb4 \uceec\ub7fc \ubcf4\uae30", variable=self.show_full_columns, command=self._refresh_tables)
        full_col_check.pack(anchor="w", pady=(4, 0))
        self._add_tooltip(full_col_check, "\ud45c\uc5d0 \ubaa8\ub4e0 \uc0c1\uc138 \uceec\ub7fc \ud45c\uc2dc")

        run_box = ttk.LabelFrame(frame, text="\uc2e4\ud589", padding=10)
        run_box.pack(fill="x", pady=(16, 0))
        self.run_current_button = ttk.Button(run_box, text="\ud604\uc7ac \uc2dc\uc7a5 \uc2e4\ud589", command=lambda: self.run_market(self.current_market_label.get()))
        row = ttk.Frame(run_box)
        row.pack(fill="x")
        self.run_us_button = ttk.Button(row, text="\ubbf8\uad6d \uc2e4\ud589", command=lambda: self.run_market("\ubbf8\uad6d"))
        self.run_us_button.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.run_kr_button = ttk.Button(row, text="\ud55c\uad6d \uc2e4\ud589", command=lambda: self.run_market("\ud55c\uad6d"))
        self.run_kr_button.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.run_us_button.configure(text="\ubbf8\uad6d \uc2e4\ud589", command=lambda: self.run_market("\ubbf8\uad6d"))
        self.run_kr_button.configure(text="한국 실행", style="Accent.TButton", command=lambda: self.run_market("한국"))
        self._add_tooltip(self.run_kr_button, "코스피·코스닥 스크리닝 (세력·종합점수 자동 포함)")
        self._add_tooltip(self.run_us_button, "미국 시장 스크리닝")
        self.run_both_button = ttk.Button(run_box, text="전체 실행 (한국장→미국장)", command=self.run_both)
        self.run_both_button.pack(fill="x", pady=(8, 0))
        self._add_tooltip(self.run_both_button, "한국장 먼저, 이어서 미국장을 자동 실행")
        refresh_button = ttk.Button(run_box, text="결과 파일 새로고침", command=self._load_cached_results)
        refresh_button.pack(fill="x", pady=(8, 0))
        self._add_tooltip(refresh_button, "마지막으로 저장된 결과 파일을 다시 불러오기")
        folder_button = ttk.Button(run_box, text="\uacb0\uacfc \ud3f4\ub354 \uc5f4\uae30", command=self.open_output_folder)
        folder_button.pack(fill="x", pady=(8, 0))
        self._add_tooltip(folder_button, "\uacb0\uacfc \ud30c\uc77c\uc774 \uc800\uc7a5\ub41c \ud3f4\ub354\ub97c \uc5f4\uae30")
        manual_button = ttk.Button(run_box, text="매뉴얼 열기", command=self.open_manual_file)
        manual_button.pack(fill="x", pady=(8, 0))
        self._add_tooltip(manual_button, "사용법, 용어 해석, 점수 계산 기준을 HTML 매뉴얼로 열기")

        search_box = ttk.LabelFrame(frame, text="\uac80\uc0c9", padding=10)
        search_box.pack(fill="x", pady=(16, 0))
        search_entry = ttk.Entry(search_box, textvariable=self.search_text, style="Readable.TEntry")
        search_entry.pack(fill="x")
        search_entry.bind("<KeyRelease>", lambda _event: self._refresh_tables())
        self._add_tooltip(search_entry, "\uc885\ubaa9\uba85\uc774\ub098 \ud2f0\ucee4\ub85c \uacb0\uacfc \ud544\ud130")

        progress_box = ttk.LabelFrame(frame, text="\uc9c4\ud589 \uc0c1\ud0dc", padding=10)
        progress_box.pack(fill="both", expand=True, pady=(16, 0))
        self.progress = ttk.Progressbar(progress_box, mode="indeterminate")
        self.progress.pack(fill="x")
        ttk.Label(progress_box, textvariable=self.last_run_text, style="Sub.TLabel", wraplength=250).pack(anchor="w", pady=(8, 0))
        self.log_list = tk.Listbox(
            progress_box,
            height=12,
            activestyle="none",
            font=("Malgun Gothic", 11),
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            selectbackground=PALETTE["selection"],
            selectforeground=PALETTE["accent"],
            highlightbackground=PALETTE["border"],
        )
        self.log_list.pack(fill="both", expand=True, pady=(8, 0))

    def _add_scale(self, parent: ttk.Frame, label: str, variable, start, end, step, tooltip: str = "") -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(12, 0))
        value_label = ttk.Label(row, width=7)
        value_label.pack(side="right")
        label_widget = ttk.Label(row, text=label)
        label_widget.pack(side="left")
        if tooltip:
            self._add_tooltip(label_widget, tooltip)

        def update_label(*_args):
            value = variable.get()
            if isinstance(value, float):
                value_label.configure(text=f"{value:.1f}")
            else:
                value_label.configure(text=str(value))

        variable.trace_add("write", update_label)
        update_label()
        scale = ttk.Scale(parent, from_=start, to=end, variable=variable, orient="horizontal")
        scale.pack(fill="x")
        if tooltip:
            self._add_tooltip(scale, tooltip)
        if step != 1:
            scale.bind("<ButtonRelease-1>", lambda _event: variable.set(round(variable.get() / step) * step))

    def _build_main(self, parent: ttk.Frame) -> None:
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill="both", expand=True)

        self.top_tab = ttk.Frame(self.notebook, padding=8)
        self.full_tab = ttk.Frame(self.notebook, padding=8)
        self.detail_tab = ttk.Frame(self.notebook, padding=8)
        self.criteria_tab = ttk.Frame(self.notebook, padding=8)
        self.tracking_tab = ttk.Frame(self.notebook, padding=8)
        self.backtest_tab = ttk.Frame(self.notebook, padding=8)
        self.scheduler_tab = ttk.Frame(self.notebook, padding=8)
        self.telegram_tab = ttk.Frame(self.notebook, padding=8)
        self.summary_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.top_tab, text="\uc0c1\uc704 \ud6c4\ubcf4")
        self.notebook.add(self.full_tab, text="\uc804\uccb4 \uacb0\uacfc")
        self.notebook.add(self.detail_tab, text="\uc0c1\uc138/\ucc28\ud2b8")
        self.notebook.add(self.summary_tab, text="\uc694\uc57d")
        self.notebook.add(self.tracking_tab, text="성과 추적")
        self.notebook.add(self.backtest_tab, text="백데이터")

        self.notebook.add(self.criteria_tab, text="\uc810\uc218 \uae30\uc900")
        self.notebook.add(self.scheduler_tab, text="\uc2a4\ucf00\uc904")
        self.notebook.add(self.telegram_tab, text="텔레그램 전송")
        self._build_top_candidate_tabs()
        self.full_tree = self._build_tree(self.full_tab, TABLE_COLUMNS)
        self._build_detail_tab()
        self._build_tracking_tab()
        self._build_backtest_tab()
        self._build_criteria_tab()
        self._build_scheduler_tab()
        self._build_telegram_tab()
        self._build_summary_tab()

    def _build_top_candidate_tabs(self) -> None:
        self.top_candidate_notebook = ttk.Notebook(self.top_tab)
        self.top_candidate_notebook.pack(fill="both", expand=True)
        self.top_category_trees: dict[str, ttk.Treeview] = {}
        categories = [
            ("composite", "종합점수"),
            ("adjusted", "기존점수"),
            ("force", "세력"),
        ]
        for key, label in categories:
            tab = ttk.Frame(self.top_candidate_notebook, padding=4)
            self.top_candidate_notebook.add(tab, text=label)
            self.top_category_trees[key] = self._build_tree(tab, TABLE_COLUMNS)
        self.top_tree = self.top_category_trees["composite"]

    def _build_tree(self, parent: ttk.Frame, columns: list[tuple[str, str, int]]) -> ttk.Treeview:
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True)
        tree = ttk.Treeview(holder, columns=[col[0] for col in columns], show="headings", selectmode="browse")
        for key, label, width in columns:
            tree.heading(key, text=label, command=lambda c=key, t=tree: self._sort_tree(t, c))
            tree.column(key, width=width, anchor="center", stretch=True)
        y_scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        tree.bind("<<TreeviewSelect>>", self._on_row_selected)
        return tree

    def _build_detail_tab(self) -> None:
        container = ttk.PanedWindow(self.detail_tab, orient="horizontal")
        container.pack(fill="both", expand=True)
        left = ttk.Frame(container)
        right = ttk.Frame(container)
        container.add(left, weight=1)
        container.add(right, weight=2)

        self.detail_text = tk.Text(
            left,
            wrap="word",
            height=20,
            padx=10,
            pady=10,
            font=("Malgun Gothic", 11),
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
        )
        self.detail_text.pack(fill="both", expand=True)
        self.detail_text.configure(state="disabled")

        controls = ttk.Frame(right)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="\uc120\ud0dd \uc885\ubaa9 \ucc28\ud2b8 \uc0c8\ub85c\uace0\uce68", command=self._draw_selected_chart).pack(side="left")
        ttk.Label(controls, text="\uac00\uaca9 \ub370\uc774\ud130\ub294 yfinance\uc5d0\uc11c \uc0c8\ub85c \ubc1b\uc2b5\ub2c8\ub2e4.", style="Sub.TLabel").pack(side="left", padx=(12, 0))
        self.chart_frame = ttk.Frame(right)
        self.chart_frame.pack(fill="both", expand=True)

    def _build_tracking_tab(self) -> None:
        controls = ttk.Frame(self.tracking_tab)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="추적 새로고침", command=self.refresh_tracking_tab).pack(side="left")
        ttk.Button(controls, text="추적 업데이트", style="Accent.TButton", command=self.update_tracking_tab).pack(side="left", padx=(8, 0))
        body = ttk.PanedWindow(self.tracking_tab, orient="vertical")
        body.pack(fill="both", expand=True)
        top_area = ttk.PanedWindow(body, orient="horizontal")
        table_area = ttk.Frame(body)
        body.add(top_area, weight=2)
        body.add(table_area, weight=3)
        self.tracking_chart_frame = ttk.Frame(top_area)
        tracking_detail_frame = ttk.Frame(top_area)
        top_area.add(self.tracking_chart_frame, weight=2)
        top_area.add(tracking_detail_frame, weight=1)
        self.tracking_summary_text = tk.Text(
            tracking_detail_frame,
            height=12,
            wrap="word",
            padx=10,
            pady=10,
            font=("Malgun Gothic", 11),
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
        )
        self.tracking_summary_text.pack(fill="both", expand=True)
        self.tracking_summary_text.configure(state="disabled")
        self.tracking_tree = self._build_tree(table_area, TRACKING_COLUMNS)

    def _build_backtest_tab(self) -> None:
        controls = ttk.Frame(self.backtest_tab)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="추천 종목으로 백데이터 실행", style="Accent.TButton", command=self.run_backtest_tab).pack(side="left")
        ttk.Button(controls, text="결과 폴더 열기", command=self.open_output_folder).pack(side="left", padx=(8, 0))
        body = ttk.PanedWindow(self.backtest_tab, orient="vertical")
        body.pack(fill="both", expand=True)
        top_area = ttk.PanedWindow(body, orient="horizontal")
        table_area = ttk.Frame(body)
        body.add(top_area, weight=2)
        body.add(table_area, weight=3)
        self.backtest_chart_frame = ttk.Frame(top_area)
        backtest_detail_frame = ttk.Frame(top_area)
        top_area.add(self.backtest_chart_frame, weight=2)
        top_area.add(backtest_detail_frame, weight=1)
        self.backtest_summary_text = tk.Text(
            backtest_detail_frame,
            height=12,
            wrap="word",
            padx=10,
            pady=10,
            font=("Malgun Gothic", 11),
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
        )
        self.backtest_summary_text.pack(fill="both", expand=True)
        self.backtest_summary_text.configure(state="disabled")
        self.backtest_tree = self._build_tree(table_area, BACKTEST_COLUMNS)

    def _build_criteria_tab(self) -> None:
        container = ttk.PanedWindow(self.criteria_tab, orient="vertical")
        container.pack(fill="both", expand=True)

        top = ttk.Frame(container)
        bottom = ttk.Frame(container)
        container.add(top, weight=1)
        container.add(bottom, weight=1)

        self.criteria_text = tk.Text(
            top,
            wrap="word",
            height=14,
            padx=12,
            pady=12,
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
        )
        self.criteria_text.pack(fill="both", expand=True)
        self.criteria_text.configure(state="disabled")

        self.breakdown_tree = ttk.Treeview(
            bottom,
            columns=["item", "value"],
            show="headings",
            selectmode="none",
        )
        self.breakdown_tree.heading("item", text="\uc810\uc218 \ud56d\ubaa9")
        self.breakdown_tree.heading("value", text="\uc120\ud0dd \uc885\ubaa9 \uac12")
        self.breakdown_tree.column("item", width=260, anchor="w")
        self.breakdown_tree.column("value", width=180, anchor="center")
        self.breakdown_tree.pack(fill="both", expand=True)
        self._refresh_score_criteria()

    def _build_scheduler_tab(self) -> None:
        frame = ttk.Frame(self.scheduler_tab, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="권장 실행 시간", style="Title.TLabel").pack(anchor="w")
        lines = []
        for item in recommend_times():
            market_name = "한국장" if item.command_market == "kr" else "미국장"
            reason = "장 마감 직후 확인" if item.command_market == "kr" else "미국장 마감 후 확인"
            lines.append(f"{market_name}: 한국시간 {item.kst_time} / 인도네시아시간 {item.wib_time} - {reason}")
        ttk.Label(frame, text="\n".join(lines), style="Sub.TLabel", justify="left").pack(anchor="w", pady=(8, 16))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Button(row, text="스케줄 등록", style="Accent.TButton", command=self.register_scheduler_tasks).pack(side="left")
        ttk.Button(row, text="등록 해제", command=self.unregister_scheduler_tasks).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="상태 확인", command=self.check_scheduler_tasks).pack(side="left", padx=(8, 0))
        ttk.Label(frame, textvariable=self.schedule_status_text, style="Sub.TLabel", wraplength=900, justify="left").pack(anchor="w", fill="x", pady=(16, 0))
        self.schedule_status_text.set("등록 대상: 한국장 16:00, 미국장 08:00")

    def _refresh_score_criteria(self) -> None:
        if self.criteria_text is None:
            return
        config = self.current_config or {}
        filters = config.get("filters", {})
        screening = config.get("screening", {})
        ranking = config.get("ranking", {})
        vcp = config.get("vcp", {})
        lines = [
            "스크리닝 흐름",
            "1. 전체 유니버스를 로드합니다.",
            f"2. 유동성 기준을 먼저 적용합니다. 현재 기준: 최근 20일 평균 거래대금 {filters.get('min_avg_dollar_volume_20d', 0):,} 이상, 가격 {filters.get('min_price', 0):,} 이상, 이력 {filters.get('min_history_days', 0)}거래일 이상.",
            "3. 유동성 통과 종목만 차트 점수, 수축패턴, 상대강도, 세력유입 점수를 계산합니다.",
            f"4. 최종 후보는 최소 점수 {screening.get('min_score_for_candidate', 0)}점, 상대강도 {ranking.get('min_rs_rank', 0)} 이상, 수축패턴 {vcp.get('min_score', 0)} 이상을 우선 반영해 고릅니다.",
            "",
            "판정",
            "80점 이상: 강력 후보",
            "65점 이상: 후보",
            "50점 이상: 관찰",
            "50점 미만: 제외",
            "",
            "세력자료",
            "실수급 데이터가 없으면 가격과 거래량으로 세력유입을 추정합니다.",
        ]
        self.criteria_text.configure(state="normal")
        self.criteria_text.delete("1.0", "end")
        self.criteria_text.insert("1.0", "\n".join(lines))
        self.criteria_text.configure(state="disabled")

    def _refresh_score_breakdown(self, row: pd.Series | None = None) -> None:
        if self.breakdown_tree is None:
            return
        self.breakdown_tree.delete(*self.breakdown_tree.get_children())
        if row is None:
            return
        fields = {
            "trend_score": "추세 점수",
            "volume_score": "거래량 점수",
            "momentum_score": "모멘텀 점수",
            "macd_score": "맥디 점수",
            "position_score": "가격 위치 점수",
            "risk_reward_score": "손익비 점수",
            "risk_penalty": "위험 감점",
            "base_score": "기본 점수",
            "vcp_score": "수축패턴 점수",
            "rs_rank": "상대강도",
            "chart_type_penalty": "패턴 보너스/감점",
            "quality_penalty": "품질 감점",
            "final_score": "최종 점수",
            "adjusted_score": "조정 점수",
            "chart_score": "차트 점수",
            "force_inflow_pct": "세력유입%",
            "force_penalty": "분산 감점",
            "force_sequence": "\ud750\ub984 \ubcf4\ub108\uc2a4",
            "composite_score": "종합 점수",
        }
        for field, label in fields.items():
            if field in row:
                self.breakdown_tree.insert("", "end", values=(label, format_value(row.get(field))))

    def register_scheduler_tasks(self) -> None:
        try:
            results = register_recommended_tasks(APP_DIR)
            status = "\n".join((result.stdout or result.stderr or f"exit={result.returncode}").strip() for result in results)
            self.schedule_status_text.set(status or "\uc2a4\ucf00\uc904 \uc791\uc5c5\uc744 \ub4f1\ub85d\ud588\uc2b5\ub2c8\ub2e4.")
            self._append_log("\uc2a4\ucf00\uc904 \uc791\uc5c5 \ub4f1\ub85d \uc644\ub8cc")
        except Exception as exc:
            self.schedule_status_text.set(str(exc))
            messagebox.showerror("\uc2a4\ucf00\uc904", str(exc))

    def unregister_scheduler_tasks(self) -> None:
        try:
            results = unregister_recommended_tasks()
            status = "\n".join((result.stdout or result.stderr or f"exit={result.returncode}").strip() for result in results)
            self.schedule_status_text.set(status or "\uc2a4\ucf00\uc904 \uc791\uc5c5\uc744 \ud574\uc81c\ud588\uc2b5\ub2c8\ub2e4.")
            self._append_log("\uc2a4\ucf00\uc904 \uc791\uc5c5 \ud574\uc81c \uc644\ub8cc")
        except Exception as exc:
            self.schedule_status_text.set(str(exc))
            messagebox.showerror("\uc2a4\ucf00\uc904", str(exc))

    def check_scheduler_tasks(self) -> None:
        try:
            results = query_recommended_tasks()
            status = "\n\n".join((result.stdout or result.stderr or f"exit={result.returncode}").strip() for result in results)
            self.schedule_status_text.set(status or "\uc2a4\ucf00\uc904\ub7ec \uc0c1\ud0dc \ucd9c\ub825\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.")
        except Exception as exc:
            self.schedule_status_text.set(str(exc))
            messagebox.showerror("\uc2a4\ucf00\uc904", str(exc))

    def _build_telegram_tab(self) -> None:
        frame = ttk.Frame(self.telegram_tab, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="텔레그램 전송 설정", style="Title.TLabel").pack(anchor="w")

        form = ttk.LabelFrame(frame, text="봇 연결", padding=12)
        form.pack(fill="x", pady=(12, 0))
        ttk.Label(form, text="봇 토큰").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        token_entry = ttk.Entry(form, textvariable=self.telegram_bot_token, show="*", width=70, style="Readable.TEntry")
        token_entry.grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Label(form, text="채팅방 아이디").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        chat_entry = ttk.Entry(form, textvariable=self.telegram_chat_id, width=70, style="Readable.TEntry")
        chat_entry.grid(row=1, column=1, sticky="ew", pady=5)
        form.columnconfigure(1, weight=1)

        time_box = ttk.LabelFrame(frame, text="전송 시간", padding=12)
        time_box.pack(fill="x", pady=(12, 0))
        ttk.Label(time_box, text="한국장 전송 시간").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Entry(time_box, textvariable=self.telegram_kr_time, width=12, style="Readable.TEntry").grid(row=0, column=1, sticky="w", pady=5)
        ttk.Label(time_box, text="미국장 전송 시간").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Entry(time_box, textvariable=self.telegram_us_time, width=12, style="Readable.TEntry").grid(row=1, column=1, sticky="w", pady=5)

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="설정 저장", style="Accent.TButton", command=self.save_telegram_settings).pack(side="left")
        ttk.Button(actions, text="테스트 전송", command=self.send_telegram_test).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="텔레그램 스케줄 등록", command=self.register_telegram_scheduler_tasks).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="스케줄 해제", command=self.unregister_scheduler_tasks).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="상태 확인", command=self.check_scheduler_tasks).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="텔레그램 등록 방법", command=self.open_telegram_manual).pack(side="left", padx=(8, 0))

        ttk.Label(frame, textvariable=self.telegram_status_text, style="Sub.TLabel", wraplength=900, justify="left").pack(
            anchor="w", fill="x", pady=(14, 0)
        )
        self.telegram_status_text.set("봇 토큰과 채팅방 아이디를 저장한 뒤 테스트 전송을 눌러 확인하세요.")

    def _validate_time_text(self, value: str) -> str:
        text = value.strip()
        try:
            hour, minute = [int(part) for part in text.split(":", 1)]
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        except Exception:
            pass
        raise ValueError("시간은 HH:MM 형식으로 입력해야 합니다. 예: 16:00")

    def save_telegram_settings(self) -> None:
        try:
            kr_time = self._validate_time_text(self.telegram_kr_time.get())
            us_time = self._validate_time_text(self.telegram_us_time.get())
            token = self.telegram_bot_token.get().strip()
            chat_id = self.telegram_chat_id.get().strip()
            self.telegram_kr_time.set(kr_time)
            self.telegram_us_time.set(us_time)
            self.settings.setdefault("telegram", {})["bot_token"] = token
            self.settings.setdefault("telegram", {})["chat_id"] = chat_id
            self.settings["telegram_schedule"] = {"kr_time": kr_time, "us_time": us_time}
            save_desktop_settings(self.settings)
            save_env_values({"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat_id})
            self.telegram_status_text.set(".env와 desktop_config.json에 텔레그램 설정을 저장했습니다.")
            self._append_log("텔레그램 설정 저장 완료")
        except Exception as exc:
            self.telegram_status_text.set(str(exc))
            messagebox.showerror("텔레그램 설정", str(exc))

    def send_telegram_test(self) -> None:
        self.save_telegram_settings()
        token = self.telegram_bot_token.get().strip()
        chat_id = self.telegram_chat_id.get().strip()
        if not token or not chat_id:
            messagebox.showwarning("텔레그램 전송", "봇 토큰과 채팅방 아이디를 먼저 입력하세요.")
            return
        ok = send_text_messages("Stock Agent 텔레그램 테스트 전송입니다.", token, chat_id)
        text = "테스트 메시지를 전송했습니다." if ok else "테스트 전송에 실패했습니다. 토큰과 채팅방 아이디를 확인하세요."
        self.telegram_status_text.set(text)
        self._append_log(text)

    def register_telegram_scheduler_tasks(self) -> None:
        try:
            self.save_telegram_settings()
            kr_time = self._validate_time_text(self.telegram_kr_time.get())
            us_time = self._validate_time_text(self.telegram_us_time.get())
            results = [
                register_task(r"StockAgent\KR_1600", kr_time, "kr", project_dir=APP_DIR, notify="telegram"),
                register_task(r"StockAgent\US_0800", us_time, "us", project_dir=APP_DIR, notify="telegram"),
            ]
            status = "\n".join((result.stdout or result.stderr or f"exit={result.returncode}").strip() for result in results)
            self.telegram_status_text.set(status or "텔레그램 전송 스케줄을 등록했습니다.")
            self.schedule_status_text.set(self.telegram_status_text.get())
            self._append_log("텔레그램 전송 스케줄 등록 완료")
        except Exception as exc:
            self.telegram_status_text.set(str(exc))
            messagebox.showerror("텔레그램 스케줄", str(exc))

    def open_telegram_manual(self) -> None:
        TELEGRAM_MANUAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        TELEGRAM_MANUAL_PATH.write_text(TELEGRAM_MANUAL_HTML, encoding="utf-8")
        os.startfile(TELEGRAM_MANUAL_PATH)

    def open_manual_file(self) -> None:
        candidates = [MANUAL_PATH]
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / "매뉴얼.html")
        for path in candidates:
            if path.exists():
                os.startfile(path)
                return
        messagebox.showerror("매뉴얼", f"매뉴얼 파일을 찾지 못했습니다.\n\n{MANUAL_PATH}")

    def _build_summary_tab(self) -> None:
        top = ttk.Frame(self.summary_tab)
        top.pack(fill="x")
        ttk.Button(top, text="\uc694\uc57d \ud30c\uc77c \uc5f4\uae30", command=self.open_summary_file).pack(side="left")
        ttk.Button(top, text="\ud604\uc7ac \uc0c1\uc704 \ud6c4\ubcf4 \ud30c\uc77c \uc800\uc7a5", command=self.save_current_top_csv).pack(side="left", padx=(8, 0))
        self.summary_text = tk.Text(
            self.summary_tab,
            wrap="word",
            padx=10,
            pady=10,
            font=("Malgun Gothic", 11),
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
        )
        self.summary_text.pack(fill="both", expand=True, pady=(8, 0))
        self.summary_text.configure(state="disabled")

    def _on_market_changed(self) -> None:
        self._load_market_defaults()
        self._load_cached_results()

    def _settings_for_market(self, market_label: str) -> dict:
        return self.settings.setdefault("markets", {}).setdefault(market_label, {})

    def _save_current_market_settings(self) -> None:
        if not hasattr(self, "universe_combo"):
            return
        market = self.current_market_label.get()
        if market not in MARKETS:
            return
        region = MARKETS[market]["region"]
        label = self.universe_label.get()
        mode = UNIVERSE_OPTIONS.get(region, {}).get(label)
        if not mode:
            return
        market_settings = self._settings_for_market(market)
        market_settings["universe_mode"] = mode
        market_settings["universe_label"] = label
        save_desktop_settings(self.settings)

    def _on_universe_changed(self, _event=None) -> None:
        self._save_current_market_settings()
        self.status_text.set(f"\ubd84\uc11d \ub300\uc0c1 \uc800\uc7a5: {self.universe_label.get()}")
        self._refresh_summary()

    def _selected_sector_values(self) -> list[str]:
        if not hasattr(self, "sector_listbox"):
            return []
        return [self.sector_listbox.get(index) for index in self.sector_listbox.curselection()]

    def _set_sector_options(self, region: str, selected: list[str] | None = None) -> None:
        if not hasattr(self, "sector_listbox"):
            return
        self.sector_listbox.delete(0, "end")
        if region != "kr":
            self.sector_filter_enabled.set(False)
            self.sector_listbox.configure(state="disabled")
            return
        self.sector_listbox.configure(state="normal")
        selected_set = set(selected or [])
        for idx, sector in enumerate(STANDARD_SECTORS):
            self.sector_listbox.insert("end", sector)
            if sector in selected_set:
                self.sector_listbox.selection_set(idx)

    def _load_market_defaults(self) -> None:
        market = self.current_market_label.get()
        region = MARKETS[market]["region"]
        config = load_config(MARKETS[market]["config"])
        self.current_config = config
        options = list(UNIVERSE_OPTIONS[region].keys())
        self.universe_combo.configure(values=options)
        current_mode = config.get("universe", {}).get("mode")
        saved_mode = self._settings_for_market(market).get("universe_mode")
        if saved_mode in UNIVERSE_OPTIONS[region].values():
            current_mode = saved_mode
        current_label = next((label for label, mode in UNIVERSE_OPTIONS[region].items() if mode == current_mode), options[0])
        self.universe_label.set(current_label)
        sector_cfg = config.get("sector_filter", {})
        self.sector_filter_enabled.set(bool(sector_cfg.get("enabled", False)))
        self._set_sector_options(region, sector_cfg.get("include", []))
        self.top_n.set(int(config.get("screening", {}).get("top_n", 5)))
        self.min_score.set(float(config.get("screening", {}).get("min_score_for_candidate", 50)))
        self.vcp_min_score.set(float(config.get("vcp", {}).get("min_score", 70)))
        self.min_risk_reward.set(float(config.get("risk", {}).get("min_risk_reward", 1.2)))
        self.regime_gate.set(bool(config.get("regime", {}).get("enabled", True)))
        self._refresh_score_criteria()

    def _build_run_config(self, market_label: str) -> dict:
        region = MARKETS[market_label]["region"]
        config = deepcopy(load_config(MARKETS[market_label]["config"]))
        saved_mode = self._settings_for_market(market_label).get("universe_mode")
        if market_label == self.current_market_label.get():
            selected_universe = self.universe_label.get()
            selected_mode = UNIVERSE_OPTIONS[region].get(selected_universe, saved_mode)
        else:
            selected_mode = saved_mode
        if selected_mode not in UNIVERSE_OPTIONS[region].values():
            selected_mode = config.get("universe", {}).get("mode")
        if selected_mode not in UNIVERSE_OPTIONS[region].values():
            selected_mode = next(iter(UNIVERSE_OPTIONS[region].values()))
        config.setdefault("universe", {})["mode"] = selected_mode
        selected_label = next((label for label, mode in UNIVERSE_OPTIONS[region].items() if mode == selected_mode), selected_mode)
        self._settings_for_market(market_label)["universe_mode"] = selected_mode
        self._settings_for_market(market_label)["universe_label"] = selected_label
        save_desktop_settings(self.settings)
        config.setdefault("screening", {})["top_n"] = int(self.top_n.get())
        config["screening"]["min_score_for_candidate"] = int(self.min_score.get())
        config.setdefault("regime", {})["enabled"] = bool(self.regime_gate.get())
        config.setdefault("vcp", {})["min_score"] = int(self.vcp_min_score.get())
        config.setdefault("risk", {})["min_risk_reward"] = float(self.min_risk_reward.get())
        config.setdefault("portfolio", {})["max_per_sector"] = 2 if self.sector_diversification.get() else int(self.top_n.get())
        selected_sectors = self._selected_sector_values() if region == "kr" else []
        config.setdefault("sector_filter", {})["enabled"] = bool(region == "kr" and self.sector_filter_enabled.get() and selected_sectors)
        config["sector_filter"]["include"] = selected_sectors
        return config

    def run_current_market(self) -> None:
        self.run_market(self.current_market_label.get())

    def run_both(self) -> None:
        if self.running:
            messagebox.showinfo("\uc2e4\ud589 \uc911", "\uc774\ubbf8 \uc2a4\ud06c\ub9ac\ub2dd\uc774 \uc2e4\ud589 \uc911\uc785\ub2c8\ub2e4.")
            return
        self.running = True
        self._set_buttons_enabled(False)
        self.status_text.set("\uc804\uccb4 \uc2e4\ud589 \uc911: \ud55c\uad6d \ud6c4 \ubbf8\uad6d")
        self.progress_started_at = datetime.now()
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.bottom_progress.configure(maximum=100, value=0)
        self.progress_text.set("[1/2 \ud55c\uad6d] \uc900\ube44 \uc911")
        self._append_log("[1/2 한국] 스크리닝 시작")
        worker = threading.Thread(target=self._run_both_worker, daemon=True)
        worker.start()

    def run_market(self, market_label: str) -> None:
        if self.running:
            messagebox.showinfo("\uc2e4\ud589 \uc911", "\uc774\ubbf8 \uc2a4\ud06c\ub9ac\ub2dd\uc774 \uc2e4\ud589 \uc911\uc785\ub2c8\ub2e4.")
            return
        if market_label != self.current_market_label.get():
            self.current_market_label.set(market_label)
            self._load_market_defaults()
        self.running = True
        self._set_buttons_enabled(False)
        self.status_text.set(f"{market_label} \uc2a4\ud06c\ub9ac\ub2dd \uc2e4\ud589 \uc911")
        self.progress_started_at = datetime.now()
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.bottom_progress.configure(maximum=100, value=0)
        self.progress_text.set(f"[{market_label}] \uc900\ube44 \uc911")
        self._append_log(f"{market_label} 스크리닝 시작")
        config = self._build_run_config(market_label)
        worker = threading.Thread(target=self._run_worker, args=(market_label, config), daemon=True)
        worker.start()

    def _run_worker(self, market_label: str, config: dict) -> None:
        try:
            def progress(payload):
                payload = dict(payload)
                payload["label"] = market_label
                self.message_queue.put(("progress", payload))

            full_df, top_df, paths = run_screen(config=config, top_n=int(self.top_n.get()), progress_cb=progress)
            self.message_queue.put(("run_done", (market_label, full_df, top_df, paths)))
        except Exception as exc:
            self.message_queue.put(("run_error", (market_label, exc, traceback.format_exc())))

    def _run_both_worker(self) -> None:
        try:
            results = []
            for index, market_label in enumerate(["한국", "미국"], start=1):
                self.message_queue.put(("log", f"[{index}/2 {market_label}] 스크리닝 시작"))
                config = self._build_run_config(market_label)

                def progress(payload, market_label=market_label, index=index):
                    payload = dict(payload)
                    payload["label"] = f"{index}/2 {market_label}"
                    self.message_queue.put(("progress", payload))

                full_df, top_df, paths = run_screen(config=config, top_n=int(self.top_n.get()), progress_cb=progress)
                results.append((market_label, full_df, top_df, paths))
                self.message_queue.put(("log", f"[{index}/2 {market_label}] 스크리닝 완료"))
            self.message_queue.put(("both_done", results))
        except Exception as exc:
            self.message_queue.put(("run_error", ("전체 실행", exc, traceback.format_exc())))

    def _tracking_worker(self, market_label: str, region: str) -> None:
        try:
            updated = update_tracking_results(region)
            summary = summarize_tracking_performance(region)
            table = get_tracking_table(region)
            self.message_queue.put(("tracking_done", (market_label, updated, summary, table)))
        except Exception as exc:
            self.message_queue.put(("tracking_error", (market_label, exc, traceback.format_exc())))

    def _backtest_worker(self, market_label: str, region: str, config: dict, tickers: list[str], stats: dict) -> None:
        try:
            def progress(fraction: float, message: str) -> None:
                self.message_queue.put(
                    (
                        "progress",
                        {
                            "label": f"{market_label} 백데이터",
                            "stage": message,
                            "current": int(fraction * 100),
                            "total": 100,
                            "ticker": "",
                        },
                    )
                )

            trades, summary, equity = run_picks_backtest(
                tickers,
                config,
                market=region,
                top_n_per_day=int(self.top_n.get()),
                lookback_period=config.get("backtest", {}).get("lookback_period", "2y"),
                progress_cb=progress,
            )
            output_dir = Path(config.get("output", {}).get("output_dir", f"output/{region}"))
            output_dir.mkdir(parents=True, exist_ok=True)
            trades_path = output_dir / "backtest_trades.csv"
            equity_path = output_dir / "backtest_equity.csv"
            trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
            equity.to_csv(equity_path, index=False, encoding="utf-8-sig")
            self.message_queue.put(("backtest_done", (market_label, stats, summary, trades, equity, trades_path, equity_path)))
        except Exception as exc:
            self.message_queue.put(("backtest_error", (market_label, exc, traceback.format_exc())))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.message_queue.get_nowait()
                if kind == "run_done":
                    self._handle_run_done(*payload)
                elif kind == "both_done":
                    self._handle_both_done(payload)
                elif kind == "run_error":
                    self._handle_run_error(*payload)
                elif kind == "tracking_done":
                    self._handle_tracking_done(*payload)
                elif kind == "tracking_error":
                    self._handle_tracking_error(*payload)
                elif kind == "backtest_done":
                    self._handle_backtest_done(*payload)
                elif kind == "backtest_error":
                    self._handle_backtest_error(*payload)
                elif kind == "progress":
                    self._handle_progress(payload)
                elif kind == "log":
                    self._append_log(str(payload))
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def _handle_run_done(self, market_label: str, full_df: pd.DataFrame, top_df: pd.DataFrame, paths: dict) -> None:
        self.running = False
        self.progress.configure(value=100)
        self.bottom_progress.configure(value=100)
        self._set_buttons_enabled(True)
        self.current_market_label.set(market_label)
        self.full_df = full_df.copy()
        self.top_df = top_df.copy()
        self.paths = paths
        self.status_text.set(f"{market_label} \uc644\ub8cc: \uc0c1\uc704 \ud6c4\ubcf4 {len(self.top_df)}\uac1c")
        self.progress_text.set(f"{market_label} \uc644\ub8cc: \uc0c1\uc704 \ud6c4\ubcf4 {len(self.top_df)}\uac1c")
        self.last_run_text.set(f"최근 실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._append_log(f"{market_label} \uc644\ub8cc. \uc804\uccb4 {len(self.full_df)}\uac1c, \uc0c1\uc704 \ud6c4\ubcf4 {len(self.top_df)}\uac1c")
        self._refresh_tables()
        self._refresh_summary()

    def _handle_progress(self, payload: dict) -> None:
        current = int(payload.get("current") or 0)
        total = max(int(payload.get("total") or 1), 1)
        percent = max(0, min(100, int(current / total * 100)))
        label = payload.get("label") or payload.get("market") or ""
        stage = payload.get("stage") or ""
        ticker = payload.get("ticker") or ""
        ticker_text = f" · {ticker}" if ticker else ""
        elapsed = ""
        if self.progress_started_at:
            delta = datetime.now() - self.progress_started_at
            minutes, seconds = divmod(int(delta.total_seconds()), 60)
            elapsed = f" · 경과 {minutes}:{seconds:02d}"
        text = f"[{label}] {stage} {current} / {total} ({percent}%)" + ticker_text + elapsed
        self.progress.configure(maximum=total, value=current)
        self.bottom_progress.configure(maximum=total, value=current)
        self.status_text.set(text)
        self.progress_text.set(text)

    def _handle_both_done(self, results: list[tuple[str, pd.DataFrame, pd.DataFrame, dict]]) -> None:
        self.running = False
        self.progress.configure(value=100)
        self.bottom_progress.configure(value=100)
        self._set_buttons_enabled(True)
        market_label, full_df, top_df, paths = results[-1]
        self.current_market_label.set(market_label)
        self.full_df = full_df.copy()
        self.top_df = top_df.copy()
        self.paths = paths
        self.status_text.set("전체 실행 완료")
        self.progress_text.set("전체 실행 완료")
        self.last_run_text.set(f"최근 전체 실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._append_log("전체 실행 완료. 마지막 시장 결과를 표시합니다.")
        self._refresh_tables()
        self._refresh_summary()

    def _handle_run_error(self, market_label: str, exc: Exception, detail: str) -> None:
        self.running = False
        self.progress.configure(value=0)
        self.bottom_progress.configure(value=0)
        self._set_buttons_enabled(True)
        self.status_text.set(f"{market_label} 오류")
        self._append_log(f"오류: {exc}")
        messagebox.showerror("스크리닝 오류", f"{market_label} 실행 중 오류가 발생했습니다.\n\n{exc}")
        LOGGER.error("Screening failed\n%s", detail)

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def refresh_tracking_tab(self) -> None:
        market = self.current_market_label.get()
        region = MARKETS[market]["region"]
        summary = summarize_tracking_performance(region)
        table = get_tracking_table(region)
        self._set_text(self.tracking_summary_text, build_performance_summary_text(summary))
        self._fill_tree(self.tracking_tree, table)

    def update_tracking_tab(self) -> None:
        if self.running:
            messagebox.showinfo("실행 중", "현재 실행 중인 작업이 끝난 뒤 다시 시도하세요.")
            return
        market = self.current_market_label.get()
        region = MARKETS[market]["region"]
        self.running = True
        self._set_buttons_enabled(False)
        self.status_text.set(f"{market} 추천 성과 추적 업데이트 중")
        threading.Thread(target=self._tracking_worker, args=(market, region), daemon=True).start()

    def _handle_tracking_done(self, market_label: str, updated: int, summary: dict, table: pd.DataFrame) -> None:
        self.running = False
        self._set_buttons_enabled(True)
        text = build_performance_summary_text(summary) + f"\n\n이번 업데이트 행: {updated:,}개"
        self._set_text(self.tracking_summary_text, text)
        self._fill_tree(self.tracking_tree, table)
        self.status_text.set(f"{market_label} 추천 성과 추적 완료")
        self._append_log(f"{market_label} 추천 성과 추적 업데이트: {updated}개")

    def _handle_tracking_error(self, market_label: str, exc: Exception, detail: str) -> None:
        self.running = False
        self._set_buttons_enabled(True)
        self.status_text.set(f"{market_label} 추적 오류")
        self._append_log(f"추적 오류: {exc}")
        LOGGER.error("Tracking update failed\n%s", detail)
        messagebox.showerror("추천 성과 추적 오류", str(exc))

    def _recommended_backtest_tickers(self, region: str) -> tuple[list[str], dict]:
        if self.top_df is not None and not self.top_df.empty and "ticker" in self.top_df.columns:
            tickers = self.top_df["ticker"].dropna().astype(str).str.strip().tolist()
            tickers = list(dict.fromkeys(ticker for ticker in tickers if ticker))
            if tickers:
                return tickers, {"source_label": "현재 상위후보", "unique_tickers": len(tickers)}
        recent = get_recent_recommendations(limit=200)
        if not recent.empty and "market_region" in recent.columns:
            recent = recent[recent["market_region"].astype(str).eq(region)]
        tickers = recent.get("ticker", pd.Series(dtype=str)).dropna().astype(str).str.strip().tolist()
        tickers = list(dict.fromkeys(ticker for ticker in tickers if ticker))
        return tickers, {"source_label": "추천 이력", "unique_tickers": len(tickers)}

    def run_backtest_tab(self) -> None:
        if self.running:
            messagebox.showinfo("실행 중", "현재 실행 중인 작업이 끝난 뒤 다시 시도하세요.")
            return
        market = self.current_market_label.get()
        region = MARKETS[market]["region"]
        config = self._build_run_config(market)
        tickers, stats = self._recommended_backtest_tickers(region)
        if not tickers:
            messagebox.showinfo("백데이터 대상 없음", "먼저 스크리닝을 실행해 추천 종목을 만들거나 추천 이력을 저장하세요.")
            return
        self.running = True
        self._set_buttons_enabled(False)
        self.status_text.set(f"{market} 추천 종목 백데이터 실행 중")
        self._set_text(self.backtest_summary_text, f"{stats['source_label']} {len(tickers)}개 종목으로 백데이터를 실행하는 중입니다.")
        threading.Thread(target=self._backtest_worker, args=(market, region, config, tickers, stats), daemon=True).start()

    def _handle_backtest_done(
        self,
        market_label: str,
        stats: dict,
        summary: dict,
        trades: pd.DataFrame,
        equity: pd.DataFrame,
        trades_path: Path,
        equity_path: Path,
    ) -> None:
        self.running = False
        self._set_buttons_enabled(True)
        lines = [
            f"{market_label} 백데이터 결과",
            f"대상 기준: {stats.get('source_label', '추천 종목')}",
            f"대상 종목: {stats.get('unique_tickers', '-')}",
            f"거래 수: {summary.get('trade_count', 0)}",
            f"승률: {summary.get('win_rate', 0)}%",
            f"기대 R: {summary.get('expected_r', 0)}",
            f"수익 팩터: {summary.get('profit_factor', 0)}",
            f"최대낙폭: {summary.get('mdd', 0)}%",
            f"총 수익률: {summary.get('total_return_pct', 0)}%",
            f"지수 수익률: {summary.get('benchmark_return_pct', 0)}%",
            f"검증구간 거래/기대 R: {summary.get('oos_trade_count', 0)} / {summary.get('oos_expected_r', 0)}",
            "",
            f"거래 파일: {trades_path}",
            f"자산곡선 파일: {equity_path}",
        ]
        self._set_text(self.backtest_summary_text, "\n".join(lines))
        self._fill_tree(self.backtest_tree, trades.tail(200) if not trades.empty else trades)
        self._draw_backtest_chart(equity)
        self.status_text.set(f"{market_label} 백데이터 완료")
        self._append_log(f"{market_label} 백데이터 완료: 거래 {summary.get('trade_count', 0)}개")

    def _handle_backtest_error(self, market_label: str, exc: Exception, detail: str) -> None:
        self.running = False
        self._set_buttons_enabled(True)
        self.status_text.set(f"{market_label} 백데이터 오류")
        self._append_log(f"백데이터 오류: {exc}")
        LOGGER.error("Backtest failed\n%s", detail)
        messagebox.showerror("백데이터 오류", str(exc))

    def _set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in [self.run_current_button, self.run_us_button, self.run_kr_button, self.run_both_button]:
            button.configure(state=state)

    def _load_cached_results(self) -> None:
        market = self.current_market_label.get()
        region = MARKETS[market]["region"]
        config = load_config(MARKETS[market]["config"])
        output_cfg = config.get("output", {})
        full_path = Path(output_cfg.get("full_result_csv", f"output/{region}/full_result.csv"))
        top_path = Path(output_cfg.get("top5_csv", f"output/{region}/top5.csv"))
        self.full_df = read_csv_if_exists(full_path)
        self.top_df = read_csv_if_exists(top_path)
        self.paths = {"full_result_csv": str(full_path), "top5_csv": str(top_path)}
        if self.full_df.empty:
            self.status_text.set(f"{market} 저장 결과 없음")
            self._append_log(f"{market} 저장 결과 파일이 아직 없습니다.")
        else:
            if self.top_df.empty:
                self.top_df = self.full_df.head(int(self.top_n.get())).copy()
            self.status_text.set(f"{market} 저장 결과 로드")
            self._append_log(f"{market} \uc800\uc7a5 \uacb0\uacfc \ub85c\ub4dc: {len(self.full_df)}\uac1c")
        self._refresh_tables()
        self._refresh_summary()
        if hasattr(self, "tracking_tree"):
            self.refresh_tracking_tab()

    def _filtered_df(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        query = self.search_text.get().strip().lower()
        if not query:
            return df
        searchable = df.astype(str).agg(" ".join, axis=1).str.lower()
        return df[searchable.str.contains(query, na=False)]

    def _visible_columns(self, df: pd.DataFrame) -> list[tuple[str, str, int]]:
        if self.show_full_columns.get() or df.empty:
            return TABLE_COLUMNS
        return [col for col in TABLE_COLUMNS if col[0] in df.columns]

    def _ranked_top_df(self, score_column: str, fallback_column: str | None = None) -> pd.DataFrame:
        source = self.full_df if self.full_df is not None and not self.full_df.empty else self.top_df
        if source is None or source.empty:
            return pd.DataFrame()
        df = source.copy()
        sort_column = score_column if score_column in df.columns else fallback_column
        if not sort_column or sort_column not in df.columns:
            if self.top_df is not None and not self.top_df.empty:
                return self.top_df.copy()
            return df.head(int(self.top_n.get())).copy()
        df["_category_sort_score"] = pd.to_numeric(df[sort_column], errors="coerce").fillna(-1)
        sort_columns = ["_category_sort_score"]
        ascending = [False]
        for extra in ["risk_reward", "final_score"]:
            if extra in df.columns:
                helper = f"_sort_{extra}"
                df[helper] = pd.to_numeric(df[extra], errors="coerce").fillna(-1)
                sort_columns.append(helper)
                ascending.append(False)
        df = df.sort_values(sort_columns, ascending=ascending).head(int(self.top_n.get())).copy()
        helpers = [col for col in df.columns if col.startswith("_sort_") or col == "_category_sort_score"]
        return df.drop(columns=helpers)

    def _refresh_tables(self) -> None:
        category_defs = {
            "composite": ("composite_score", "adjusted_score"),
            "adjusted": ("adjusted_score", "final_score"),
            "force": ("force_inflow_pct", None),
        }
        for key, tree in getattr(self, "top_category_trees", {}).items():
            score_column, fallback_column = category_defs[key]
            df = self._ranked_top_df(score_column, fallback_column)
            self._fill_tree(tree, self._filtered_df(df))
        self._fill_tree(self.full_tree, self._filtered_df(self.full_df))

    def _fill_tree(self, tree: ttk.Treeview, df: pd.DataFrame) -> None:
        tree.delete(*tree.get_children())
        if df is None or df.empty:
            return
        columns = list(tree["columns"])
        for _, row in df.iterrows():
            values = [format_value(row.get(col)) for col in columns]
            tree.insert("", "end", values=values)

    def _sort_tree(self, tree: ttk.Treeview, column: str) -> None:
        idx = list(tree["columns"]).index(column)
        descending = not self.sort_state.get(column, False)
        self.sort_state[column] = descending
        rows = [(tree.set(child, column), child) for child in tree.get_children("")]
        rows.sort(key=lambda item: numeric_sort_value(item[0]), reverse=descending)
        for order, (_value, child) in enumerate(rows):
            tree.move(child, "", order)

    def _on_row_selected(self, event) -> None:
        tree = event.widget
        item = tree.focus()
        if not item:
            return
        values = tree.item(item, "values")
        columns = list(tree["columns"])
        row = dict(zip(columns, values))
        ticker = row.get("ticker", "")
        if hasattr(self, "tracking_tree") and tree == self.tracking_tree:
            self._show_tracking_chart(row)
            return
        source = self.full_df
        if not source.empty and ticker:
            matched = source[source["ticker"].astype(str) == str(ticker)]
            if not matched.empty:
                self._show_detail(matched.iloc[0])
                self.notebook.select(self.detail_tab)
                self._draw_chart_for_ticker(ticker)

    def _show_detail(self, row: pd.Series) -> None:
        lines = []
        for key, label in DETAIL_FIELDS:
            if key in row:
                lines.append(f"{label}: {format_value(row.get(key))}")
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", "\n\n".join(lines))
        self.detail_text.configure(state="disabled")
        self._refresh_score_breakdown(row)

    def _draw_selected_chart(self) -> None:
        active_tree = self.full_tree if self.full_tree.focus() else None
        if active_tree is None:
            for tree in getattr(self, "top_category_trees", {}).values():
                if tree.focus():
                    active_tree = tree
                    break
        item = active_tree.focus() if active_tree is not None else ""
        if not item:
            messagebox.showinfo("종목 선택", "차트를 볼 종목을 먼저 선택하세요.")
            return
        values = active_tree.item(item, "values")
        row = dict(zip(active_tree["columns"], values))
        ticker = row.get("ticker")
        if ticker:
            self._draw_chart_for_ticker(ticker)

    def _draw_backtest_chart(self, equity: pd.DataFrame) -> None:
        if Figure is None or FigureCanvasTkAgg is None or not hasattr(self, "backtest_chart_frame"):
            return
        for child in self.backtest_chart_frame.winfo_children():
            child.destroy()
        if equity is None or equity.empty or "equity" not in equity.columns:
            ttk.Label(self.backtest_chart_frame, text="백데이터 그래프를 표시할 거래가 없습니다.").pack(anchor="w")
            return
        chart_df = equity.copy()
        if "date" in chart_df.columns:
            chart_df["date"] = pd.to_datetime(chart_df["date"], errors="coerce")
            chart_df = chart_df.dropna(subset=["date"]).sort_values("date")
            x_values = chart_df["date"]
        else:
            x_values = chart_df.index
        strategy = pd.to_numeric(chart_df["equity"], errors="coerce")
        if strategy.dropna().empty:
            ttk.Label(self.backtest_chart_frame, text="백데이터 그래프를 표시할 자산 데이터가 없습니다.").pack(anchor="w")
            return

        fig = Figure(figsize=(7.0, 3.8), dpi=100)
        fig.patch.set_facecolor(PALETTE["surface"])
        ax = fig.add_subplot(1, 1, 1)
        ax.set_facecolor(PALETTE["surface"])
        ax.plot(x_values, strategy, label="전략 자산", color=PALETTE["accent"], linewidth=1.7)
        if "benchmark_equity" in chart_df.columns:
            index_series = pd.to_numeric(chart_df["benchmark_equity"], errors="coerce")
            if not index_series.dropna().empty:
                ax.plot(x_values, index_series, label="지수", color="#60A5FA", linewidth=1.3, linestyle="--")
        ax.set_title("백데이터 자산 흐름")
        ax.set_ylabel("자산")
        ax.title.set_color(PALETTE["text"])
        ax.yaxis.label.set_color(PALETTE["muted"])
        ax.tick_params(colors=PALETTE["muted"])
        ax.grid(True, color=PALETTE["border"], alpha=0.45)
        for spine in ax.spines.values():
            spine.set_color(PALETTE["border"])
        legend = ax.legend(loc="best", fontsize=8)
        if legend:
            legend.get_frame().set_facecolor(PALETTE["surface2"])
            legend.get_frame().set_edgecolor(PALETTE["border"])
            for text in legend.get_texts():
                text.set_color(PALETTE["text"])
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=self.backtest_chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def _show_tracking_chart(self, row: dict) -> None:
        if Figure is None or FigureCanvasTkAgg is None:
            return
        for child in self.tracking_chart_frame.winfo_children():
            child.destroy()
        ticker = str(row.get("ticker", "")).strip()
        run_date_text = str(row.get("run_date", "")).strip()
        if not ticker or not run_date_text:
            ttk.Label(self.tracking_chart_frame, text="추적 차트를 볼 추천 행을 선택하세요.").pack(anchor="w")
            return
        loading = ttk.Label(self.tracking_chart_frame, text=f"{ticker} 추천 이후 차트 로딩 중...")
        loading.pack(anchor="w")
        self.update_idletasks()
        df = fetch_ohlcv(ticker, period="6mo", interval="1d", timeout=60)
        loading.destroy()
        if df is None or df.empty:
            ttk.Label(self.tracking_chart_frame, text=f"{ticker} 가격 데이터를 가져오지 못했습니다.").pack(anchor="w")
            return
        run_date = pd.to_datetime(run_date_text, errors="coerce")
        if pd.isna(run_date):
            ttk.Label(self.tracking_chart_frame, text="추천일을 해석하지 못했습니다.").pack(anchor="w")
            return
        chart_df = df.copy()
        chart_df.index = pd.to_datetime(chart_df.index).tz_localize(None)
        chart_df = chart_df[chart_df.index.normalize() >= run_date.normalize()].head(35)
        if chart_df.empty:
            ttk.Label(self.tracking_chart_frame, text="추천일 이후 가격 데이터가 아직 없습니다.").pack(anchor="w")
            return

        entry = numeric_sort_value(row.get("entry_price"))
        target1 = numeric_sort_value(row.get("target1_price"))
        target2 = numeric_sort_value(row.get("target2_price"))
        stop = numeric_sort_value(row.get("stop_price"))
        fig = Figure(figsize=(7.0, 3.8), dpi=100)
        fig.patch.set_facecolor(PALETTE["surface"])
        ax = fig.add_subplot(1, 1, 1)
        ax.set_facecolor(PALETTE["surface"])
        ax.plot(chart_df.index, chart_df["Close"], label="종가", color=PALETTE["text"], linewidth=1.5)
        levels = [
            (entry, "추천가", PALETTE["accent"]),
            (target1, "1차 목표", PALETTE["positive"]),
            (target2, "2차 목표", "#60A5FA"),
            (stop, "손절가", PALETTE["negative"]),
        ]
        for value, label, color in levels:
            if isinstance(value, (int, float)):
                ax.axhline(value, color=color, linestyle="--", linewidth=1.0, label=f"{label} {value:,.2f}")
        ax.set_title(f"{ticker} 추천일 이후 흐름")
        ax.title.set_color(PALETTE["text"])
        ax.tick_params(colors=PALETTE["muted"])
        ax.grid(True, color=PALETTE["border"], alpha=0.45)
        for spine in ax.spines.values():
            spine.set_color(PALETTE["border"])
        legend = ax.legend(loc="best", fontsize=8)
        if legend:
            legend.get_frame().set_facecolor(PALETTE["surface2"])
            legend.get_frame().set_edgecolor(PALETTE["border"])
            for text in legend.get_texts():
                text.set_color(PALETTE["text"])
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=self.tracking_chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

        details = [
            f"종목: {ticker}",
            f"추천일: {run_date_text}",
            f"추천가: {format_value(row.get('entry_price'))}",
            f"현재 추적일: {format_value(row.get('tracking_date'))}",
            f"수익률: {format_value(row.get('return_pct'))}%",
            f"최고/최저: {format_value(row.get('max_return_pct'))}% / {format_value(row.get('min_return_pct'))}%",
            f"첫 도달: {format_value(row.get('first_hit'))}",
            f"상태: {format_value(row.get('status'))}",
            f"다음날 시초가 갭: {format_value(row.get('next_open_gap_pct'))}%",
        ]
        self._set_text(self.tracking_summary_text, "\n".join(details))

    def _draw_chart_for_ticker(self, ticker: str) -> None:
        if Figure is None or FigureCanvasTkAgg is None:
            return
        for child in self.chart_frame.winfo_children():
            child.destroy()
        loading = ttk.Label(self.chart_frame, text=f"{ticker} 차트 로딩 중...")
        loading.pack(anchor="w")
        self.update_idletasks()
        market = self.current_market_label.get()
        config = self._build_run_config(market)
        data_cfg = config.get("data", {})
        df = fetch_ohlcv(
            ticker,
            period=data_cfg.get("period", "1y"),
            interval=data_cfg.get("interval", "1d"),
            timeout=int(data_cfg.get("request_timeout_seconds", 600)),
        )
        loading.destroy()
        if df.empty:
            ttk.Label(self.chart_frame, text=f"{ticker} 가격 데이터를 가져오지 못했습니다.").pack(anchor="w")
            return
        try:
            chart_df = add_indicators(df.copy())
        except Exception:
            chart_df = df.copy()
            chart_df["MA20"] = chart_df["Close"].rolling(20).mean()
            chart_df["MA50"] = chart_df["Close"].rolling(50).mean()
        fig = Figure(figsize=(8.5, 5.2), dpi=100)
        fig.patch.set_facecolor(PALETTE["surface"])
        ax_price = fig.add_subplot(2, 1, 1)
        ax_volume = fig.add_subplot(2, 1, 2, sharex=ax_price)
        for axis in [ax_price, ax_volume]:
            axis.set_facecolor(PALETTE["surface"])
            axis.tick_params(colors=PALETTE["muted"])
            axis.grid(True, color=PALETTE["border"], alpha=0.45)
            for spine in axis.spines.values():
                spine.set_color(PALETTE["border"])
        ax_price.plot(chart_df.index, chart_df["Close"], label="종가", color=PALETTE["text"], linewidth=1.4)
        ma_labels = {"MA20": "20일선", "ma20": "20일선", "MA50": "50일선", "ma50": "50일선"}
        for col, color in [("MA20", PALETTE["accent"]), ("ma20", PALETTE["accent"]), ("MA50", PALETTE["positive"]), ("ma50", PALETTE["positive"])]:
            if col in chart_df.columns:
                ax_price.plot(chart_df.index, chart_df[col], label=ma_labels[col], color=color, linewidth=1.0)
        ax_price.set_title(str(ticker))
        ax_price.title.set_color(PALETTE["text"])
        legend = ax_price.legend(loc="upper left")
        if legend:
            legend.get_frame().set_facecolor(PALETTE["surface2"])
            legend.get_frame().set_edgecolor(PALETTE["border"])
            for text in legend.get_texts():
                text.set_color(PALETTE["text"])
        if "Volume" in chart_df.columns:
            ax_volume.bar(chart_df.index, chart_df["Volume"], color=PALETTE["muted"], width=1.0)
            ax_volume.set_ylabel("\uac70\ub798\ub7c9")
            ax_volume.yaxis.label.set_color(PALETTE["muted"])
        fig.tight_layout()
        self.chart_canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        self.chart_canvas.draw()
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True)

    def _refresh_summary(self) -> None:
        stats = self.paths.get("stats", {}) if isinstance(self.paths, dict) else {}
        lines = []
        market = self.current_market_label.get()
        lines.append(f"\uc2dc\uc7a5: {market}")
        if stats:
            summary_steps = []
            if "scored_result_count" in stats:
                summary_steps.append(f"\uc2e0\ud638 \uacc4\uc0b0 \uacb0\uacfc: {stats.get('scored_result_count', '-')}")
            if "candidate_after_rs_filter" in stats:
                summary_steps.append(f"\uc0c1\ub300\uac15\ub3c4 \ubc18\uc601 \ud6c4: {stats.get('candidate_after_rs_filter', '-')}")
            if "candidate_after_vcp_filter" in stats:
                summary_steps.append(f"\uc218\ucd95\ud328\ud134 \ubc18\uc601 \ud6c4: {stats.get('candidate_after_vcp_filter', '-')}")
            if "candidate_after_score_gate" in stats:
                summary_steps.append(f"\ucd5c\uc18c\uc810\uc218 \ud1b5\uacfc: {stats.get('candidate_after_score_gate', '-')}")
            if stats.get("force_real_fetch_mode"):
                summary_steps.append(str(stats.get("force_real_fetch_mode")))
            if "force_real_fetch_count" in stats:
                summary_steps.append(f"\uc2e4\uc218\uae09 \ud655\uc778 \uc131\uacf5: {stats.get('force_real_fetch_count', 0)}")
            if stats.get("rs_filter_note"):
                summary_steps.append(str(stats.get("rs_filter_note")))
            if stats.get("vcp_filter_note"):
                summary_steps.append(str(stats.get("vcp_filter_note")))
            lines.append(f"\uc720\ub2c8\ubc84\uc2a4: {format_value(stats.get('universe_label', '-'))}")
            lines.append(f"\uc804\uccb4 \ub85c\ub4dc \uc885\ubaa9: {stats.get('unique_tickers', '-')}")
            lines.append(f"\uc720\ub3d9\uc131 \ud1b5\uacfc: {stats.get('passed_liquidity_filter', '-')}")
            lines.append(f"\ucd5c\uc885 \ud6c4\ubcf4: {stats.get('selected_top_candidates', len(self.top_df))}")
            lines.extend(summary_steps)
            lines.append(f"\uc2dc\uc7a5 \ubd84\uc704\uae30: {format_value(stats.get('market_regime', '-'))}")
            lines.append(f"\uc2dc\uc7a5 \ucf54\uba58\ud2b8: {format_value(stats.get('market_comment', '-'))}")
        else:
            try:
                _, universe_stats = load_universe(self._build_run_config(market))
                lines.append(f"\uc720\ub2c8\ubc84\uc2a4: {format_value(universe_stats.get('universe_label', '-'))}")
                lines.append(f"\uc804\uccb4 \ub85c\ub4dc \uc885\ubaa9: {universe_stats.get('unique_tickers', '-')}")
            except Exception:
                pass
            lines.append(f"\uc800\uc7a5 \uacb0\uacfc: \uc804\uccb4 {len(self.full_df)}\uac1c / \uc0c1\uc704 \ud6c4\ubcf4 {len(self.top_df)}\uac1c")
        if self.paths:
            lines.append("")
            lines.append("\ud30c\uc77c")
            for key, value in self.paths.items():
                if key != "stats":
                    lines.append(f"- {key}: {value}")
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", "\n".join(lines))
        self.summary_text.configure(state="disabled")

    def save_current_top_csv(self) -> None:
        if self.top_df.empty:
            messagebox.showinfo("저장할 데이터 없음", "현재 상위 후보 데이터가 없습니다.")
            return
        default_name = f"상위후보_{self.current_market_label.get()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(
            initialdir=APP_DIR / "output",
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("결과 파일", "*.csv")],
        )
        if path:
            self.top_df.to_csv(path, index=False, encoding="utf-8-sig")
            self._append_log(f"결과 파일 저장: {path}")

    def open_output_folder(self) -> None:
        market = self.current_market_label.get()
        region = MARKETS[market]["region"]
        folder = APP_DIR / "output" / region
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def open_summary_file(self) -> None:
        summary = self.paths.get("summary_txt") or self.paths.get("performance_summary_txt")
        if summary and Path(summary).exists():
            os.startfile(Path(summary))
            return
        self.open_output_folder()

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_list.insert("end", f"[{stamp}] {message}")
        self.log_list.yview_moveto(1.0)


def main() -> int:
    setup_logging()
    if any(arg.startswith("--") for arg in sys.argv[1:]):
        return run_from_args(parse_args())
    app = StockAgentDesktop()
    app.mainloop()
    return 0


def write_startup_error(exc: Exception) -> None:
    log_path = APP_DIR / "error.log"
    try:
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        log_path = Path("error.log")
        try:
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "실행 오류",
            f"프로그램 시작 중 오류가 발생했습니다.\n\n{exc}\n\n상세 내용: {log_path}",
        )
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        write_startup_error(exc)
        raise SystemExit(1)
