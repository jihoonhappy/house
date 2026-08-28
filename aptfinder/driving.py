"""자차 소요시간 조회 (카카오모빌리티 미래운행정보).

실시간 조회는 실행 시각마다 값이 달라 비교가 불가능하므로, 항상 "다음 평일 아침"
기준으로 조회해 재현 가능한 값을 얻는다. 출근시간대라 실제 체감에 가깝다.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .kakao import CachedKakaoClient

DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/future/directions"
COORD_PRECISION = 4      # 약 10m. 같은 단지의 여러 면적대가 한 번만 조회되도록 묶는다
OK_RESULT_CODE = 0


def next_weekday_departure(hour: int, today: datetime | None = None) -> str:
    """다음 평일 지정 시각을 yyyyMMddHHmm으로. 같은 날 안에서는 값이 변하지 않는다."""
    base = (today or datetime.now()).replace(
        hour=hour, minute=0, second=0, microsecond=0)
    candidate = base + timedelta(days=1)
    while candidate.weekday() >= 5:          # 토·일이면 다음 날로
        candidate += timedelta(days=1)
    return candidate.strftime("%Y%m%d%H%M")


class DrivingTimes(CachedKakaoClient):
    """좌표 사이 자차 소요시간을 재고 결과를 캐시한다."""

    def __init__(self, *args: Any, departure_hour: int = 8, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.departure = next_weekday_departure(departure_hour)

    def travel(
        self, lat: float, lon: float, destination: tuple[float, float]
    ) -> dict[str, Any] | None:
        """(분, km, 통행료). 경로를 찾지 못하면 None."""
        origin = f"{lon:.{COORD_PRECISION}f},{lat:.{COORD_PRECISION}f}"
        target = f"{destination[1]:.{COORD_PRECISION}f},{destination[0]:.{COORD_PRECISION}f}"
        cache_key = f"{origin}>{target}@{self.departure}"
        hit, value = self.cached(cache_key)
        if hit:
            return dict(value) if value else None

        payload = self.request(DIRECTIONS_URL, {
            "origin": origin, "destination": target,
            "departure_time": self.departure, "priority": "RECOMMEND",
        })
        result = self._summarize(payload)
        self.remember(cache_key, result)
        return dict(result) if result else None

    def best_access(
        self, lat: float, lon: float, destinations: Mapping[str, tuple[float, float]]
    ) -> dict[str, Any]:
        """여러 목적지 중 가장 빨리 닿는 곳과 그 시간."""
        best: dict[str, Any] = {"minutes": None, "destination": "", "km": None, "toll": None}
        for name, coord in destinations.items():
            found = self.travel(lat, lon, coord)
            if found and (best["minutes"] is None or found["minutes"] < best["minutes"]):
                best = {**found, "destination": name}
        return best

    @staticmethod
    def _summarize(payload: Mapping[str, Any]) -> dict[str, Any] | None:
        routes = payload.get("routes") or []
        if not routes:
            return None
        route = routes[0]
        if route.get("result_code", OK_RESULT_CODE) != OK_RESULT_CODE:
            return None
        summary = route.get("summary") or {}
        duration, distance = summary.get("duration"), summary.get("distance")
        if duration is None or distance is None:
            return None
        return {
            "minutes": round(duration / 60, 1),
            "km": round(distance / 1000, 1),
            "toll": (summary.get("fare") or {}).get("toll", 0),
        }
