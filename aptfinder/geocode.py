"""주소 → 좌표 변환 (카카오 로컬 API).

지번 주소 검색을 먼저 시도하고, 실패하면 단지명 키워드 검색으로 한 번 더 시도한다.
'결과 없음'만 캐시하고 네트워크·인증 오류는 캐시하지 않는다 (일시적 실패를 영구 기억하지 않기 위함).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .kakao import CachedKakaoClient

ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


class KakaoGeocoder(CachedKakaoClient):
    """주소를 좌표로 바꾸고 결과를 캐시하는 지오코더."""

    def lookup(self, address: str, keyword: str | None = None) -> tuple[float, float] | None:
        """(lat, lon)을 반환하고, 찾지 못하면 None을 반환한다."""
        cache_key = f"{address}|{keyword or ''}"
        hit, value = self.cached(cache_key)
        if hit:
            return tuple(value) if value else None

        coord = self._search(ADDRESS_URL, {"query": address, "size": 1})
        if coord is None and keyword:
            coord = self._search(KEYWORD_URL, {"query": keyword, "size": 1})

        self.remember(cache_key, list(coord) if coord else None)
        return coord

    def _search(self, url: str, params: Mapping[str, Any]) -> tuple[float, float] | None:
        documents = self.request(url, params).get("documents") or []
        if not documents:
            return None
        first = documents[0]
        try:
            return float(first["y"]), float(first["x"])
        except (KeyError, TypeError, ValueError):
            return None
