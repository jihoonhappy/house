"""단지 주변 편의시설 조사 (카카오 로컬 반경검색).

병원·대형마트·전통시장·학원처럼 "반경 안에 몇 개 있고 가장 가까운 건 몇 m인가"를
한 번의 호출로 얻는다. 결과는 좌표 단위로 캐시하므로 재실행 비용이 거의 없다.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .kakao import CachedKakaoClient

CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
PAGE_SIZE = 15
MAX_RADIUS_M = 20000

EMPTY = {"count": 0, "nearest": "", "nearest_m": None}


def _distance(document: Mapping[str, Any]) -> int | None:
    try:
        return int(document["distance"])
    except (KeyError, TypeError, ValueError):
        return None


class AmenityFinder(CachedKakaoClient):
    """좌표 주변 시설을 세고 최근접 거리를 재는 조사기."""

    def survey(self, lat: float, lon: float, spec: Mapping[str, Any]) -> dict[str, Any]:
        """spec에 정의된 시설을 반경 안에서 조사한다.

        spec = {kind: category|keyword, code|query: ..., radius_m: N, contains: 선택}
        contains를 주면 카테고리명에 그 문자열이 든 결과만 센다
        (예: '전통시장' 검색 결과에서 상인회 사무실을 제외).
        """
        kind = spec.get("kind")
        radius = min(int(spec.get("radius_m") or 0), MAX_RADIUS_M)
        if kind == "category":
            url = CATEGORY_URL
            params = {"category_group_code": spec["code"]}
            label = spec["code"]
        elif kind == "keyword":
            url = KEYWORD_URL
            params = {"query": spec["query"]}
            label = spec["query"]
        else:
            raise ValueError(f"알 수 없는 시설 조사 kind: {kind!r} (category 또는 keyword)")

        contains = spec.get("contains") or ""
        cache_key = f"{kind}:{label}:{contains}:{radius}:{lat:.5f}:{lon:.5f}"
        hit, value = self.cached(cache_key)
        if hit:
            return dict(value) if value else dict(EMPTY)

        payload = self.request(url, {
            **params, "x": f"{lon}", "y": f"{lat}",
            "radius": radius, "sort": "distance", "size": PAGE_SIZE,
        })
        result = self._summarize(payload, contains)
        self.remember(cache_key, result)
        return dict(result)

    def survey_all(
        self, lat: float, lon: float, specs: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, Any]:
        """여러 시설을 한 번에 조사해 '이름_count / _nearest / _nearest_m' 형태로 펼친다."""
        flattened: dict[str, Any] = {}
        for name, spec in specs.items():
            result = self.survey(lat, lon, spec)
            flattened[f"{name}_count"] = result["count"]
            flattened[f"{name}_nearest"] = result["nearest"]
            flattened[f"{name}_nearest_m"] = result["nearest_m"]
        return flattened

    @staticmethod
    def _summarize(payload: Mapping[str, Any], contains: str) -> dict[str, Any]:
        documents = payload.get("documents") or []
        total = (payload.get("meta") or {}).get("total_count", len(documents))
        if contains:
            # 필터가 있으면 첫 페이지에서 걸러낸 개수만 신뢰한다 (total은 필터 이전 값).
            documents = [d for d in documents if contains in (d.get("category_name") or "")]
            total = len(documents)
        if not documents:
            return dict(EMPTY)
        nearest = documents[0]
        return {
            "count": total,
            "nearest": nearest.get("place_name", ""),
            "nearest_m": _distance(nearest),
        }
