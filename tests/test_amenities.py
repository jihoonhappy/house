"""편의시설 반경조사 테스트 (네트워크 없음)."""
import pytest

from aptfinder import amenities, kakao
from aptfinder.errors import ApiError

HOSPITAL = {"kind": "category", "code": "HP8", "radius_m": 1000}
MARKET = {"kind": "keyword", "query": "전통시장", "radius_m": 1500, "contains": "시장"}


def payload(docs, total=None):
    return {"meta": {"total_count": total if total is not None else len(docs)},
            "documents": docs}


def doc(name, distance, category="가정,생활 > 시장"):
    return {"place_name": name, "distance": str(distance), "category_name": category}


def finder(monkeypatch, response, tmp_path, budget=None):
    calls = []

    def fake_get_json(url, headers=None, timeout=30):
        calls.append(url)
        return response

    monkeypatch.setattr(kakao, "get_json", fake_get_json)
    client = amenities.AmenityFinder("key", tmp_path / "amenity.json",
                                     sleep=lambda s: None, call_budget=budget)
    return client, calls


class TestCategorySurvey:
    def test_returns_count_and_nearest(self, monkeypatch, tmp_path):
        response = payload([doc("서울프라임치과의원", 52, "의료 > 병원")], total=89)
        f, _ = finder(monkeypatch, response, tmp_path)
        result = f.survey(37.5896, 127.0576, HOSPITAL)
        assert result == {"count": 89, "nearest": "서울프라임치과의원", "nearest_m": 52}

    def test_no_results_is_reported_as_zero(self, monkeypatch, tmp_path):
        f, _ = finder(monkeypatch, payload([], total=0), tmp_path)
        assert f.survey(37.5, 127.0, HOSPITAL) == {"count": 0, "nearest": "", "nearest_m": None}

    def test_second_survey_at_same_point_uses_cache(self, monkeypatch, tmp_path):
        f, calls = finder(monkeypatch, payload([doc("A", 10)], total=3), tmp_path)
        f.survey(37.5, 127.0, HOSPITAL)
        f.survey(37.5, 127.0, HOSPITAL)
        assert len(calls) == 1

    def test_different_radius_is_a_different_cache_entry(self, monkeypatch, tmp_path):
        f, calls = finder(monkeypatch, payload([doc("A", 10)], total=3), tmp_path)
        f.survey(37.5, 127.0, HOSPITAL)
        f.survey(37.5, 127.0, {**HOSPITAL, "radius_m": 500})
        assert len(calls) == 2


class TestKeywordSurvey:
    def test_filters_by_category_substring(self, monkeypatch, tmp_path):
        """'전통시장' 검색에 상인회 사무실이 섞이면 시장으로 세면 안 된다."""
        response = payload([
            doc("청량리전통시장상인회사무실", 100, "서비스,산업 > 관리,운영"),
            doc("회기시장", 276, "가정,생활 > 시장"),
        ], total=16)
        f, _ = finder(monkeypatch, response, tmp_path)
        result = f.survey(37.5896, 127.0576, MARKET)
        assert result["nearest"] == "회기시장"
        assert result["nearest_m"] == 276
        assert result["count"] == 1

    def test_unfiltered_keyword_uses_total_count(self, monkeypatch, tmp_path):
        spec = {"kind": "keyword", "query": "종합병원", "radius_m": 3000}
        f, _ = finder(monkeypatch, payload([doc("A", 500)], total=7), tmp_path)
        assert f.survey(37.5, 127.0, spec)["count"] == 7


class TestSurveyAll:
    def test_runs_every_configured_spec(self, monkeypatch, tmp_path):
        f, _ = finder(monkeypatch, payload([doc("X", 10)], total=5), tmp_path)
        result = f.survey_all(37.5, 127.0, {"hospital": HOSPITAL, "market": MARKET})
        assert result["hospital_count"] == 5
        assert result["hospital_nearest_m"] == 10
        assert "market_nearest" in result


class TestBudget:
    def test_stops_when_budget_is_exhausted(self, monkeypatch, tmp_path):
        f, _ = finder(monkeypatch, payload([doc("A", 10)], total=1), tmp_path, budget=1)
        f.survey(37.5, 127.0, HOSPITAL)
        with pytest.raises(ApiError, match="예산"):
            f.survey(37.6, 127.1, HOSPITAL)


class TestSpecValidation:
    def test_unknown_kind_is_rejected(self, monkeypatch, tmp_path):
        f, _ = finder(monkeypatch, payload([]), tmp_path)
        with pytest.raises(ValueError, match="kind"):
            f.survey(37.5, 127.0, {"kind": "telepathy", "radius_m": 100})
