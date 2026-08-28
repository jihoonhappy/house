"""면적대 분리·대표가격·점수화 로직 테스트."""
import pytest

from aptfinder import analyze

BANDS = [
    {"label": "소형(~55㎡)", "min": 0, "max": 55},
    {"label": "59㎡형", "min": 55, "max": 66},
    {"label": "84㎡형", "min": 80, "max": 96},
    {"label": "115㎡+", "min": 115, "max": 0},
]

CRITERIA = {
    "price_min": 60000, "price_max": 70000,
    "lookback_months": 12, "price_window_months": 6,
    "min_trade_count": 2, "area_min_m2": 59, "area_max_m2": 0,
    "station_max_distance_m": 500, "school_max_distance_m": 800,
    "school_filter": False,
}


def trade(apt="까치마을", area=84.9, price=65000, ym="202608", dong="수서동", jibun="746"):
    return {"gu": "강남구", "sgg_code": "11680", "dong": dong, "jibun": jibun, "apt": apt,
            "price_manwon": price, "area_m2": area, "floor": "6",
            "build_year": "1993", "deal_ym": ym}


class TestBandFor:
    def test_matches_by_half_open_interval(self):
        assert analyze.band_for(59.9, BANDS) == "59㎡형"
        assert analyze.band_for(55.0, BANDS) == "59㎡형"
        assert analyze.band_for(54.9, BANDS) == "소형(~55㎡)"

    def test_max_zero_means_no_upper_bound(self):
        assert analyze.band_for(200.0, BANDS) == "115㎡+"

    def test_returns_none_when_no_band_matches(self):
        assert analyze.band_for(100.0, BANDS) is None


class TestAreaFilter:
    def test_rejects_below_minimum(self):
        assert analyze.passes_area(58.9, CRITERIA) is False
        assert analyze.passes_area(59.0, CRITERIA) is True

    def test_zero_max_means_unbounded(self):
        assert analyze.passes_area(300.0, CRITERIA) is True

    def test_respects_max_when_set(self):
        criteria = {**CRITERIA, "area_max_m2": 100}
        assert analyze.passes_area(120.0, criteria) is False


class TestRepresentativePrice:
    def test_prefers_recent_window_when_enough_trades(self):
        rows = [trade(price=90000, ym="202601"), trade(price=90000, ym="202602"),
                trade(price=65000, ym="202607"), trade(price=67000, ym="202608")]
        price, count, basis = analyze.representative_price(
            rows, {"202607", "202608"}, min_trade_count=2)
        assert price == 66000
        assert count == 2
        assert "최근" in basis

    def test_falls_back_to_full_period_when_recent_is_thin(self):
        rows = [trade(price=60000, ym="202601"), trade(price=62000, ym="202602"),
                trade(price=99000, ym="202608")]
        price, count, basis = analyze.representative_price(
            rows, {"202608"}, min_trade_count=2)
        assert price == 62000
        assert count == 3
        assert "전체" in basis


class TestBuildCandidates:
    def test_splits_same_complex_by_area_band(self):
        """34㎡와 84㎡가 한 중앙값에 섞이면 안 된다."""
        trades = [
            trade(area=34.4, price=30000, ym="202607"),
            trade(area=34.4, price=32000, ym="202608"),
            trade(area=84.9, price=65000, ym="202607"),
            trade(area=84.9, price=66000, ym="202608"),
        ]
        # 면적대 분리 자체를 보기 위해 면적·가격 필터는 열어둔다
        criteria = {**CRITERIA, "area_min_m2": 0, "price_min": 0, "price_max": 999999}
        result = analyze.build_candidates(trades, BANDS, criteria, {"202607", "202608"})
        bands = {c["area_band"]: c["price_manwon"] for c in result}
        assert bands == {"소형(~55㎡)": 31000, "84㎡형": 65500}

    def test_area_minimum_drops_small_units(self):
        trades = [trade(area=34.4, price=65000, ym="202607"),
                  trade(area=34.4, price=65000, ym="202608")]
        assert analyze.build_candidates(trades, BANDS, CRITERIA, {"202607", "202608"}) == []

    def test_price_range_filter(self):
        trades = [trade(price=80000, ym="202607"), trade(price=82000, ym="202608")]
        assert analyze.build_candidates(trades, BANDS, CRITERIA, {"202607", "202608"}) == []

    def test_requires_minimum_trade_count(self):
        trades = [trade(price=65000, ym="202608")]
        assert analyze.build_candidates(trades, BANDS, CRITERIA, {"202608"}) == []

    def test_keeps_addr_and_metadata(self):
        trades = [trade(price=65000, ym="202607"), trade(price=66000, ym="202608")]
        candidate = analyze.build_candidates(trades, BANDS, CRITERIA, {"202607", "202608"})[0]
        assert candidate["addr"] == "서울 강남구 수서동 746"
        assert candidate["apt"] == "까치마을"
        assert candidate["trade_count"] == 2
        assert candidate["latest_deal_ym"] == "202608"
        assert candidate["latest_price_manwon"] == 66000

    def test_uses_most_common_jibun_for_address(self):
        trades = [trade(jibun="746", ym="202606"), trade(jibun="746", ym="202607"),
                  trade(jibun="999", ym="202608")]
        candidate = analyze.build_candidates(
            trades, BANDS, CRITERIA, {"202606", "202607", "202608"})[0]
        assert candidate["addr"].endswith("746")


class TestScore:
    def test_closer_station_scores_higher(self):
        weights = {"station_distance": 40, "school_distance": 30,
                   "trade_activity": 15, "build_year": 15}
        near = analyze.score_candidate(
            {"station_dist_m": 50, "school_dist_m": 100, "trade_count": 20,
             "build_year": "2020"}, weights, CRITERIA, current_year=2026)
        far = analyze.score_candidate(
            {"station_dist_m": 480, "school_dist_m": 100, "trade_count": 20,
             "build_year": "2020"}, weights, CRITERIA, current_year=2026)
        assert near > far

    def test_missing_school_does_not_go_negative(self):
        weights = {"station_distance": 40, "school_distance": 30,
                   "trade_activity": 15, "build_year": 15}
        result = analyze.score_candidate(
            {"station_dist_m": 100, "school_dist_m": None, "trade_count": 1,
             "build_year": ""}, weights, CRITERIA, current_year=2026)
        assert 0 <= result <= 100

    def test_perfect_candidate_approaches_full_marks(self):
        weights = {"station_distance": 40, "school_distance": 30,
                   "trade_activity": 15, "build_year": 15}
        result = analyze.score_candidate(
            {"station_dist_m": 0, "school_dist_m": 0, "trade_count": 40,
             "build_year": "2026"}, weights, CRITERIA, current_year=2026)
        assert result == pytest.approx(100.0)


class TestRegion:
    def test_maps_district_code_to_province(self):
        assert analyze.sido_of("11680") == "서울"
        assert analyze.sido_of("41135") == "경기"
        assert analyze.sido_of("28185") == "인천"

    def test_unknown_code_is_blank(self):
        assert analyze.sido_of("99999") == ""
        assert analyze.sido_of(None) == ""

    def test_gyeonggi_candidate_address_says_gyeonggi(self):
        trades = [{"gu": "성남시 분당구", "sgg_code": "41135", "dong": "정자동", "jibun": "20",
                   "apt": "정자아파트", "price_manwon": 65000, "area_m2": 84.9, "floor": "3",
                   "build_year": "2001", "deal_ym": ym} for ym in ("202607", "202608")]
        candidate = analyze.build_candidates(trades, BANDS, CRITERIA, {"202607", "202608"})[0]
        assert candidate["addr"] == "경기 성남시 분당구 정자동 20"
        assert candidate["sido"] == "경기"
