"""좌표 계산 - 직선거리와 최근접 탐색. 외부 의존 없는 순수 함수."""
from __future__ import annotations
import math
from collections.abc import Iterable, Mapping
from typing import Any

EARTH_RADIUS_M = 6371000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 사이의 대권(직선) 거리를 미터로 반환한다."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (math.sin(d_phi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def has_coords(point: Mapping[str, Any]) -> bool:
    """lat/lon이 숫자로 채워진 지점인지 확인한다."""
    return (isinstance(point.get("lat"), (int, float))
            and isinstance(point.get("lon"), (int, float)))


def nearest(
    lat: float, lon: float, points: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, Any] | None, float]:
    """points 중 가장 가까운 항목과 거리(m)를 (point, distance)로 반환한다.

    후보가 없으면 (None, inf).
    """
    best, best_distance = None, float("inf")
    for point in points:
        if not has_coords(point):
            continue
        distance = haversine_m(lat, lon, point["lat"], point["lon"])
        if distance < best_distance:
            best, best_distance = point, distance
    return best, best_distance


def count_within(
    lat: float, lon: float, points: Iterable[Mapping[str, Any]], radius_m: float
) -> int:
    """반경 안에 있는 지점 개수. 좌표가 없는 항목은 세지 않는다."""
    return sum(
        1 for point in points
        if has_coords(point) and haversine_m(lat, lon, point["lat"], point["lon"]) <= radius_m
    )
