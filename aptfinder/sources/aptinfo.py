"""서울시 공동주택 정보(OpenAptInfo) 수집.

단지분류(아파트/주상복합), 총 세대수, 좌표, 동수, 주차대수를 제공한다.
좌표가 실거래 주소 지오코딩보다 정확하므로 매칭된 단지는 이 좌표로 교체한다.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from ..config import data_dir
from ..errors import ApiError
from ..http import get_json
from ..logging_util import get_logger

BASE_URL = "http://openapi.seoul.go.kr:8088/{key}/json/{dataset}/{start}/{end}/"
DATASET = "OpenAptInfo"
PAGE_SIZE = 1000
MAX_PAGES = 20

# 같은 데이터셋 안에서도 "서울"과 "서울특별시"가 섞여 있어 짧은 형태로 통일한다.
SIDO_SUFFIXES = ("특별자치시", "특별자치도", "특별시", "광역시", "도")

log = get_logger("aptinfo")


def normalize_sido(name: str | None) -> str:
    """'서울특별시' → '서울', '경기도' → '경기'."""
    text = (name or "").strip()
    for suffix in SIDO_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _number(value: Any) -> float | None:
    """'206.0' 같은 문자열을 숫자로. 비었거나 이상하면 None."""
    if value in (None, "", "***"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """OpenAptInfo row → 분석에 쓰는 최소 필드 집합."""
    parsed = []
    for row in rows:
        name = (row.get("APT_NM") or "").strip()
        if not name:
            continue
        lat, lon = _number(row.get("YCRD")), _number(row.get("XCRD"))
        households = _number(row.get("TNOHSH"))
        parsed.append({
            "apt_code": (row.get("APT_CD") or "").strip(),
            "name": name,
            "complex_type": (row.get("CMPX_CLSF") or "").strip(),
            "sido": normalize_sido(row.get("CTPV_ADDR")) or "서울",
            "gu": (row.get("SGG_ADDR") or "").strip(),
            "dong": (row.get("EMD_ADDR") or "").strip(),
            "road_addr": (row.get("APT_RDN_ADDR") or "").strip(),
            "households": int(households) if households else None,
            "dong_count": int(_number(row.get("WHOL_DONG_CNT")) or 0) or None,
            "parking": int(_number(row.get("PRK_CNTOM")) or 0) or None,
            "heating": (row.get("MN_MTHD") or "").strip(),
            "builder": (row.get("BLDR") or "").strip(),
            "approved_on": (row.get("USE_APRV_YMD") or "")[:10],
            "lat": lat,
            "lon": lon,
        })
    return parsed


def _extract(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    if "RESULT" in payload:
        result = payload["RESULT"]
        raise ApiError(
            f"서울 열린데이터광장 오류 {result.get('CODE')}: {result.get('MESSAGE')}\n"
            f"  data.seoul.go.kr에서 '{DATASET}' 데이터셋과 인증키를 확인하세요."
        )
    for value in payload.values():
        if isinstance(value, dict) and "row" in value:
            return value["row"], value.get("list_total_count")
    raise ApiError(f"예상치 못한 응답 구조: {list(payload)[:5]}")


def collect(service_key: str, force: bool = False) -> list[dict[str, Any]]:
    """공동주택 정보를 수집해 data/apt_info.json에 저장한다."""
    cache = data_dir() / "apt_info.json"
    if cache.exists() and not force:
        complexes = json.loads(cache.read_text(encoding="utf-8"))
        log.info("공동주택 정보: 캐시 사용 (%d건)", len(complexes))
        return complexes

    complexes: list[dict[str, Any]] = []
    start = 1
    for _ in range(MAX_PAGES):
        url = BASE_URL.format(key=service_key, dataset=DATASET,
                              start=start, end=start + PAGE_SIZE - 1)
        rows, total = _extract(get_json(url))
        complexes.extend(parse_rows(rows))
        start += PAGE_SIZE
        if not rows or (total and start > total):
            break

    if not complexes:
        raise ApiError(f"'{DATASET}' 파싱 결과가 0건입니다. 데이터셋 명세를 확인하세요.")
    cache.write_text(json.dumps(complexes, ensure_ascii=False), encoding="utf-8")
    located = sum(1 for c in complexes if c["lat"] and c["lon"])
    log.info("공동주택 %d건 (좌표 %d, 세대수 %d) → %s",
             len(complexes), located,
             sum(1 for c in complexes if c["households"]), cache)
    return complexes
