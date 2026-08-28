"""국토교통부 아파트 매매 실거래가 수집.

엔드포인트가 바뀌면 data.go.kr 활용신청 상세 페이지의 '요청주소'로 RTMS_URL만 교체하면 된다.
"""
from __future__ import annotations
import json
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from ..config import all_districts, data_dir
from ..errors import ApiError
from ..http import build_url, get
from ..logging_util import get_logger

RTMS_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
ROWS_PER_PAGE = 1000
MAX_PAGES = 30
OK_CODES = ("00", "000")
CANCELLED = "O"  # cdealType: 거래 해제 건

log = get_logger("rtms")


def recent_months(count: int, today: date | None = None) -> list[str]:
    """오늘 기준 최근 count개월의 YYYYMM 목록 (이번 달 포함, 최신순)."""
    today = today or date.today()
    year, month = today.year, today.month
    months = []
    for _ in range(count):
        months.append(f"{year}{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return months


def parse_trades(xml_text: str, gu_name: str) -> list[dict[str, Any]]:
    """실거래 XML을 dict 목록으로 변환한다. 해제된 거래는 제외."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ApiError(f"실거래 XML 파싱 실패: {e}\n응답 앞부분: {xml_text[:200]}") from e

    result_code = (root.findtext(".//resultCode") or "").strip()
    if result_code and result_code not in OK_CODES:
        message = root.findtext(".//resultMsg") or "unknown"
        raise ApiError(f"실거래 API 오류 {result_code}: {message}")

    rows = []
    for item in root.iter("item"):
        def field(tag):
            return (item.findtext(tag) or "").strip()

        if field("cdealType") == CANCELLED:
            continue
        price = field("dealAmount").replace(",", "")
        if not price.isdigit():
            continue
        try:
            area = float(field("excluUseAr"))
        except ValueError:
            continue
        rows.append({
            "gu": gu_name,
            "sgg_code": field("sggCd"),
            "dong": field("umdNm"),
            "jibun": field("jibun"),
            "apt": field("aptNm"),
            "price_manwon": int(price),
            "area_m2": area,
            "floor": field("floor"),
            "build_year": field("buildYear"),
            "deal_ym": f"{field('dealYear')}{int(field('dealMonth') or 0):02d}",
        })
    return rows


def total_count(xml_text: str) -> int | None:
    """응답의 totalCount. 없으면 None."""
    try:
        value = ET.fromstring(xml_text).findtext(".//totalCount")
    except ET.ParseError:
        return None
    return int(value) if value and value.strip().isdigit() else None


def fetch_month(
    service_key: str,
    lawd_cd: str,
    gu_name: str,
    deal_ymd: str,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """한 구·한 달의 거래를 모두(페이징 포함) 가져온다."""
    rows, page = [], 1
    while page <= MAX_PAGES:
        url = build_url(RTMS_URL, service_key, {
            "LAWD_CD": lawd_cd, "DEAL_YMD": deal_ymd,
            "numOfRows": ROWS_PER_PAGE, "pageNo": page,
        })
        xml_text = get(url, sleep=sleep)
        rows.extend(parse_trades(xml_text, gu_name))
        total = total_count(xml_text)
        if total is None or page * ROWS_PER_PAGE >= total:
            break
        page += 1
        sleep(0.2)
    return rows


def _with_district_code(
    rows: list[dict[str, Any]], lawd_cd: str, gu_name: str
) -> list[dict[str, Any]]:
    """예전 캐시에 없던 시군구코드·지역명을 파일 키에서 채운다 (재수집 방지)."""
    return [{**row, "sgg_code": row.get("sgg_code") or lawd_cd,
             "gu": row.get("gu") or gu_name} for row in rows]


def collect(
    cfg: Mapping[str, Any], service_key: str, sleep: Callable[[float], None] = time.sleep
) -> list[dict[str, Any]]:
    """설정된 모든 구 × 최근 N개월을 수집해 data/trades_all.json에 저장한다."""
    months = recent_months(cfg["criteria"]["lookback_months"])
    districts = all_districts(cfg)
    directory = data_dir()
    all_rows, failures = [], []

    for lawd_cd, gu_name in districts.items():
        for deal_ymd in months:
            cache = directory / f"trades_{lawd_cd}_{deal_ymd}.json"
            if cache.exists():
                all_rows.extend(_with_district_code(
                    json.loads(cache.read_text(encoding="utf-8")), lawd_cd, gu_name))
                continue
            try:
                rows = fetch_month(service_key, lawd_cd, gu_name, deal_ymd, sleep=sleep)
            except ApiError as e:
                log.warning("  ! %s %s 실패: %s", gu_name, deal_ymd, e)
                failures.append((gu_name, deal_ymd))
                continue
            cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            all_rows.extend(rows)
            log.info("  %s %s: %d건", gu_name, deal_ymd, len(rows))
            sleep(0.2)

    out = directory / "trades_all.json"
    out.write_text(json.dumps(all_rows, ensure_ascii=False), encoding="utf-8")
    log.info("실거래 총 %d건 → %s", len(all_rows), out)
    if failures:
        log.warning("실패한 구/월 %d건 — 재실행하면 실패분만 다시 시도합니다.", len(failures))
    return all_rows
