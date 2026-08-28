"""대시보드 렌더링 테스트."""
from aptfinder import report

CRITERIA = {"price_min": 60000, "price_max": 70000, "area_min_m2": 59,
            "station_max_distance_m": 500, "min_households": 300,
            "exclude_complex_types": ["주상복합"]}

CANDIDATE = {
    "gu": "강남구", "dong": "수서동", "apt": "까치마을", "area_band": "84㎡형",
    "households": 930, "dong_count": 8, "complex_type": "아파트", "approved_on": "2015-03-02",
    "middle_school_count": 2, "high_school_count": 1, "academy_count": 45,
    "hospital_count": 30, "hospital_nearest_m": 120,
    "mart_nearest_m": 700, "market_nearest_m": 900,
    "price_manwon": 65000, "price_basis": "최근 4건", "trade_count": 9,
    "latest_deal_ym": "202608", "latest_price_manwon": 66000, "build_year": "1993",
    "station": "수서", "station_line": "3호선", "station_dist_m": 320,
    "school": "수서초등학교", "school_dist_m": 410, "score": 71.2,
    "lat": 37.4844, "lon": 127.0983, "addr": "서울 강남구 수서동 746",
}


class TestTitle:
    def test_reflects_configured_conditions(self):
        title = report.build_title(CRITERIA)
        assert "6~7억" in title and "59㎡+" in title and "500m" in title

    def test_omits_area_clause_when_no_minimum(self):
        title = report.build_title({**CRITERIA, "area_min_m2": 0})
        assert "㎡" not in title and "6~7억" in title

    def test_shows_household_and_exclusion_conditions(self):
        title = report.build_title(CRITERIA)
        assert "300세대+" in title and "주상복합 제외" in title


class TestRender:
    def test_embeds_candidate_data(self):
        html = report.render([CANDIDATE], CRITERIA)
        assert "까치마을" in html
        assert "84㎡형" in html
        assert "__DATA__" not in html and "__TITLE__" not in html

    def test_escapes_angle_brackets_to_protect_script_block(self):
        evil = {**CANDIDATE, "apt": "</script><img src=x>"}
        html = report.render([evil], CRITERIA)
        assert "</script><img" not in html
        assert "\\u003c/script" in html

    def test_renders_with_no_candidates(self):
        html = report.render([], CRITERIA)
        assert "const DATA = [];" in html

    def test_writes_file(self, tmp_path):
        out = report.write([CANDIDATE], CRITERIA, tmp_path / "d.html")
        assert out.exists() and "까치마을" in out.read_text(encoding="utf-8")


class TestCommuteInTitle:
    def test_shows_commute_limit(self):
        title = report.build_title({**CRITERIA, "max_commute_min": 45})
        assert "서울 45분" in title

    def test_omits_commute_when_unlimited(self):
        assert "분" not in report.build_title({**CRITERIA, "max_commute_min": 0})

    def test_renders_commute_columns(self):
        html = report.render([{**CANDIDATE, "sido": "경기", "commute_min": 27.4,
                               "commute_to": "강남"}], CRITERIA)
        assert "서울까지" in html and "commute_min" in html


class TestRegionsInTitle:
    def test_lists_regions_present_in_candidates(self):
        assert report.regions_of([{"sido": "경기"}, {"sido": "서울"}]) == ["서울", "경기"]

    def test_ignores_missing_region(self):
        assert report.regions_of([{"apt": "x"}]) == []

    def test_title_reflects_regions(self):
        assert report.build_title(CRITERIA, ["서울", "경기"]).startswith("실거주 아파트 후보 (서울·경기")

    def test_render_uses_candidate_regions(self):
        html = report.render([{**CANDIDATE, "sido": "경기"}], CRITERIA)
        assert "후보 (경기 ·" in html


class TestPublishCopy:
    def test_creates_missing_directories(self, tmp_path):
        out = report.write([CANDIDATE], CRITERIA, tmp_path / "docs" / "index.html")
        assert out.exists()
        assert out.parent.name == "docs"

    def test_published_copy_matches_local(self, tmp_path):
        local = report.write([CANDIDATE], CRITERIA, tmp_path / "dashboard.html")
        published = report.write([CANDIDATE], CRITERIA, tmp_path / "docs" / "index.html")
        assert local.read_text(encoding="utf-8") == published.read_text(encoding="utf-8")
