"""확장된 점수 체계 테스트 - 학군·세대수·편의시설 포함."""
import pytest

from aptfinder import analyze

CRITERIA = {"station_max_distance_m": 500, "school_max_distance_m": 800,
            "min_households": 300}
SETTINGS = {"middle_radius_m": 1000, "high_radius_m": 1500,
            "schools_for_full_score": 3, "academy_saturation": 80}
WEIGHTS = {"station_distance": 18, "school_distance": 14, "school_zone": 14,
           "households": 12, "build_year": 10, "hospital": 10, "mart": 8,
           "market": 6, "trade_activity": 8}

PERFECT = {
    "station_dist_m": 0, "school_dist_m": 0, "build_year": "2026",
    "trade_count": 40, "households": 3000,
    "middle_school_count": 5, "high_school_count": 5, "academy_count": 200,
    "hospital_count": 100, "hospital_nearest_m": 0,
    "mart_nearest_m": 0, "market_nearest_m": 0,
}
BARREN = {
    "station_dist_m": 500, "school_dist_m": None, "build_year": "1980",
    "trade_count": 0, "households": None,
    "middle_school_count": 0, "high_school_count": 0, "academy_count": 0,
    "hospital_count": 0, "hospital_nearest_m": None,
    "mart_nearest_m": None, "market_nearest_m": None,
}


def score(candidate):
    return analyze.score_candidate(candidate, WEIGHTS, CRITERIA, SETTINGS, current_year=2026)


class TestBounds:
    def test_perfect_candidate_scores_full_marks(self):
        assert score(PERFECT) == pytest.approx(100.0)

    def test_barren_candidate_scores_zero(self):
        assert score(BARREN) == pytest.approx(0.0)

    def test_score_never_leaves_zero_to_hundred(self):
        weird = {**PERFECT, "households": 99999, "academy_count": 9999,
                 "trade_count": 9999, "hospital_count": 9999}
        assert 0 <= score(weird) <= 100


class TestSchoolZone:
    def test_more_middle_schools_scores_higher(self):
        few = analyze.school_zone_score({**PERFECT, "middle_school_count": 0}, SETTINGS)
        many = analyze.school_zone_score({**PERFECT, "middle_school_count": 5}, SETTINGS)
        assert many > few

    def test_academy_density_lifts_the_score(self):
        quiet = analyze.school_zone_score({**BARREN, "academy_count": 0}, SETTINGS)
        busy = analyze.school_zone_score({**BARREN, "academy_count": 100}, SETTINGS)
        assert busy > quiet

    def test_saturates_at_configured_thresholds(self):
        at = analyze.school_zone_score(
            {"middle_school_count": 3, "high_school_count": 3, "academy_count": 80}, SETTINGS)
        beyond = analyze.school_zone_score(
            {"middle_school_count": 30, "high_school_count": 30, "academy_count": 800}, SETTINGS)
        assert at == pytest.approx(beyond) == pytest.approx(1.0)

    def test_missing_fields_score_zero_not_error(self):
        assert analyze.school_zone_score({}, SETTINGS) == 0.0


class TestHouseholds:
    def test_bigger_complex_scores_higher(self):
        small = score({**PERFECT, "households": 300})
        large = score({**PERFECT, "households": 3000})
        assert large > small

    def test_unknown_household_count_scores_zero_without_error(self):
        assert score({**PERFECT, "households": None}) < 100


class TestAmenities:
    def test_closer_mart_scores_higher(self):
        near = score({**PERFECT, "mart_nearest_m": 100})
        far = score({**PERFECT, "mart_nearest_m": 1400})
        assert near > far

    def test_missing_market_does_not_crash(self):
        assert score({**PERFECT, "market_nearest_m": None}) < 100

    def test_hospital_uses_both_count_and_distance(self):
        sparse = score({**PERFECT, "hospital_count": 1, "hospital_nearest_m": 900})
        dense = score({**PERFECT, "hospital_count": 60, "hospital_nearest_m": 50})
        assert dense > sparse


class TestComponents:
    def test_every_weight_has_a_component(self):
        components = analyze.score_components(PERFECT, CRITERIA, SETTINGS, 2026)
        assert set(WEIGHTS) <= set(components)

    def test_components_are_normalised_between_zero_and_one(self):
        for value in analyze.score_components(PERFECT, CRITERIA, SETTINGS, 2026).values():
            assert 0.0 <= value <= 1.0

    def test_unknown_weight_key_is_ignored(self):
        assert analyze.score_candidate(
            PERFECT, {**WEIGHTS, "무의미한항목": 50}, CRITERIA, SETTINGS, 2026
        ) == pytest.approx(100.0)


class TestSchoolMetrics:
    SCHOOLS = [
        {"name": "가초", "kind": "초등학교", "lat": 37.5000, "lon": 127.0000},
        {"name": "나중", "kind": "중학교", "lat": 37.5040, "lon": 127.0000},
        {"name": "다중", "kind": "중학교", "lat": 37.5900, "lon": 127.0000},
        {"name": "라고", "kind": "고등학교", "lat": 37.5090, "lon": 127.0000},
    ]

    def test_counts_by_kind_within_radius(self):
        result = analyze.school_metrics(37.5, 127.0, self.SCHOOLS, SETTINGS)
        assert result["middle_school_count"] == 1     # 나중만 1km 이내
        assert result["high_school_count"] == 1       # 라고는 1.5km 이내
        assert result["middle_school"] == "나중"

    def test_reports_nearest_distance_per_kind(self):
        result = analyze.school_metrics(37.5, 127.0, self.SCHOOLS, SETTINGS)
        assert result["school_dist_m"] == 0
        assert 400 < result["middle_school_dist_m"] < 500

    def test_handles_empty_school_list(self):
        result = analyze.school_metrics(37.5, 127.0, [], SETTINGS)
        assert result["middle_school_count"] == 0
        assert result["school_dist_m"] is None


class FakeGraph:
    def __init__(self, table):
        self.table = table

    def best_access(self, station, destinations):
        for destination in destinations:
            minutes = self.table.get((station, destination))
            if minutes is not None:
                return {"minutes": minutes, "destination": destination}
        return {"minutes": None, "destination": ""}


class TestCommute:
    GRAPH = FakeGraph({("정자", "강남"): 27.0, ("수원", "시청"): 80.0})

    def test_attaches_minutes_and_destination(self):
        result = analyze.attach_commute({"station": "정자"}, self.GRAPH, ["강남", "시청"])
        assert result["commute_min"] == 27.0
        assert result["commute_to"] == "강남"

    def test_unreachable_station_gets_none(self):
        result = analyze.attach_commute({"station": "외딴역"}, self.GRAPH, ["강남"])
        assert result["commute_min"] is None

    def test_candidate_without_station_is_safe(self):
        assert analyze.attach_commute({}, self.GRAPH, ["강남"])["commute_min"] is None

    def test_filter_keeps_fast_commute(self):
        assert analyze.passes_commute({"commute_min": 27.0}, {"max_commute_min": 45}) is True

    def test_filter_drops_slow_commute(self):
        assert analyze.passes_commute({"commute_min": 80.0}, {"max_commute_min": 45}) is False

    def test_filter_drops_unreachable(self):
        assert analyze.passes_commute({"commute_min": None}, {"max_commute_min": 45}) is False

    def test_zero_limit_disables_the_filter(self):
        assert analyze.passes_commute({"commute_min": None}, {"max_commute_min": 0}) is True

    def test_shorter_commute_scores_higher(self):
        criteria = {**CRITERIA, "max_commute_min": 45}
        weights = {"commute": 100}
        near = analyze.score_candidate({"commute_min": 10}, weights, criteria, SETTINGS, 2026)
        far = analyze.score_candidate({"commute_min": 40}, weights, criteria, SETTINGS, 2026)
        assert near > far

    def test_commute_at_the_limit_scores_zero(self):
        criteria = {**CRITERIA, "max_commute_min": 45}
        assert analyze.score_candidate(
            {"commute_min": 45}, {"commute": 100}, criteria, SETTINGS, 2026) == 0.0


class TestValuePerEok:
    def test_cheaper_at_same_score_gives_better_value(self):
        cheap = analyze.value_per_eok({"score": 60.0, "price_manwon": 40000})
        pricey = analyze.value_per_eok({"score": 60.0, "price_manwon": 60000})
        assert cheap > pricey

    def test_higher_score_at_same_price_gives_better_value(self):
        assert (analyze.value_per_eok({"score": 70.0, "price_manwon": 50000})
                > analyze.value_per_eok({"score": 50.0, "price_manwon": 50000}))

    def test_is_score_per_hundred_million_won(self):
        assert analyze.value_per_eok({"score": 60.0, "price_manwon": 60000}) == 10.0
        assert analyze.value_per_eok({"score": 55.0, "price_manwon": 40000}) == 13.8

    def test_missing_price_is_none(self):
        assert analyze.value_per_eok({"score": 60.0, "price_manwon": 0}) is None
        assert analyze.value_per_eok({"score": 60.0}) is None

    def test_missing_score_is_none(self):
        assert analyze.value_per_eok({"price_manwon": 50000}) is None
