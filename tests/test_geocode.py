"""지오코더 캐시·폴백·오류안내 테스트 (네트워크 호출 없음)."""
import json

import pytest

from aptfinder import geocode, kakao
from aptfinder.errors import ApiError


@pytest.fixture
def cache_path(tmp_path):
    return tmp_path / "geocode_cache.json"


def make(monkeypatch, responses, cache_path):
    """responses: 호출 순서대로 돌려줄 페이로드 목록."""
    calls = []

    def fake_get_json(url, headers=None, timeout=30):
        calls.append(url)
        return responses[len(calls) - 1]

    monkeypatch.setattr(kakao, "get_json", fake_get_json)
    return geocode.KakaoGeocoder("key", cache_path, sleep=lambda s: None), calls


DOC = {"documents": [{"x": "127.0983", "y": "37.4844"}]}
EMPTY = {"documents": []}


class TestLookup:
    def test_returns_coordinates_from_address_search(self, monkeypatch, cache_path):
        geo, calls = make(monkeypatch, [DOC], cache_path)
        assert geo.lookup("서울 강남구 수서동 746") == (37.4844, 127.0983)
        assert len(calls) == 1
        assert "address.json" in calls[0]

    def test_falls_back_to_keyword_search(self, monkeypatch, cache_path):
        geo, calls = make(monkeypatch, [EMPTY, DOC], cache_path)
        assert geo.lookup("이상한 주소", keyword="서울 강남구 까치마을") == (37.4844, 127.0983)
        assert "keyword.json" in calls[1]

    def test_returns_none_when_nothing_found(self, monkeypatch, cache_path):
        geo, _ = make(monkeypatch, [EMPTY, EMPTY], cache_path)
        assert geo.lookup("없는 주소", keyword="없는 단지") is None

    def test_second_lookup_uses_cache(self, monkeypatch, cache_path):
        geo, calls = make(monkeypatch, [DOC], cache_path)
        geo.lookup("서울 강남구 수서동 746")
        geo.lookup("서울 강남구 수서동 746")
        assert len(calls) == 1

    def test_cache_survives_reload(self, monkeypatch, cache_path):
        geo, _ = make(monkeypatch, [DOC], cache_path)
        geo.lookup("서울 강남구 수서동 746")
        geo.save()
        reloaded, calls = make(monkeypatch, [], cache_path)
        assert reloaded.lookup("서울 강남구 수서동 746") == (37.4844, 127.0983)
        assert calls == []

    def test_corrupted_cache_is_ignored(self, monkeypatch, cache_path):
        cache_path.write_text("{broken", encoding="utf-8")
        geo, _ = make(monkeypatch, [DOC], cache_path)
        assert geo.lookup("서울 강남구 수서동 746") == (37.4844, 127.0983)

    def test_saved_cache_is_valid_json(self, monkeypatch, cache_path):
        geo, _ = make(monkeypatch, [DOC], cache_path)
        geo.lookup("서울 강남구 수서동 746")
        geo.save()
        assert json.loads(cache_path.read_text(encoding="utf-8"))


class TestDisabledService:
    def test_explains_how_to_enable_kakao_map(self, monkeypatch, cache_path):
        def raise_403(url, headers=None, timeout=30):
            raise ApiError('HTTP 403 — {"errorType":"NotAuthorizedError",'
                           '"message":"App disabled OPEN_MAP_AND_LOCAL service."}')

        monkeypatch.setattr(kakao, "get_json", raise_403)
        geo = geocode.KakaoGeocoder("key", cache_path, sleep=lambda s: None)
        with pytest.raises(ApiError, match="카카오맵"):
            geo.lookup("서울 강남구 수서동 746")

    def test_transient_failure_is_not_cached(self, monkeypatch, cache_path):
        def raise_500(url, headers=None, timeout=30):
            raise ApiError("HTTP 500 — server error")

        monkeypatch.setattr(kakao, "get_json", raise_500)
        geo = geocode.KakaoGeocoder("key", cache_path, sleep=lambda s: None)
        with pytest.raises(ApiError):
            geo.lookup("서울 강남구 수서동 746")
        geo.save()
        assert json.loads(cache_path.read_text(encoding="utf-8")) == {}


class TestCallBudget:
    def test_stops_and_saves_when_budget_is_exhausted(self, monkeypatch, cache_path):
        monkeypatch.setattr(kakao, "get_json", lambda url, headers=None, timeout=30: DOC)
        geo = geocode.KakaoGeocoder("key", cache_path, sleep=lambda s: None, call_budget=2)
        assert geo.lookup("주소1") is not None
        assert geo.lookup("주소2") is not None
        with pytest.raises(ApiError, match="예산"):
            geo.lookup("주소3")
        assert json.loads(cache_path.read_text(encoding="utf-8"))  # 진행분이 보존됨

    def test_no_budget_means_unlimited(self, monkeypatch, cache_path):
        monkeypatch.setattr(kakao, "get_json", lambda url, headers=None, timeout=30: DOC)
        geo = geocode.KakaoGeocoder("key", cache_path, sleep=lambda s: None)
        for i in range(50):
            assert geo.lookup(f"주소{i}") is not None
