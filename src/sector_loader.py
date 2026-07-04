"""KR sector map loading, caching, and standardization."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

LOGGER = logging.getLogger(__name__)
SECTOR_MAP_PATH = Path("data/sector_map_kr.csv")
TAXONOMY_PATH = Path("data/sector_taxonomy.yaml")
STANDARD_SECTORS = [
    "의약·바이오",
    "헬스케어·의료기기",
    "반도체",
    "2차전지·소재",
    "IT·소프트웨어",
    "자동차·부품",
    "금융",
    "화학·에너지",
    "조선·기계·방산",
    "소비재·유통",
    "기타",
]


def _normalize_kr_ticker(ticker, market: str | None = None) -> str:
    raw = str(ticker).strip().upper()
    if raw.endswith(".KS") or raw.endswith(".KQ"):
        return raw
    digits = raw.zfill(6) if raw.isdigit() else raw
    market_upper = str(market or "").strip().upper()
    if len(digits) == 6 and digits.isdigit():
        suffix = ".KQ" if market_upper == "KOSDAQ" else ".KS"
        return f"{digits}{suffix}"
    return raw


def _load_taxonomy(path: str | Path = TAXONOMY_PATH) -> tuple[dict[str, list[str]], str]:
    file_path = Path(path)
    if not file_path.exists():
        return {}, "기타"
    data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    return data.get("sector_keywords", {}), data.get("fallback_sector", "기타")


def standardize_sector(raw_sector: str, raw_industry: str = "") -> str:
    keywords, fallback = _load_taxonomy()
    haystack = f"{raw_sector or ''} {raw_industry or ''}".lower()
    for standard, terms in keywords.items():
        for term in terms or []:
            if str(term).lower() in haystack:
                return standard
    return fallback


def _fresh_enough(path: Path, refresh_days: int) -> bool:
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age <= timedelta(days=max(1, int(refresh_days)))


def _ticker_base(ticker: str) -> str:
    return str(ticker).strip().upper().replace(".KS", "").replace(".KQ", "").zfill(6)


def _fetch_pykrx_sector_map() -> pd.DataFrame:
    from pykrx import stock

    today = datetime.now().strftime("%Y%m%d")
    frames = []
    for market in ["KOSPI", "KOSDAQ"]:
        raw = stock.get_market_sector_classifications(today, market)
        if raw is None or raw.empty:
            continue
        df = raw.reset_index().copy()
        rename = {}
        for col in df.columns:
            text = str(col).lower()
            if text in {"ticker", "티커", "종목코드"} or "티커" in text or "코드" in text:
                rename[col] = "raw_ticker"
            elif text in {"name", "종목명"} or "종목" in text:
                rename[col] = "name"
            elif "업종" in text or "sector" in text:
                rename[col] = "industry"
        df = df.rename(columns=rename)
        if "raw_ticker" not in df.columns:
            df = df.rename(columns={df.columns[0]: "raw_ticker"})
        if "industry" not in df.columns:
            candidates = [c for c in df.columns if c not in {"raw_ticker", "name"}]
            df["industry"] = df[candidates[0]] if candidates else ""
        df["market"] = market
        df["ticker"] = [_normalize_kr_ticker(t, market) for t in df["raw_ticker"]]
        df["sector"] = [standardize_sector(ind, ind) for ind in df["industry"].fillna("")]
        df["sector_source"] = "pykrx"
        df["updated_at"] = datetime.now().isoformat(timespec="seconds")
        df["ticker_base"] = df["ticker"].map(_ticker_base)
        frames.append(df[["ticker", "ticker_base", "sector", "industry", "sector_source", "updated_at"]])
    if not frames:
        return pd.DataFrame(columns=["ticker", "ticker_base", "sector", "industry", "sector_source", "updated_at"])
    return pd.concat(frames, ignore_index=True).drop_duplicates("ticker")


def _fetch_naver_sector_map() -> pd.DataFrame:
    import requests
    from bs4 import BeautifulSoup

    base_url = "https://finance.naver.com"
    headers = {"User-Agent": "Mozilla/5.0"}
    index_url = f"{base_url}/sise/sise_group.naver?type=upjong"
    response = requests.get(index_url, headers=headers, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    groups: list[tuple[str, str]] = []
    for link in soup.select('a[href*="sise_group_detail.naver?type=upjong"]'):
        raw_industry = link.get_text(strip=True)
        href = link.get("href", "")
        if raw_industry and href:
            groups.append((raw_industry, href.replace("&amp;", "&")))
    rows = []
    seen_codes: set[tuple[str, str]] = set()
    for raw_industry, href in groups:
        sector = standardize_sector(raw_industry, raw_industry)
        for page in range(1, 31):
            sep = "&" if "?" in href else "?"
            url = f"{base_url}{href}{sep}page={page}"
            detail = requests.get(url, headers=headers, timeout=15)
            detail.raise_for_status()
            detail_soup = BeautifulSoup(detail.text, "html.parser")
            page_codes = []
            for item in detail_soup.select('a[href*="/item/main.naver?code="]'):
                href_text = item.get("href", "")
                code = href_text.split("code=")[-1].split("&")[0].strip()
                name = item.get_text(strip=True)
                if len(code) != 6 or not code.isdigit():
                    continue
                key = (raw_industry, code)
                if key in seen_codes:
                    continue
                seen_codes.add(key)
                page_codes.append(code)
                rows.append(
                    {
                        "ticker": code,
                        "ticker_base": code,
                        "sector": sector,
                        "industry": raw_industry,
                        "sector_source": "naver",
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                        "name": name,
                    }
                )
            if not page_codes:
                break
    if not rows:
        return pd.DataFrame(columns=["ticker", "ticker_base", "sector", "industry", "sector_source", "updated_at"])
    return pd.DataFrame(rows).drop_duplicates("ticker_base")[["ticker", "ticker_base", "sector", "industry", "sector_source", "updated_at"]]


def build_kr_sector_map(force_refresh: bool = False, refresh_days: int = 7) -> pd.DataFrame:
    if not force_refresh and _fresh_enough(SECTOR_MAP_PATH, refresh_days):
        return pd.read_csv(SECTOR_MAP_PATH, dtype={"ticker": str, "ticker_base": str})
    for source_name, fetcher in [("pykrx", _fetch_pykrx_sector_map), ("naver", _fetch_naver_sector_map)]:
        try:
            df = fetcher()
            if not df.empty:
                SECTOR_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(SECTOR_MAP_PATH, index=False, encoding="utf-8-sig")
                return df
        except Exception as exc:  # pragma: no cover - external provider dependent
            LOGGER.warning("Failed to refresh KR sector map from %s: %s", source_name, exc)
    if SECTOR_MAP_PATH.exists():
        LOGGER.warning("Using existing KR sector map after refresh failure: %s", SECTOR_MAP_PATH)
        return pd.read_csv(SECTOR_MAP_PATH, dtype={"ticker": str, "ticker_base": str})
    return pd.DataFrame(columns=["ticker", "ticker_base", "sector", "industry", "sector_source", "updated_at"])


def attach_sectors(universe_df: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    if universe_df.empty:
        return universe_df.copy()
    config = config or {}
    sector_cfg = config.get("sector_filter", {})
    refresh_days = int(sector_cfg.get("refresh_days", 7))
    sector_map = build_kr_sector_map(force_refresh=bool(sector_cfg.get("force_refresh", False)), refresh_days=refresh_days)
    out = universe_df.copy()
    if sector_map.empty:
        out["sector"] = out.get("sector", "").fillna("").replace("", "기타")
        out["industry"] = out.get("industry", "") if "industry" in out.columns else ""
        out["sector_source"] = out.get("sector_source", "") if "sector_source" in out.columns else ""
        return out
    out["ticker_base"] = out["ticker"].map(_ticker_base)
    sector_map = sector_map.copy()
    if "ticker_base" not in sector_map.columns:
        sector_map["ticker_base"] = sector_map["ticker"].map(_ticker_base)
    else:
        sector_map["ticker_base"] = sector_map["ticker_base"].map(_ticker_base)
    merged = out.merge(sector_map, on="ticker_base", how="left", suffixes=("", "_mapped"))
    existing_sector = merged["sector"] if "sector" in merged.columns else pd.Series("", index=merged.index)
    mapped_sector = merged["sector_mapped"] if "sector_mapped" in merged.columns else pd.Series("", index=merged.index)
    merged["sector"] = mapped_sector.fillna("").replace("", pd.NA).fillna(existing_sector).fillna("기타")
    if "industry" not in merged.columns:
        merged["industry"] = ""
    if "sector_source" not in merged.columns:
        merged["sector_source"] = ""
    drop_cols = [c for c in ["sector_mapped", "ticker_mapped"] if c in merged.columns]
    return merged.drop(columns=drop_cols)


def apply_sector_filter(universe_df: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    config = config or {}
    sector_cfg = config.get("sector_filter", {})
    include = [str(value) for value in sector_cfg.get("include", []) if str(value).strip()]
    if not bool(sector_cfg.get("enabled", False)) or not include:
        return universe_df
    return universe_df[universe_df["sector"].isin(include)].reset_index(drop=True)
