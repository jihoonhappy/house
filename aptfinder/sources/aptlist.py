"""국토교통부 공동주택 단지 목록제공 서비스 (전국).

시도 단위로 단지코드(kaptCode)와 소재지를 열거한다. 기본정보 API가 단지코드만
받기 때문에, 이 목록이 있어야 서울 밖 단지의 분류를 조회할 수 있다.

활용신청: https://www.data.go.kr/data/15057332/openapi.do
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..config import data_dir
from ..errors import ApiError
from ..http import build_url, get_json
from ..logging_util import get_logger

LIST_URL = "https://apis.data.go.kr/1613000/AptListService4/getSidoAptList4"
ROWS_PER_PAGE = 1000
MAX_PAGES = 40

log = get_logger("aptlist")

NOT_REGISTERED = (
    "공동주택 단지 목록제공 서비스가 이 키에 등록되어 있지 않습니다.\n"
    "  https://www.data.go.kr/data/15057332/openapi.do 에서 활용신청하세요.\n"
    "  (기본 정보제공 서비스와는 별개 신청입니다.)"
)


def parse_items(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """목록 item → {apt_code, name, sido, sigungu, dong}."""
    parsed = []
    for item in items:
        code = (item.get("kaptCode") or "").strip()
        if not code:
            continue
        parsed.append({
            "apt_code": code,
            "name": (item.get("kaptName") or "").strip(),
            "sido": (item.get("as1") or "").strip(),
            "sigungu": (item.get("as2") or "").strip(),
            "dong": (item.get("as3") or "").strip(),
        })
    return parsed


def _items_of(payload: Mapping[str, Any]) -> tuple[list[dict], int]:
    body = (payload.get("response") or {}).get("body") or {}
    items = (body.get("items") or {})
    rows = items.get("item") if isinstance(items, dict) else items
    if rows is None:
        rows = []
    if isinstance(rows, dict):
        rows = [rows]
    return rows, int(body.get("totalCount") or 0)


def fetch_sido(service_key: str, sido_code: str) -> list[dict[str, Any]]:
    """한 시도의 단지 목록 전체를 가져온다."""
    collected: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        url = build_url(LIST_URL, service_key, {
            "sidoCode": sido_code, "numOfRows": ROWS_PER_PAGE, "pageNo": page})
        try:
            payload = get_json(url)
        except ApiError as e:
            if "SERVICE_KEY_IS_NOT_REGISTERED" in str(e) or "HTTP 403" in str(e):
                raise ApiError(NOT_REGISTERED) from e
            raise
        rows, total = _items_of(payload)
        collected.extend(parse_items(rows))
        if not rows or page * ROWS_PER_PAGE >= total:
            break
    return collected


def sido_codes(districts: Iterable[str]) -> list[str]:
    """시군구코드 목록에서 시도코드(앞 2자리)를 뽑는다."""
    return sorted({code[:2] for code in districts if len(code) >= 2})


def collect(
    service_key: str, codes: Sequence[str], force: bool = False
) -> list[dict[str, Any]]:
    """지정한 시도들의 단지 목록을 모아 data/apt_list.json에 저장한다."""
    cache = data_dir() / "apt_list.json"
    if cache.exists() and not force:
        rows = json.loads(cache.read_text(encoding="utf-8"))
        log.info("단지 목록: 캐시 사용 (%d건)", len(rows))
        return rows

    rows: list[dict[str, Any]] = []
    for code in codes:
        found = fetch_sido(service_key, code)
        log.info("  시도 %s: %d단지", code, len(found))
        rows.extend(found)
    if not rows:
        raise ApiError("단지 목록이 0건입니다. 시도코드와 응답 필드명을 확인하세요.")
    cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    log.info("단지 목록 %d건 → %s", len(rows), cache)
    return rows
