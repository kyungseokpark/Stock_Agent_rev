"""Stable Korean market universe fallbacks for MVP screening."""

from __future__ import annotations

import io
import contextlib
import re
import time
from pathlib import Path

import pandas as pd
import requests


DATA_DIR = Path("data")
KR_UNIVERSE_CSV = DATA_DIR / "universe_kr.csv"
KR_NAVER_CSV = DATA_DIR / "universe_kr_naver.csv"
KOSPI_CSV = DATA_DIR / "universe_kospi.csv"
KOSDAQ_CSV = DATA_DIR / "universe_kosdaq.csv"
TICKERS_KR_CSV = Path("tickers_kr.csv")

EXCLUDE_KEYWORDS = [
    "ETF",
    "ETN",
    "KODEX",
    "TIGER",
    "ACE",
    "SOL",
    "HANARO",
    "ARIRANG",
    "KBSTAR",
    "히어로즈",
    "스팩",
    "SPAC",
    "우선주",
    "리츠",
]

DEFAULT_KR_UNIVERSE_CSV = """ticker,name,market
005930,삼성전자,KOSPI
000660,SK하이닉스,KOSPI
373220,LG에너지솔루션,KOSPI
207940,삼성바이오로직스,KOSPI
005380,현대차,KOSPI
000270,기아,KOSPI
068270,셀트리온,KOSPI
005490,POSCO홀딩스,KOSPI
035420,NAVER,KOSPI
035720,카카오,KOSPI
105560,KB금융,KOSPI
055550,신한지주,KOSPI
086790,하나금융지주,KOSPI
316140,우리금융지주,KOSPI
032830,삼성생명,KOSPI
000810,삼성화재,KOSPI
012330,현대모비스,KOSPI
028260,삼성물산,KOSPI
009540,HD한국조선해양,KOSPI
329180,HD현대중공업,KOSPI
010140,삼성중공업,KOSPI
042660,한화오션,KOSPI
034020,두산에너빌리티,KOSPI
267260,HD현대일렉트릭,KOSPI
000720,현대건설,KOSPI
047040,대우건설,KOSPI
006400,삼성SDI,KOSPI
051910,LG화학,KOSPI
096770,SK이노베이션,KOSPI
011170,롯데케미칼,KOSPI
010950,S-Oil,KOSPI
009830,한화솔루션,KOSPI
010130,고려아연,KOSPI
000100,유한양행,KOSPI
128940,한미약품,KOSPI
326030,SK바이오팜,KOSPI
302440,SK바이오사이언스,KOSPI
017670,SK텔레콤,KOSPI
030200,KT,KOSPI
032640,LG유플러스,KOSPI
066570,LG전자,KOSPI
011070,LG이노텍,KOSPI
034730,SK,KOSPI
003550,LG,KOSPI
086280,현대글로비스,KOSPI
018260,삼성에스디에스,KOSPI
003670,포스코퓨처엠,KOSPI
009150,삼성전기,KOSPI
011200,HMM,KOSPI
003490,대한항공,KOSPI
021240,코웨이,KOSPI
004020,현대제철,KOSPI
010120,LS ELECTRIC,KOSPI
000150,두산,KOSPI
241560,두산밥캣,KOSPI
006800,미래에셋증권,KOSPI
039490,키움증권,KOSPI
071050,한국금융지주,KOSPI
138040,메리츠금융지주,KOSPI
024110,기업은행,KOSPI
015760,한국전력,KOSPI
033780,KT&G,KOSPI
090430,아모레퍼시픽,KOSPI
161390,한국타이어앤테크놀로지,KOSPI
271560,오리온,KOSPI
097950,CJ제일제당,KOSPI
000120,CJ대한통운,KOSPI
035250,강원랜드,KOSPI
251270,넷마블,KOSPI
352820,하이브,KOSPI
259960,크래프톤,KOSPI
006260,LS,KOSPI
267250,HD현대,KOSPI
012450,한화에어로스페이스,KOSPI
047810,한국항공우주,KOSPI
272210,한화시스템,KOSPI
011790,SKC,KOSPI
247540,에코프로비엠,KOSDAQ
086520,에코프로,KOSDAQ
196170,알테오젠,KOSDAQ
214150,클래시스,KOSDAQ
145020,휴젤,KOSDAQ
028300,HLB,KOSDAQ
141080,리가켐바이오,KOSDAQ
277810,레인보우로보틱스,KOSDAQ
039030,이오테크닉스,KOSDAQ
058470,리노공업,KOSDAQ
036930,주성엔지니어링,KOSDAQ
240810,원익IPS,KOSDAQ
095340,ISC,KOSDAQ
293490,카카오게임즈,KOSDAQ
112040,위메이드,KOSDAQ
263750,펄어비스,KOSDAQ
067310,하나마이크론,KOSDAQ
222800,심텍,KOSDAQ
084370,유진테크,KOSDAQ
078600,대주전자재료,KOSDAQ
121600,나노신소재,KOSDAQ
403870,HPSP,KOSDAQ
089030,테크윙,KOSDAQ
"""


def normalize_kr_ticker_for_yfinance(ticker, market: str) -> str:
    raw = str(ticker).strip().upper()
    if raw.endswith(".KS") or raw.endswith(".KQ"):
        return raw
    digits = re.sub(r"\D", "", raw).zfill(6)
    suffix = ".KQ" if str(market).upper() == "KOSDAQ" else ".KS"
    return f"{digits}{suffix}"


def add_yfinance_suffix(df: pd.DataFrame) -> pd.DataFrame:
    out = clean_kr_universe(df)
    if out.empty:
        return out
    out["ticker"] = [normalize_kr_ticker_for_yfinance(t, m) for t, m in zip(out["ticker"], out["market"])]
    return out


def clean_kr_universe(df: pd.DataFrame) -> pd.DataFrame:
    columns = ["ticker", "name", "market", "source", "sector"]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    out = df.copy()
    out["ticker"] = out["ticker"].astype(str).str.extract(r"(\d{1,6})", expand=False).fillna("").str.zfill(6)
    out["name"] = out["name"].astype(str).str.strip() if "name" in out.columns else out["ticker"]
    out["market"] = out["market"].astype(str).str.strip().str.upper() if "market" in out.columns else "KOSPI"
    out["source"] = out["source"].astype(str).str.strip() if "source" in out.columns else ""
    out["sector"] = out["sector"].astype(str).str.strip() if "sector" in out.columns else ""

    out = out[out["ticker"].str.match(r"^\d{6}$")]
    out = out[out["market"].isin(["KOSPI", "KOSDAQ"])]
    exclude_pattern = "|".join(re.escape(keyword) for keyword in EXCLUDE_KEYWORDS)
    out = out[~out["name"].str.contains(exclude_pattern, case=False, na=False)]
    out = out[~out["name"].str.endswith(("우", "우B", "우선주"), na=False)]
    return out[columns].drop_duplicates("ticker").reset_index(drop=True)


def _save_kr_csv(df: pd.DataFrame, path: Path, *, yfinance_ticker: bool = False) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = add_yfinance_suffix(df) if yfinance_ticker else clean_kr_universe(df)
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return out


def create_default_kr_universe_csv(path: str | Path = KR_UNIVERSE_CSV) -> pd.DataFrame:
    print("[WARN] 외부 한국장 universe 수집 실패. 기본 내장 100개 대표 종목 리스트를 사용합니다.")
    df = pd.read_csv(io.StringIO(DEFAULT_KR_UNIVERSE_CSV), dtype={"ticker": str})
    df["source"] = "default_kr"
    df["sector"] = ""
    _save_kr_csv(df, Path(path))
    return clean_kr_universe(df)


def load_kr_universe_csv(path: str | Path = KR_UNIVERSE_CSV) -> pd.DataFrame:
    csv_path = Path(path)
    if not csv_path.exists():
        return create_default_kr_universe_csv(csv_path)
    return clean_kr_universe(pd.read_csv(csv_path, dtype={"ticker": str}))


def fetch_naver_market_sum(market: str, pages: int = 40, sleep_seconds: float = 0.35) -> pd.DataFrame:
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:
        raise RuntimeError("beautifulsoup4가 설치되어 있지 않습니다. python -m pip install beautifulsoup4 를 실행하세요.") from exc

    market = market.upper()
    sosok = "0" if market == "KOSPI" else "1"
    source = "naver_kospi" if market == "KOSPI" else "naver_kosdaq"
    rows = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        )
    }

    for page in range(1, pages + 1):
        url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            response.encoding = "euc-kr"
            soup = BeautifulSoup(response.text, "html.parser")
            page_rows = 0
            for link in soup.select("a[href*='code=']"):
                href = link.get("href", "")
                name = link.get_text(strip=True)
                match = re.search(r"code=(\d{6})", href)
                if not name or not match:
                    continue
                rows.append(
                    {
                        "ticker": match.group(1),
                        "name": name,
                        "market": market,
                        "source": source,
                        "sector": "",
                    }
                )
                page_rows += 1
            if page_rows == 0 and page > 1:
                break
        except Exception as exc:
            print(f"[WARN] Naver Finance {market} page {page} fetch failed: {exc}")
            if page == 1:
                raise
            continue
        time.sleep(sleep_seconds)

    return clean_kr_universe(pd.DataFrame(rows))


def fetch_naver_kr_universe(kospi_pages: int = 40, kosdaq_pages: int = 40) -> pd.DataFrame:
    print("trying Naver Finance fallback...")
    kospi = fetch_naver_market_sum("KOSPI", kospi_pages)
    kosdaq = fetch_naver_market_sum("KOSDAQ", kosdaq_pages)
    df = clean_kr_universe(pd.concat([kospi, kosdaq], ignore_index=True))
    if df.empty:
        raise RuntimeError("Naver Finance universe result is empty.")
    _save_kr_csv(df, KR_NAVER_CSV)
    return df


def fetch_pykrx_kr_universe() -> pd.DataFrame:
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        try:
            from pykrx import stock
        except Exception as exc:
            raise RuntimeError("pykrx가 설치되어 있지 않습니다. python -m pip install pykrx 를 실행하세요.") from exc

        # TODO: 안정적인 네트워크 환경에서 pykrx 기반 전체 KRX universe 자동 갱신 기능 재검토
        rows = []
        for market in ["KOSPI", "KOSDAQ"]:
            tickers = stock.get_market_ticker_list(market=market)
            source = "kospi" if market == "KOSPI" else "kosdaq"
            for ticker in tickers:
                rows.append(
                    {
                        "ticker": str(ticker).zfill(6),
                        "name": stock.get_market_ticker_name(ticker),
                        "market": market,
                        "source": source,
                        "sector": "",
                    }
                )
    df = clean_kr_universe(pd.DataFrame(rows))
    if df.empty:
        raise RuntimeError("pykrx Korean universe result is empty.")
    return df


def _load_existing_kospi_kosdaq_csv() -> pd.DataFrame:
    frames = []
    for path, source in [(KOSPI_CSV, "kospi"), (KOSDAQ_CSV, "kosdaq")]:
        if path.exists():
            df = pd.read_csv(path, dtype={"ticker": str})
            if "source" not in df.columns:
                df["source"] = source
            if "sector" not in df.columns:
                df["sector"] = ""
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return clean_kr_universe(pd.concat(frames, ignore_index=True))


def _load_custom_kr_only(custom_path: str | Path = TICKERS_KR_CSV) -> pd.DataFrame:
    path = Path(custom_path)
    if not path.exists():
        return create_default_kr_universe_csv(KR_UNIVERSE_CSV)
    df = pd.read_csv(path, dtype={"ticker": str})
    if "source" not in df.columns:
        df["source"] = "custom_kr"
    if "sector" not in df.columns:
        df["sector"] = ""
    return clean_kr_universe(df)


def get_krx_universe_with_fallback(
    csv_path: str | Path = KR_UNIVERSE_CSV,
    try_pykrx: bool = True,
    try_naver: bool = True,
    kospi_pages: int = 40,
    kosdaq_pages: int = 40,
) -> pd.DataFrame:
    if try_pykrx:
        try:
            df = fetch_pykrx_kr_universe()
            _save_kr_csv(df, Path(csv_path))
            return df
        except Exception as exc:
            print(f"pykrx failed: {exc}")

    if try_naver:
        try:
            df = fetch_naver_kr_universe(kospi_pages=kospi_pages, kosdaq_pages=kosdaq_pages)
            _save_kr_csv(df, Path(csv_path))
            return df
        except Exception as exc:
            print(f"naver fallback failed: {exc}")

    existing = _load_existing_kospi_kosdaq_csv()
    if not existing.empty:
        print("using existing universe CSV files...")
        _save_kr_csv(existing, Path(csv_path))
        return existing

    csv_path = Path(csv_path)
    if csv_path.exists():
        print(f"using existing {csv_path}...")
        return load_kr_universe_csv(csv_path)

    print("existing universe CSV not found.")
    print("using tickers_kr.csv only.")
    print("KOSPI/KOSDAQ 전체 목록을 가져오지 못해 custom_kr 관심종목만 사용합니다.")
    custom = _load_custom_kr_only()
    _save_kr_csv(custom, csv_path)
    return custom
