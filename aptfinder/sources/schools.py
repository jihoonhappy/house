"""나이스 교육정보 개방포털 - 서울 학교 위치 수집.

분석에 쓰는 초·중·고만 좌표를 붙인다 (대학·특수학교 등은 제외해 호출을 아낀다).
"""
from __future__ import annotations
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from ..config import data_dir
from ..errors import ApiError
from ..http import get_json
from ..logging_util import get_logger

SCHOOL_URL = "https://open.neis.go.kr/hub/schoolInfo"
DEFAULT_OFFICE_CODES = ("B10",)   # B10 서울, J10 경기, E10 인천
PAGE_SIZE = 1000
MAX_PAGES = 10
ELEMENTARY = "초등학교"
MIDDLE = "중학교"
HIGH = "고등학교"
GEOCODED_KINDS = (ELEMENTARY, MIDDLE, HIGH)

log = get_logger("schools")


def parse_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """NEIS row → [{name, kind, addr}]."""
    return [
        {
            "name": (row.get("SCHUL_NM") or "").strip(),
            "kind": (row.get("SCHUL_KND_SC_NM") or "").strip(),
            "addr": (row.get("ORG_RDNMA") or "").strip(),
        }
        for row in rows
        if row.get("SCHUL_NM")
    ]


def fetch_list(service_key: str, office_codes: Sequence[str] = DEFAULT_OFFICE_CODES) -> list[dict[str, Any]]:
    """지정한 시도교육청들의 학교 목록을 모두 가져온다."""
    schools: list[dict[str, Any]] = []
    for office in office_codes:
        for page in range(1, MAX_PAGES + 1):
            params = urlencode({
                "KEY": service_key, "Type": "json", "pIndex": page, "pSize": PAGE_SIZE,
                "ATPT_OFCDC_SC_CODE": office,
            })
            payload = get_json(f"{SCHOOL_URL}?{params}")
            if "schoolInfo" not in payload:
                result = (payload.get("RESULT") or {})
                if page == 1:
                    raise ApiError(
                        f"나이스 API 오류 {result.get('CODE')}: {result.get('MESSAGE')}\n"
                        f"  교육청코드 {office} · open.neis.go.kr에서 인증키를 확인하세요."
                    )
                break
            batch = payload["schoolInfo"][1]["row"]
            schools.extend(parse_rows(batch))
            if len(batch) < PAGE_SIZE:
                break
    return schools


def collect(
    service_key: str,
    geocoder: Any,
    office_codes: Sequence[str] = DEFAULT_OFFICE_CODES,
    force: bool = False,
) -> list[dict[str, Any]]:
    """학교 목록 수집 + 초등학교 좌표 지오코딩 → data/schools.json."""
    cache = data_dir() / "schools.json"
    if cache.exists() and not force:
        schools = json.loads(cache.read_text(encoding="utf-8"))
        log.info("학교: 캐시 사용 (%d건)", len(schools))
        return schools

    schools = fetch_list(service_key, office_codes)
    targets = [s for s in schools if s["kind"] in GEOCODED_KINDS]
    log.info("학교 %d건 중 초·중·고 %d건에 좌표를 붙입니다", len(schools), len(targets))

    located = 0
    for index, school in enumerate(targets, 1):
        if not school["addr"]:
            continue
        coord = geocoder.lookup(school["addr"], keyword=f"서울 {school['name']}")
        if coord:
            school["lat"], school["lon"] = coord
            located += 1
        if index % 200 == 0:
            log.info("  지오코딩 %d/%d", index, len(targets))
    geocoder.save()

    cache.write_text(json.dumps(schools, ensure_ascii=False), encoding="utf-8")
    log.info("학교 %d건 저장 (좌표 %d/%d) → %s", len(schools), located, len(targets), cache)
    return schools
