"""자차 소요시간 조회·결합 테스트 (네트워크 없음)."""
import json
from datetime import datetime

import pytest

from aptfinder import driving, kakao
from aptfinder.errors import ApiError

DESTS = {"강남": (37.4980, 127.0279), "시청": (37.5657, 126.9771)}


def route(seconds, metres, toll=0):
    return {"routes": [{"result_code": 0,
                        "summary": {"duration": seconds, "distance": metres,
                                    "fare": {"toll": toll, "taxi": 0}}}]}


def finder(monkeypatch, responses, tmp_path, budget=None):
    calls = []

    def fake_get_json(url, headers=None, timeout=30):
        calls.append(url)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(kakao, "get_json", fake_get_json)
    return driving.DrivingTimes("key", tmp_path / "drive.json", departure_hour=8,
                                sleep=lambda s: None, call_budget=budget), calls


class TestDepartureTime:
    def test_picks_a_weekday_morning(self):
        stamp = driving.next_weekday_departure(8, today=datetime(2026, 8, 28, 14, 0))
        assert stamp.endswith("0800")
        parsed = datetime.strptime(stamp, "%Y%m%d%H%M")
        assert parsed.weekday() < 5          # 월~금
        assert parsed > datetime(2026, 8, 28, 14, 0)

    def test_saturday_rolls_to_monday(self):
        stamp = driving.next_weekday_departure(8, today=datetime(2026, 8, 29, 9, 0))
        assert datetime.strptime(stamp, "%Y%m%d%H%M").weekday() == 0

    def test_is_stable_for_the_same_day(self):
        a = driving.next_weekday_departure(8, today=datetime(2026, 8, 28, 9, 0))
        b = driving.next_weekday_departure(8, today=datetime(2026, 8, 28, 18, 0))
        assert a == b


class TestLookup:
    def test_returns_minutes_distance_and_toll(self, monkeypatch, tmp_path):
        finder_, _ = finder(monkeypatch, [route(2580, 18400, 2700)], tmp_path)
        result = finder_.travel(37.505, 126.753, (37.5217, 126.9244))
        assert {k: result[k] for k in ("minutes", "km", "toll")} == {
            "minutes": 43.0, "km": 18.4, "toll": 2700}
        assert result["departure"] == finder_.departure

    def test_second_call_at_same_point_uses_cache(self, monkeypatch, tmp_path):
        finder_, calls = finder(monkeypatch, [route(600, 5000)], tmp_path)
        finder_.travel(37.5, 127.0, (37.4980, 127.0279))
        finder_.travel(37.5, 127.0, (37.4980, 127.0279))
        assert len(calls) == 1

    def test_failed_route_returns_none(self, monkeypatch, tmp_path):
        finder_, _ = finder(monkeypatch, [{"routes": [{"result_code": 104}]}], tmp_path)
        assert finder_.travel(37.5, 127.0, (37.4, 127.1)) is None

    def test_empty_response_returns_none(self, monkeypatch, tmp_path):
        finder_, _ = finder(monkeypatch, [{"routes": []}], tmp_path)
        assert finder_.travel(37.5, 127.0, (37.4, 127.1)) is None


class TestBestAccess:
    def test_picks_the_fastest_destination(self, monkeypatch, tmp_path):
        finder_, _ = finder(monkeypatch, [route(3600, 30000), route(1800, 15000)], tmp_path)
        best = finder_.best_access(37.6, 126.8, DESTS)
        assert best["destination"] == "시청"
        assert best["minutes"] == 30.0

    def test_all_failures_give_none(self, monkeypatch, tmp_path):
        finder_, _ = finder(monkeypatch, [{"routes": []}], tmp_path)
        assert finder_.best_access(37.6, 126.8, DESTS)["minutes"] is None

    def test_no_destinations_is_safe(self, monkeypatch, tmp_path):
        finder_, calls = finder(monkeypatch, [route(600, 5000)], tmp_path)
        assert finder_.best_access(37.6, 126.8, {})["minutes"] is None
        assert calls == []


class TestBudget:
    def test_stops_when_budget_is_exhausted(self, monkeypatch, tmp_path):
        finder_, _ = finder(monkeypatch, [route(600, 5000)], tmp_path, budget=1)
        finder_.travel(37.5, 127.0, (37.4, 127.1))
        with pytest.raises(ApiError, match="예산"):
            finder_.travel(37.6, 127.2, (37.4, 127.1))

    def test_cache_is_saved_on_budget_stop(self, monkeypatch, tmp_path):
        finder_, _ = finder(monkeypatch, [route(600, 5000)], tmp_path, budget=1)
        finder_.travel(37.5, 127.0, (37.4, 127.1))
        with pytest.raises(ApiError):
            finder_.travel(37.6, 127.2, (37.4, 127.1))
        assert json.loads((tmp_path / "drive.json").read_text(encoding="utf-8"))


class TestCacheKeyIsDateIndependent:
    """캐시 키에 날짜가 들어가면 날이 바뀔 때마다 전량 재조회된다."""

    def test_same_route_hits_cache_across_departure_dates(self, monkeypatch, tmp_path):
        calls = []

        def fake_get_json(url, headers=None, timeout=30):
            calls.append(url)
            return route(1800, 15000)

        monkeypatch.setattr(kakao, "get_json", fake_get_json)
        first = driving.DrivingTimes("key", tmp_path / "d.json", departure_hour=8,
                                     sleep=lambda s: None)
        first.departure = "202609030800"
        first.travel(37.5, 127.0, (37.4, 127.1))
        first.save()

        later = driving.DrivingTimes("key", tmp_path / "d.json", departure_hour=8,
                                     sleep=lambda s: None)
        later.departure = "202612310800"          # 몇 달 뒤
        assert later.travel(37.5, 127.0, (37.4, 127.1))["minutes"] == 30.0
        assert len(calls) == 1                     # 재조회하지 않는다

    def test_result_records_which_departure_it_came_from(self, monkeypatch, tmp_path):
        monkeypatch.setattr(kakao, "get_json",
                            lambda url, headers=None, timeout=30: route(1800, 15000))
        finder_ = driving.DrivingTimes("key", tmp_path / "d.json", departure_hour=8,
                                       sleep=lambda s: None)
        assert finder_.travel(37.5, 127.0, (37.4, 127.1))["departure"] == finder_.departure
