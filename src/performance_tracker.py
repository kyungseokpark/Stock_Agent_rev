"""SQLite-backed recommendation history and optional tracking foundation."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from .data_loader import fetch_ohlcv


DB_PATH = Path("data/screener_history.db")


RECOMMENDATION_COLUMNS = [
    "run_date",
    "market_region",
    "universe_mode",
    "ticker",
    "name",
    "source",
    "score",
    "adjusted_score",
    "decision",
    "chart_type",
    "entry_price",
    "stop_price",
    "target1_price",
    "target2_price",
    "risk_reward",
    "rsi",
    "volume_ratio",
    "is_sample_data",
    "data_source",
    "data_quality",
    "passed_liquidity_filter",
    "liquidity_warning",
    "passed_risk_reward_filter",
    "risk_reward_warning",
]


def init_history_db(db_path: str | Path = DB_PATH) -> Path:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT NOT NULL,
                market_region TEXT NOT NULL,
                universe_mode TEXT NOT NULL,
                ticker TEXT NOT NULL,
                name TEXT,
                source TEXT,
                score REAL,
                adjusted_score REAL,
                decision TEXT,
                chart_type TEXT,
                entry_price REAL,
                stop_price REAL,
                target1_price REAL,
                target2_price REAL,
                risk_reward REAL,
                rsi REAL,
                volume_ratio REAL,
                is_sample_data INTEGER,
                data_source TEXT,
                data_quality TEXT,
                passed_liquidity_filter INTEGER,
                liquidity_warning TEXT,
                passed_risk_reward_filter INTEGER,
                risk_reward_warning TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(run_date, market_region, ticker)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracking_results (
                recommendation_id INTEGER,
                ticker TEXT,
                run_date TEXT,
                tracking_date TEXT,
                days_after INTEGER,
                close_price REAL,
                high_price REAL,
                low_price REAL,
                return_pct REAL,
                max_return_pct REAL,
                min_return_pct REAL,
                hit_stop INTEGER,
                hit_target1 INTEGER,
                hit_target2 INTEGER,
                first_hit TEXT,
                status TEXT,
                next_open_price REAL,
                next_open_gap_pct REAL,
                updated_at TEXT,
                PRIMARY KEY (recommendation_id, days_after)
            )
            """
        )
    return path


def _value(row: pd.Series, *names: str):
    for name in names:
        if name in row and pd.notna(row[name]):
            value = row[name]
            if isinstance(value, bool):
                return int(value)
            return value
    return None


def _recommendation_record(run_date: str, market_region: str, universe_mode: str, row: pd.Series) -> dict:
    return {
        "run_date": run_date,
        "market_region": market_region,
        "universe_mode": universe_mode,
        "ticker": _value(row, "ticker"),
        "name": _value(row, "name"),
        "source": _value(row, "source"),
        "score": _value(row, "score", "final_score"),
        "adjusted_score": _value(row, "adjusted_score"),
        "decision": _value(row, "decision"),
        "chart_type": _value(row, "chart_type"),
        "entry_price": _value(row, "current_price"),
        "stop_price": _value(row, "stop_loss"),
        "target1_price": _value(row, "target1"),
        "target2_price": _value(row, "target2"),
        "risk_reward": _value(row, "risk_reward"),
        "rsi": _value(row, "rsi14"),
        "volume_ratio": _value(row, "volume_ratio"),
        "is_sample_data": int(bool(_value(row, "is_sample_data"))),
        "data_source": _value(row, "data_source"),
        "data_quality": _value(row, "data_quality"),
        "passed_liquidity_filter": int(bool(_value(row, "passed_liquidity_filter"))),
        "liquidity_warning": _value(row, "liquidity_warning"),
        "passed_risk_reward_filter": int(bool(_value(row, "passed_risk_reward_filter"))),
        "risk_reward_warning": _value(row, "risk_reward_warning"),
    }


def save_recommendations(
    run_date: str,
    market_region: str,
    universe_mode: str,
    top5_df: pd.DataFrame,
    db_path: str | Path = DB_PATH,
) -> int:
    init_history_db(db_path)
    if top5_df.empty:
        return 0

    created_at = datetime.now().isoformat(timespec="seconds")
    records = []
    for _, row in top5_df.drop_duplicates("ticker").iterrows():
        record = _recommendation_record(run_date, market_region, universe_mode, row)
        record["created_at"] = created_at
        records.append(record)

    placeholders = ", ".join([":" + col for col in RECOMMENDATION_COLUMNS] + [":created_at"])
    columns = ", ".join(RECOMMENDATION_COLUMNS + ["created_at"])
    sql = f"INSERT INTO recommendations ({columns}) VALUES ({placeholders})"

    with sqlite3.connect(db_path) as conn:
        existing_tickers = {
            str(row[0])
            for row in conn.execute(
                "SELECT ticker FROM recommendations WHERE run_date = ? AND market_region = ?",
                (run_date, market_region),
            ).fetchall()
        }
        new_records = [record for record in records if str(record["ticker"]) not in existing_tickers]
        if not new_records:
            return 0
        before = conn.total_changes
        conn.executemany(sql, new_records)
        return conn.total_changes - before


def get_recent_recommendations(limit: int = 100, db_path: str | Path = DB_PATH) -> pd.DataFrame:
    init_history_db(db_path)
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(
            "SELECT * FROM recommendations ORDER BY run_date DESC, created_at DESC, id DESC LIMIT ?",
            conn,
            params=(limit,),
        )


def _to_float(value, default: float | None = None) -> float | None:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_hit_for_day(low_price: float, high_price: float, stop_price: float | None, target1: float | None, target2: float | None) -> str:
    hit_stop = stop_price is not None and low_price <= stop_price
    hit_target2 = target2 is not None and high_price >= target2
    hit_target1 = target1 is not None and high_price >= target1
    if hit_stop and (hit_target1 or hit_target2):
        return "ambiguous"
    if hit_stop:
        return "stop_first"
    if hit_target2:
        return "target2_first"
    if hit_target1:
        return "target1_first"
    return "none"


def calculate_forward_returns(recommendation: pd.Series | dict, ohlcv: pd.DataFrame, max_days: int = 10) -> list[dict]:
    rec = pd.Series(recommendation)
    entry_price = _to_float(rec.get("entry_price"))
    if not entry_price or entry_price <= 0 or ohlcv.empty:
        return []

    run_date = pd.to_datetime(rec.get("run_date")).tz_localize(None)
    bars = ohlcv.copy()
    bars.index = pd.to_datetime(bars.index).tz_localize(None)
    bars = bars[bars.index.normalize() > run_date.normalize()].head(max_days)
    if bars.empty:
        return []

    stop_price = _to_float(rec.get("stop_price"))
    target1 = _to_float(rec.get("target1_price"))
    target2 = _to_float(rec.get("target2_price"))
    next_open = _to_float(bars.iloc[0].get("Open"))
    next_open_gap = ((next_open / entry_price - 1) * 100) if next_open else None

    rows = []
    first_hit = "none"
    cumulative_high = None
    cumulative_low = None
    for day, (tracking_date, bar) in enumerate(bars.iterrows(), start=1):
        close_price = _to_float(bar.get("Close"))
        high_price = _to_float(bar.get("High"))
        low_price = _to_float(bar.get("Low"))
        if close_price is None or high_price is None or low_price is None:
            continue

        cumulative_high = high_price if cumulative_high is None else max(cumulative_high, high_price)
        cumulative_low = low_price if cumulative_low is None else min(cumulative_low, low_price)
        day_hit = _first_hit_for_day(low_price, high_price, stop_price, target1, target2)
        if first_hit == "none" and day_hit != "none":
            first_hit = day_hit

        rows.append(
            {
                "recommendation_id": int(rec.get("id")),
                "ticker": rec.get("ticker"),
                "run_date": str(rec.get("run_date")),
                "tracking_date": tracking_date.strftime("%Y-%m-%d"),
                "days_after": day,
                "close_price": round(close_price, 4),
                "high_price": round(high_price, 4),
                "low_price": round(low_price, 4),
                "return_pct": round((close_price / entry_price - 1) * 100, 4),
                "max_return_pct": round((cumulative_high / entry_price - 1) * 100, 4),
                "min_return_pct": round((cumulative_low / entry_price - 1) * 100, 4),
                "hit_stop": int(stop_price is not None and cumulative_low <= stop_price),
                "hit_target1": int(target1 is not None and cumulative_high >= target1),
                "hit_target2": int(target2 is not None and cumulative_high >= target2),
                "first_hit": first_hit,
                "status": "completed" if day >= max_days else "tracking",
                "next_open_price": round(next_open, 4) if next_open else None,
                "next_open_gap_pct": round(next_open_gap, 4) if next_open_gap is not None else None,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
    if rows and len(rows) < max_days:
        rows[-1]["status"] = "tracking"
    return rows


def update_tracking_results(
    market_region: str | None = None,
    db_path: str | Path = DB_PATH,
    max_days: int = 10,
) -> int:
    init_history_db(db_path)
    where = ""
    params: tuple = ()
    if market_region:
        where = "WHERE market_region = ?"
        params = (market_region,)
    with sqlite3.connect(db_path) as conn:
        recommendations = pd.read_sql_query(
            f"SELECT * FROM recommendations {where} ORDER BY run_date DESC, id DESC",
            conn,
            params=params,
        )
    if recommendations.empty:
        return 0

    rows = []
    for _, rec in recommendations.iterrows():
        df = fetch_ohlcv(str(rec["ticker"]), period="3mo", interval="1d")
        rows.extend(calculate_forward_returns(rec, df, max_days=max_days))

    if not rows:
        return 0

    columns = list(rows[0].keys())
    placeholders = ", ".join(":" + col for col in columns)
    assignments = ", ".join(f"{col}=excluded.{col}" for col in columns if col not in {"recommendation_id", "days_after"})
    sql = (
        f"INSERT INTO tracking_results ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(recommendation_id, days_after) DO UPDATE SET {assignments}"
    )
    with sqlite3.connect(db_path) as conn:
        before = conn.total_changes
        conn.executemany(sql, rows)
        return conn.total_changes - before


def get_tracking_table(market_region: str | None = None, db_path: str | Path = DB_PATH) -> pd.DataFrame:
    init_history_db(db_path)
    where = ""
    params: tuple = ()
    if market_region:
        where = "WHERE r.market_region = ?"
        params = (market_region,)
    query = f"""
        SELECT
            r.run_date,
            r.market_region,
            r.universe_mode,
            r.ticker,
            r.name,
            r.entry_price,
            r.target1_price,
            r.target2_price,
            r.stop_price,
            r.data_quality,
            r.liquidity_warning,
            r.risk_reward_warning,
            t.days_after,
            t.tracking_date,
            t.close_price,
            t.return_pct,
            t.max_return_pct,
            t.min_return_pct,
            t.hit_target1,
            t.hit_target2,
            t.hit_stop,
            t.first_hit,
            t.status,
            t.next_open_price,
            t.next_open_gap_pct
        FROM recommendations r
        LEFT JOIN tracking_results t ON r.id = t.recommendation_id
        {where}
        ORDER BY r.run_date DESC, r.id DESC, t.days_after DESC
    """
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(query, conn, params=params)


def summarize_tracking_performance(market_region: str | None = None, db_path: str | Path = DB_PATH) -> dict:
    table = get_tracking_table(market_region, db_path)
    if table.empty or table["days_after"].dropna().empty:
        return {
            "completed_count": 0,
            "tracking_count": 0,
            "avg_5d_return": None,
            "avg_10d_return": None,
            "target1_hit_rate": None,
            "stop_hit_rate": None,
            "ambiguous_rate": None,
            "message": "아직 10거래일 성과 데이터가 충분하지 않습니다.",
        }

    latest = table.dropna(subset=["days_after"]).sort_values(["run_date", "ticker", "days_after"]).groupby(
        ["run_date", "market_region", "ticker"], as_index=False
    ).tail(1)
    day5 = table[table["days_after"].eq(5)]
    day10 = table[table["days_after"].eq(10)]
    completed = latest[latest["status"].eq("completed")]
    tracking = latest[latest["status"].eq("tracking")]

    def pct(series: pd.Series) -> float | None:
        if series.empty:
            return None
        return round(float(series.mean()), 2)

    return {
        "completed_count": int(len(completed)),
        "tracking_count": int(len(tracking)),
        "avg_5d_return": pct(day5["return_pct"].dropna()),
        "avg_10d_return": pct(day10["return_pct"].dropna()),
        "target1_hit_rate": pct(latest["hit_target1"].dropna() * 100),
        "stop_hit_rate": pct(latest["hit_stop"].dropna() * 100),
        "ambiguous_rate": pct(latest["first_hit"].eq("ambiguous").astype(float) * 100),
        "message": "",
    }


def build_performance_summary_text(summary: dict) -> str:
    if summary.get("message"):
        return "[추천 성과 추적]\n" + summary["message"]
    return "\n".join(
        [
            "[추천 성과 추적]",
            f"최근 완료 추천 수: {summary.get('completed_count', 0)}개",
            f"추적 중인 추천: {summary.get('tracking_count', 0)}개",
            f"평균 5일 수익률: {summary.get('avg_5d_return') if summary.get('avg_5d_return') is not None else '-'}%",
            f"평균 10일 수익률: {summary.get('avg_10d_return') if summary.get('avg_10d_return') is not None else '-'}%",
            f"1차 목표가 누적 터치율: {summary.get('target1_hit_rate') if summary.get('target1_hit_rate') is not None else '-'}%",
            f"손절 누적 터치율: {summary.get('stop_hit_rate') if summary.get('stop_hit_rate') is not None else '-'}%",
            f"최초 동시터치 비율: {summary.get('ambiguous_rate') if summary.get('ambiguous_rate') is not None else '-'}%",
            "이 수익률은 실제 체결 수익률이 아니라 추천 기준가 대비 사후 추적 수익률입니다. 슬리피지, 매수 시점, 수수료, 환율은 반영하지 않았습니다.",
        ]
    )
