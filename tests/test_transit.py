"""지하철 소요시간 추정 테스트."""
import pytest

from aptfinder import transit

# 1호선: A-B-C 일직선, 2호선: C-D. C가 환승역.
LINE_ROWS = [
    {"name": "가역", "line": "01호선", "order_code": "P01"},
    {"name": "나역", "line": "01호선", "order_code": "P02"},
    {"name": "다역", "line": "01호선", "order_code": "P03"},
    {"name": "다역", "line": "02호선", "order_code": "K10"},
    {"name": "라역", "line": "02호선", "order_code": "K11"},
    {"name": "외딴역", "line": "09호선", "order_code": "Z01"},
]
# 위도 0.01도 ≈ 1.11km
COORDS = {
    "가역": (37.500, 127.000), "나역": (37.510, 127.000), "다역": (37.520, 127.000),
    "라역": (37.530, 127.000), "외딴역": (38.000, 127.900),
}
SETTINGS = {"default_speed_kmh": 37, "line_speed_kmh": {"02호선": 60},
            "dwell_min": 0.3, "transfer_min": 3.5, "initial_wait_min": 1.5,
            "route_factor": 1.15}


@pytest.fixture
def graph():
    return transit.TransitGraph(LINE_ROWS, COORDS, SETTINGS)


class TestNormalizeStationName:
    def test_strips_parenthetical_alias(self):
        assert transit.normalize_station("경복궁(정부서울청사)") == transit.normalize_station("경복궁")

    def test_ignores_middle_dot_and_spaces(self):
        assert transit.normalize_station("4·19민주묘지") == transit.normalize_station("4.19 민주묘지")

    def test_empty_is_safe(self):
        assert transit.normalize_station(None) == ""


class TestOrdering:
    def test_recovers_station_order_from_code(self):
        assert transit.order_key({"order_code": "P02"}) < transit.order_key({"order_code": "P10"})

    def test_groups_by_code_prefix(self):
        """접두가 다르면 번호보다 접두가 우선한다 (노선 분기 구간 구분)."""
        assert transit.order_key({"order_code": "K01"}) < transit.order_key({"order_code": "P99"})
        assert transit.order_key({"order_code": "P01"}) < transit.order_key({"order_code": "P02"})

    def test_missing_code_sorts_last(self):
        assert transit.order_key({"order_code": ""}) > transit.order_key({"order_code": "Z99"})


class TestTravelTime:
    def test_adjacent_stations_take_a_few_minutes(self, graph):
        minutes = graph.travel_minutes("가역", "나역")
        assert 1.5 < minutes < 8

    def test_farther_station_takes_longer(self, graph):
        assert graph.travel_minutes("가역", "다역") > graph.travel_minutes("가역", "나역")

    def test_transfer_adds_penalty(self, graph):
        """다역→라역은 같은 거리라도 환승이 없어 1호선 두 정거장보다 빠를 수 있다."""
        with_transfer = graph.travel_minutes("나역", "라역")
        without = graph.travel_minutes("나역", "다역")
        assert with_transfer > without + SETTINGS["transfer_min"] - 1

    def test_same_station_is_zero(self, graph):
        assert graph.travel_minutes("가역", "가역") == 0.0

    def test_unreachable_station_returns_none(self, graph):
        assert graph.travel_minutes("가역", "외딴역") is None

    def test_unknown_station_returns_none(self, graph):
        assert graph.travel_minutes("없는역", "가역") is None

    def test_alias_names_resolve(self, graph):
        assert graph.travel_minutes("가역(어딘가)", "나역") == graph.travel_minutes("가역", "나역")


class TestBestAccess:
    def test_picks_the_fastest_destination(self, graph):
        result = graph.best_access("가역", ["라역", "나역"])
        assert result["destination"] == "나역"
        assert result["minutes"] == pytest.approx(graph.travel_minutes("가역", "나역"))

    def test_ignores_unreachable_destinations(self, graph):
        result = graph.best_access("가역", ["외딴역", "나역"])
        assert result["destination"] == "나역"

    def test_all_unreachable_returns_none(self, graph):
        assert graph.best_access("가역", ["외딴역"])["minutes"] is None

    def test_unknown_origin_returns_none(self, graph):
        assert graph.best_access("없는역", ["나역"])["minutes"] is None


class TestGraphConstruction:
    def test_line_speed_override_is_applied(self):
        slow = transit.TransitGraph(LINE_ROWS, COORDS, {**SETTINGS, "line_speed_kmh": {"02호선": 20}})
        fast = transit.TransitGraph(LINE_ROWS, COORDS, {**SETTINGS, "line_speed_kmh": {"02호선": 200}})
        assert slow.travel_minutes("다역", "라역") > fast.travel_minutes("다역", "라역")

    def test_stations_without_coordinates_are_skipped(self):
        graph = transit.TransitGraph(LINE_ROWS, {"가역": (37.5, 127.0)}, SETTINGS)
        assert graph.travel_minutes("가역", "나역") is None

    def test_absurdly_long_hops_are_not_connected(self):
        """노선 끝과 끝이 잘못 이어져 지름길이 생기면 안 된다."""
        rows = [{"name": "끝1", "line": "L", "order_code": "A01"},
                {"name": "끝2", "line": "L", "order_code": "A02"}]
        coords = {"끝1": (37.5, 127.0), "끝2": (35.0, 129.0)}   # 서울-부산
        graph = transit.TransitGraph(rows, coords, SETTINGS)
        assert graph.travel_minutes("끝1", "끝2") is None
