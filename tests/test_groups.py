"""점수 그룹(교통·학군·단지·생활인프라) 집계 테스트."""
import pytest

from aptfinder import analyze
from aptfinder.errors import ConfigError

WEIGHTS = {"commute": 18, "station_distance": 12, "school_zone": 12,
           "school_distance": 10, "households": 10, "trade_activity": 10,
           "build_year": 8, "hospital": 8, "mart": 7, "market": 5}

GROUPS = {
    "transit": {"label": "교통", "items": ["commute", "station_distance"]},
    "school": {"label": "학군", "items": ["school_distance", "school_zone"]},
    "complex": {"label": "단지", "items": ["households", "build_year", "trade_activity"]},
    "life": {"label": "생활인프라", "items": ["hospital", "mart", "market"]},
}

CRITERIA = {"station_max_distance_m": 500, "school_max_distance_m": 800,
            "max_commute_min": 45}
SETTINGS = {"middle_radius_m": 1000, "high_radius_m": 1500,
            "schools_for_full_score": 3, "academy_saturation": 80}

PERFECT = {"commute_min": 0, "station_dist_m": 0, "school_dist_m": 0,
           "build_year": "2026", "trade_count": 40, "households": 3000,
           "middle_school_count": 5, "high_school_count": 5, "academy_count": 200,
           "hospital_count": 100, "hospital_nearest_m": 0,
           "mart_nearest_m": 0, "market_nearest_m": 0}
BARREN = {"commute_min": 45, "station_dist_m": 500, "school_dist_m": None,
          "build_year": "1980", "trade_count": 0, "households": None,
          "middle_school_count": 0, "high_school_count": 0, "academy_count": 0,
          "hospital_count": 0, "hospital_nearest_m": None,
          "mart_nearest_m": None, "market_nearest_m": None}


class TestGroupMaxima:
    def test_group_maxima_sum_to_total(self):
        maxima = analyze.group_maxima(WEIGHTS, GROUPS)
        assert sum(maxima.values()) == sum(WEIGHTS.values()) == 100

    def test_each_group_totals_its_items(self):
        maxima = analyze.group_maxima(WEIGHTS, GROUPS)
        assert maxima["transit"] == 30      # 18 + 12
        assert maxima["school"] == 22       # 10 + 12
        assert maxima["complex"] == 28      # 10 + 8 + 10
        assert maxima["life"] == 20         # 8 + 7 + 5


class TestGroupScores:
    def test_perfect_candidate_maxes_every_group(self):
        scores = analyze.group_scores(PERFECT, WEIGHTS, CRITERIA, SETTINGS, GROUPS, 2026)
        assert scores == {"transit": 30.0, "school": 22.0, "complex": 28.0, "life": 20.0}

    def test_barren_candidate_scores_zero_everywhere(self):
        scores = analyze.group_scores(BARREN, WEIGHTS, CRITERIA, SETTINGS, GROUPS, 2026)
        assert set(scores.values()) == {0.0}

    def test_groups_add_up_to_the_total_score(self):
        candidate = {**PERFECT, "station_dist_m": 250, "hospital_count": 10,
                     "mart_nearest_m": 700, "commute_min": 20}
        total = analyze.score_candidate(candidate, WEIGHTS, CRITERIA, SETTINGS, 2026)
        grouped = analyze.group_scores(candidate, WEIGHTS, CRITERIA, SETTINGS, GROUPS, 2026)
        assert sum(grouped.values()) == pytest.approx(total, abs=0.3)

    def test_school_group_includes_elementary_distance(self):
        """초등학교 거리는 학군에 들어가야 한다."""
        near = analyze.group_scores({**BARREN, "school_dist_m": 0},
                                    WEIGHTS, CRITERIA, SETTINGS, GROUPS, 2026)
        far = analyze.group_scores({**BARREN, "school_dist_m": 800},
                                   WEIGHTS, CRITERIA, SETTINGS, GROUPS, 2026)
        assert near["school"] > far["school"]

    def test_life_group_reacts_to_mart_distance(self):
        near = analyze.group_scores({**BARREN, "mart_nearest_m": 0},
                                    WEIGHTS, CRITERIA, SETTINGS, GROUPS, 2026)
        far = analyze.group_scores({**BARREN, "mart_nearest_m": 1500},
                                   WEIGHTS, CRITERIA, SETTINGS, GROUPS, 2026)
        assert near["life"] > far["life"]

    def test_unknown_item_in_group_is_ignored(self):
        groups = {"x": {"label": "X", "items": ["commute", "없는항목"]}}
        assert analyze.group_scores(PERFECT, WEIGHTS, CRITERIA, SETTINGS, groups, 2026)["x"] == 18.0


class TestGroupValidation:
    def test_accepts_groups_covering_every_weight_once(self):
        assert analyze.validate_groups(WEIGHTS, GROUPS) is None

    def test_rejects_missing_item(self):
        broken = {**GROUPS, "life": {"label": "생활", "items": ["hospital", "mart"]}}
        with pytest.raises(ConfigError, match="market"):
            analyze.validate_groups(WEIGHTS, broken)

    def test_rejects_duplicated_item(self):
        broken = {**GROUPS,
                  "life": {"label": "생활", "items": ["hospital", "mart", "market", "commute"]}}
        with pytest.raises(ConfigError, match="commute"):
            analyze.validate_groups(WEIGHTS, broken)

    def test_rejects_unknown_item(self):
        broken = {**GROUPS, "life": {"label": "생활",
                                     "items": ["hospital", "mart", "market", "헬스장"]}}
        with pytest.raises(ConfigError, match="헬스장"):
            analyze.validate_groups(WEIGHTS, broken)
