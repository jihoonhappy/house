"""거래 원본 → 점수화된 후보까지의 통합 흐름 (네트워크 없음)."""
from aptfinder import analyze

BANDS = [{"label": "59㎡형", "min": 55, "max": 66}, {"label": "84㎡형", "min": 80, "max": 96}]
CRITERIA = {"price_min": 60000, "price_max": 70000, "lookback_months": 12,
            "price_window_months": 6, "min_trade_count": 2, "area_min_m2": 59,
            "area_max_m2": 0, "station_max_distance_m": 500,
            "school_max_distance_m": 800, "school_filter": False}
WEIGHTS = {"station_distance": 18, "school_distance": 14, "school_zone": 14,
           "households": 12, "build_year": 10, "hospital": 10, "mart": 8,
           "market": 6, "trade_activity": 8}

# 수서역(37.4870,127.1015) 바로 옆 단지 / 역에서 먼 단지
STATIONS = [{"name": "수서", "line": "3호선", "lat": 37.4870, "lon": 127.1015}]
SCHOOLS = [
    {"name": "수서초등학교", "kind": "초등학교", "lat": 37.4880, "lon": 127.1000},
    {"name": "수서중학교", "kind": "중학교", "lat": 37.4890, "lon": 127.1005},
    {"name": "수서고등학교", "kind": "고등학교", "lat": 37.4900, "lon": 127.1010},
]
SETTINGS = {"middle_radius_m": 1000, "high_radius_m": 1500,
            "schools_for_full_score": 3, "academy_saturation": 80}

COORDS = {"까치마을": (37.4868, 127.1012), "먼단지": (37.5200, 127.1500)}


def trades_for(apt, price):
    return [{"gu": "강남구", "dong": "수서동", "jibun": "746", "apt": apt,
             "price_manwon": price, "area_m2": 84.9, "floor": "6",
             "build_year": "2015", "deal_ym": ym} for ym in ("202607", "202608")]


def run(trades):
    candidates = analyze.build_candidates(trades, BANDS, CRITERIA, {"202607", "202608"})
    located = [{**c, "lat": COORDS[c["apt"]][0], "lon": COORDS[c["apt"]][1]}
               for c in candidates if c["apt"] in COORDS]
    with_distance = [analyze.attach_distances(c, STATIONS, SCHOOLS, SETTINGS) for c in located]
    passed = [c for c in with_distance if analyze.passes_distance(c, CRITERIA)]
    enriched = [{**c, "households": 800, "dong_count": 8, "complex_type": "아파트",
                 "parking": 900, "matched": True, "approved_on": "2015-03-02",
                 "hospital_count": 20, "hospital_nearest_m": 300,
                 "general_hospital_nearest": "수서병원", "general_hospital_nearest_m": 1800,
                 "mart_nearest": "이마트", "mart_nearest_m": 700,
                 "market_nearest": "수서시장", "market_nearest_m": 900,
                 "academy_count": 30, "commute_min": 28.4, "commute_to": "강남"}
                for c in passed]
    return sorted(
        ({**c, "score": analyze.score_candidate(c, WEIGHTS, CRITERIA, SETTINGS, 2026)}
         for c in enriched),
        key=lambda c: -c["score"])


class TestPipeline:
    def test_keeps_complex_within_station_radius(self):
        result = run(trades_for("까치마을", 65000))
        assert [c["apt"] for c in result] == ["까치마을"]
        assert result[0]["station"] == "수서"
        assert result[0]["station_dist_m"] < 500
        assert result[0]["school"] == "수서초등학교"

    def test_drops_complex_outside_station_radius(self):
        assert run(trades_for("먼단지", 65000)) == []

    def test_drops_complex_outside_price_range(self):
        assert run(trades_for("까치마을", 95000)) == []

    def test_score_is_within_bounds(self):
        assert 0 <= run(trades_for("까치마을", 65000))[0]["score"] <= 100

    def test_csv_columns_all_exist_on_candidate(self):
        from aptfinder.pipeline import CSV_COLUMNS
        candidate = run(trades_for("까치마을", 65000))[0]
        missing = [c for c in CSV_COLUMNS if c not in candidate]
        assert missing == []
