"""지하철 소요시간 추정.

노선별 역 순서(FR_CODE)로 인접역 그래프를 만들고, 역 좌표로 구간 거리를 재어
노선별 표정속도로 시간을 매긴다. 같은 이름의 역은 환승 간선으로 잇는다.
그 위에서 다익스트라로 목적지까지 최단 시간을 구한다.

한계: 급행·특급을 반영하지 않아 장거리 노선(1호선 등)은 실제보다 보수적으로 나온다.
배차 간격과 버스 환승도 반영하지 않는다. 순위 비교용 추정치로만 쓸 것.
"""
from __future__ import annotations

import heapq
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .geo import haversine_m

ALIAS = re.compile(r"\(.*?\)")
NOISE = re.compile(r"[\s·.]")
ORDER = re.compile(r"([A-Za-z]*)(\d+)")

DEFAULT_SPEED_KMH = 37.0
DEFAULT_DWELL_MIN = 0.3
DEFAULT_TRANSFER_MIN = 3.5
DEFAULT_WAIT_MIN = 1.5
DEFAULT_ROUTE_FACTOR = 1.15   # 직선거리 → 선로 실거리 보정
MAX_HOP_KM = 25.0             # 이보다 먼 인접역은 오연결로 보고 잇지 않는다

Node = tuple[str, str]        # (정규화된 역명, 노선)


def normalize_station(name: str | None) -> str:
    """부기역명·가운뎃점·공백 차이를 흡수한다 (경복궁(정부서울청사) → 경복궁)."""
    return NOISE.sub("", ALIAS.sub("", name or ""))


def order_key(row: Mapping[str, Any]) -> tuple[str, int]:
    """FR_CODE를 (접두, 번호)로 분해해 노선 내 순서를 만든다."""
    match = ORDER.match(row.get("order_code") or "")
    return (match.group(1), int(match.group(2))) if match else ("zzz", 10 ** 9)


class TransitGraph:
    """역 사이 최단 소요시간을 추정하는 그래프."""

    def __init__(
        self,
        line_rows: Iterable[Mapping[str, Any]],
        station_coords: Mapping[str, tuple[float, float]],
        settings: Mapping[str, Any] | None = None,
    ) -> None:
        settings = settings or {}
        self.default_speed = settings.get("default_speed_kmh") or DEFAULT_SPEED_KMH
        self.line_speed = settings.get("line_speed_kmh") or {}
        self.dwell = settings.get("dwell_min", DEFAULT_DWELL_MIN)
        self.transfer = settings.get("transfer_min", DEFAULT_TRANSFER_MIN)
        self.wait = settings.get("initial_wait_min", DEFAULT_WAIT_MIN)
        self.route_factor = settings.get("route_factor") or DEFAULT_ROUTE_FACTOR

        self._coords = {normalize_station(k): v for k, v in station_coords.items()}
        self._edges: dict[Node, list[tuple[Node, float]]] = {}
        self._nodes_of: dict[str, set[Node]] = {}
        self._build(list(line_rows))

    def _build(self, rows: Sequence[Mapping[str, Any]]) -> None:
        by_line: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            name, line = normalize_station(row.get("name")), row.get("line")
            if not name or not line:
                continue
            by_line.setdefault(line, []).append(row)
            self._nodes_of.setdefault(name, set()).add((name, line))

        for line, group in by_line.items():
            speed = self.line_speed.get(line, self.default_speed)
            ordered = sorted(group, key=order_key)
            for first, second in zip(ordered, ordered[1:]):
                self._connect(first, second, line, speed)

        for nodes in self._nodes_of.values():
            for origin in nodes:
                for other in nodes:
                    if origin != other:
                        self._edges.setdefault(origin, []).append((other, self.transfer))

    def _connect(
        self,
        first: Mapping[str, Any],
        second: Mapping[str, Any],
        line: str,
        speed: float,
    ) -> None:
        left, right = normalize_station(first["name"]), normalize_station(second["name"])
        here, there = self._coords.get(left), self._coords.get(right)
        if not here or not there:
            return
        km = haversine_m(here[0], here[1], there[0], there[1]) / 1000 * self.route_factor
        if km > MAX_HOP_KM:
            return
        minutes = km / speed * 60 + self.dwell
        self._edges.setdefault((left, line), []).append(((right, line), minutes))
        self._edges.setdefault((right, line), []).append(((left, line), minutes))

    def knows(self, station: str) -> bool:
        """그래프에 있는 역인지."""
        return normalize_station(station) in self._nodes_of

    def travel_minutes(self, origin: str, destination: str) -> float | None:
        """출발역에서 도착역까지 추정 소요시간(분). 갈 수 없으면 None."""
        start_name, goal_name = normalize_station(origin), normalize_station(destination)
        if start_name == goal_name and start_name in self._nodes_of:
            return 0.0
        starts = self._nodes_of.get(start_name)
        goals = self._nodes_of.get(goal_name)
        if not starts or not goals:
            return None

        best: dict[Node, float] = {node: self.wait for node in starts}
        queue = [(self.wait, node) for node in starts]
        heapq.heapify(queue)
        while queue:
            elapsed, node = heapq.heappop(queue)
            if node in goals:
                return round(elapsed, 1)
            if elapsed > best.get(node, float("inf")):
                continue
            for neighbour, cost in self._edges.get(node, ()):
                total = elapsed + cost
                if total < best.get(neighbour, float("inf")):
                    best[neighbour] = total
                    heapq.heappush(queue, (total, neighbour))
        return None

    def best_access(
        self, origin: str, destinations: Iterable[str]
    ) -> dict[str, Any]:
        """여러 목적지 중 가장 빨리 닿는 곳과 그 시간."""
        best_minutes, best_destination = None, ""
        for destination in destinations:
            minutes = self.travel_minutes(origin, destination)
            if minutes is not None and (best_minutes is None or minutes < best_minutes):
                best_minutes, best_destination = minutes, destination
        return {"minutes": best_minutes, "destination": best_destination}
