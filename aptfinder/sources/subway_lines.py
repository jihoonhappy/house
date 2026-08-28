"""서울 열린데이터광장 - 노선별 지하철역 정보 (역 순서 복원용).

FR_CODE(외부코드)는 노선 내 순번을 담고 있어, 노선별로 정렬하면 역의 물리적
배열이 복원된다. 이것으로 인접역 그래프를 만들 수 있다.
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
DATASET = "SearchSTNBySubwayLineInfo"
PAGE_SIZE = 1000
MAX_PAGES = 10

log = get_logger("subway_lines")


def parse_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """역-노선 행 → {name, line, code}."""
    parsed = []
    for row in rows:
        name = (row.get("STATION_NM") or "").strip()
        line = (row.get("LINE_NUM") or "").strip()
        if not name or not line:
            continue
        parsed.append({"name": name, "line": line,
                       "order_code": (row.get("FR_CODE") or "").strip()})
    return parsed


def _extract(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    if "RESULT" in payload:
        result = payload["RESULT"]
        raise ApiError(f"서울 열린데이터광장 오류 {result.get('CODE')}: {result.get('MESSAGE')}")
    for value in payload.values():
        if isinstance(value, dict) and "row" in value:
            return value["row"], value.get("list_total_count")
    raise ApiError(f"예상치 못한 응답 구조: {list(payload)[:5]}")


def collect(service_key: str, force: bool = False) -> list[dict[str, Any]]:
    """노선별 역 정보를 수집해 data/subway_lines.json에 저장한다."""
    cache = data_dir() / "subway_lines.json"
    if cache.exists() and not force:
        rows = json.loads(cache.read_text(encoding="utf-8"))
        log.info("노선별 역 정보: 캐시 사용 (%d건)", len(rows))
        return rows

    rows: list[dict[str, Any]] = []
    start = 1
    for _ in range(MAX_PAGES):
        url = BASE_URL.format(key=service_key, dataset=DATASET,
                              start=start, end=start + PAGE_SIZE - 1)
        page, total = _extract(get_json(url))
        rows.extend(parse_rows(page))
        start += PAGE_SIZE
        if not page or (total and start > total):
            break
    if not rows:
        raise ApiError(f"'{DATASET}' 파싱 결과가 0건입니다.")
    cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    log.info("노선별 역 %d건 (노선 %d개) → %s",
             len(rows), len({r["line"] for r in rows}), cache)
    return rows
