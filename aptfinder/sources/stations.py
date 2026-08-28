"""서울 열린데이터광장 - 지하철역 좌표(역사마스터) 수집."""
from __future__ import annotations
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..config import data_dir
from ..errors import ApiError
from ..http import get_json
from ..logging_util import get_logger

BASE_URL = "http://openapi.seoul.go.kr:8088/{key}/json/{dataset}/{start}/{end}/"
DATASET = "subwayStationMaster"
PAGE_SIZE = 1000

# 데이터셋 개편에 대비한 필드명 후보 (앞에서부터 먼저 있는 것을 쓴다)
LAT_FIELDS = ("LAT", "CRDNT_Y", "YCRDNT", "Y")
LON_FIELDS = ("LOT", "CRDNT_X", "XCRDNT", "X")
NAME_FIELDS = ("BLDN_NM", "STATN_NM", "STATION_NM", "STN_NM")
LINE_FIELDS = ("ROUTE", "LINE_NUM", "LINE_NM")

log = get_logger("stations")


def _pick(row: Mapping[str, Any], candidates: Sequence[str]) -> Any:
    for field in candidates:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return None


def parse_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """API row 목록 → [{name, line, lat, lon}]. 좌표 없는 행은 버린다."""
    parsed = []
    for row in rows:
        name = _pick(row, NAME_FIELDS)
        lat, lon = _pick(row, LAT_FIELDS), _pick(row, LON_FIELDS)
        if not (name and lat and lon):
            continue
        try:
            parsed.append({
                "name": str(name).strip(),
                "line": str(_pick(row, LINE_FIELDS) or "").strip(),
                "lat": float(lat),
                "lon": float(lon),
            })
        except (TypeError, ValueError):
            continue
    return parsed


def _extract_rows(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    """{DATASET: {row: [...]}} 또는 {RESULT: {...}} 응답에서 row를 꺼낸다."""
    if "RESULT" in payload:
        result = payload["RESULT"]
        raise ApiError(
            f"서울 열린데이터광장 오류 {result.get('CODE')}: {result.get('MESSAGE')}\n"
            "  인증키를 확인하거나 data.seoul.go.kr에서 데이터셋명을 확인하세요."
        )
    for value in payload.values():
        if isinstance(value, dict) and "row" in value:
            return value["row"], value.get("list_total_count")
    raise ApiError(f"예상치 못한 응답 구조: {list(payload)[:5]}")


def collect(service_key: str, force: bool = False) -> list[dict[str, Any]]:
    """지하철역 좌표를 수집해 data/stations.json에 저장한다."""
    cache = data_dir() / "stations.json"
    if cache.exists() and not force:
        stations = json.loads(cache.read_text(encoding="utf-8"))
        log.info("지하철역: 캐시 사용 (%d건)", len(stations))
        return stations

    stations, start = [], 1
    while True:
        url = BASE_URL.format(key=service_key, dataset=DATASET,
                              start=start, end=start + PAGE_SIZE - 1)
        rows, total = _extract_rows(get_json(url))
        stations.extend(parse_rows(rows))
        start += PAGE_SIZE
        if not rows or (total and start > total):
            break

    if not stations:
        raise ApiError(
            "역 좌표 파싱 결과가 0건입니다. data.seoul.go.kr에서 "
            f"'{DATASET}' 데이터셋의 응답 필드명을 확인하고 stations.py 상수를 수정하세요."
        )
    cache.write_text(json.dumps(stations, ensure_ascii=False), encoding="utf-8")
    log.info("지하철역 %d건 → %s", len(stations), cache)
    return stations
