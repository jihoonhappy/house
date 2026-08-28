"""국토교통부 공동주택 기본 정보제공 서비스 (전국).

단지코드(kaptCode)로 단지분류(아파트/주상복합)·세대수·동수·사용승인일을 조회한다.
서울시 데이터셋(OpenAptInfo)이 서울만 담고 있어, 경기 등 다른 지역의 주상복합
판별은 이 API로만 가능하다. 조회 결과는 디스크에 캐시한다.

활용신청: https://www.data.go.kr/data/15058453/openapi.do
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import ApiError
from ..http import build_url, get_json
from ..logging_util import get_logger

BASIS_URL = "https://apis.data.go.kr/1613000/AptBasisInfoServiceV5/getAphusBassInfoV5"
FLUSH_EVERY = 100

log = get_logger("aptbasis")


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """API item → 분석에 쓰는 필드. 빈 응답이면 None."""
    if not item or not item.get("kaptCode"):
        return None
    households = _number(item.get("kaptdaCnt"))
    used = (item.get("kaptUsedate") or "").strip()
    return {
        "apt_code": item["kaptCode"],
        "name": (item.get("kaptName") or "").strip(),
        "complex_type": (item.get("codeAptNm") or "").strip(),
        "jibun_addr": (item.get("kaptAddr") or "").strip(),
        "road_addr": (item.get("doroJuso") or "").strip(),
        "bjd_code": (item.get("bjdCode") or "").strip(),
        "households": int(households) if households else None,
        "dong_count": int(_number(item.get("kaptDongCnt")) or 0) or None,
        "top_floor": int(_number(item.get("kaptTopFloor")) or 0) or None,
        "heating": (item.get("codeHeatNm") or "").strip(),
        "builder": (item.get("kaptBcompany") or "").strip(),
        "approved_on": f"{used[:4]}-{used[4:6]}-{used[6:8]}" if len(used) == 8 else "",
    }


class AptBasisLookup:
    """단지코드로 기본정보를 조회하고 결과를 캐시한다."""

    def __init__(self, service_key: str, cache_path: str | Path) -> None:
        self.service_key = service_key
        self.cache_path = Path(cache_path)
        self._cache = self._load()
        self._dirty = 0
        self.calls = 0

    def _load(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("기본정보 캐시를 읽지 못해 새로 시작합니다: %s", e)
            return {}

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        self._dirty = 0

    def lookup(self, apt_code: str) -> dict[str, Any] | None:
        """단지 기본정보. 조회되지 않으면 None (그 사실도 캐시한다)."""
        if not apt_code:
            return None
        if apt_code in self._cache:
            return self._cache[apt_code]

        url = build_url(BASIS_URL, self.service_key, {"kaptCode": apt_code})
        try:
            payload = get_json(url)
        except ApiError as e:
            if "SERVICE_KEY_IS_NOT_REGISTERED" in str(e) or "HTTP 403" in str(e):
                raise ApiError(
                    "공동주택 기본 정보제공 서비스가 이 키에 등록되어 있지 않습니다.\n"
                    "  https://www.data.go.kr/data/15058453/openapi.do 에서 활용신청하세요."
                ) from e
            raise
        self.calls += 1
        item = ((payload.get("response") or {}).get("body") or {}).get("item")
        result = parse_item(item if isinstance(item, dict) else None)
        self._cache[apt_code] = result
        self._dirty += 1
        if self._dirty >= FLUSH_EVERY:
            self.save()
        return result
