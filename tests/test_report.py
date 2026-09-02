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
        title = report.build_title({**CRITERIA, "require_station": True})
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


class TestValueColumn:
    def test_renders_value_column(self):
        html = report.render([{**CANDIDATE, "value_per_eok": 11.0}], CRITERIA)
        assert "가성비" in html and "value_per_eok" in html

    def test_price_filter_inputs_exist(self):
        html = report.render([CANDIDATE], CRITERIA)
        assert 'id="minPrice"' in html and 'id="maxPrice"' in html


class TestTableIntegrity:
    """헤더와 셀 개수가 어긋나면 표 전체가 한 칸씩 밀린다. 실제로 그런 버그가 있었다."""

    def _counts(self, html):
        import re
        # <thead>가 <th...>로 잘못 잡히지 않도록 닫는 태그까지 요구한다
        headers = re.findall(r"<th\b[^>]*>.*?</th>", html, re.S)
        row = re.search(r"return `<tr data-i=.*?</tr>`;", html, re.S)
        cells = re.findall(r"<td\b[^>]*>.*?</td>", row.group(0), re.S) if row else []
        return len(headers), len(cells)

    def test_header_and_cell_counts_match(self):
        headers, cells = self._counts(report.render([CANDIDATE], CRITERIA))
        assert headers == cells, f"헤더 {headers}개 vs 셀 {cells}개 — 표가 어긋난다"

    def test_every_sortable_header_maps_to_a_candidate_field(self):
        import re
        html = report.render([CANDIDATE], CRITERIA)
        keys = re.findall(r'<th data-k="([^"]+)"', html)
        allowed = set(CANDIDATE) | {"value_per_eok", "commute_min", "commute_mode",
                                    "transit_min", "drive_min", "sido",
                                    "vs_avg_pct", "vs_peak_pct",
                                    "middle_school_count", "high_school_count"}
        assert [k for k in keys if k not in allowed] == []

    def test_commute_column_is_present(self):
        assert "서울까지" in report.render([CANDIDATE], CRITERIA)


GROUPS = {
    "transit": {"label": "교통", "items": ["commute", "station_distance"]},
    "life": {"label": "생활인프라", "items": ["hospital", "mart", "market"]},
}
MAXIMA = {"transit": 30, "life": 20}


class TestGroupColumns:
    def test_group_metadata_is_injected(self):
        html = report.render([CANDIDATE], CRITERIA, GROUPS, MAXIMA)
        assert "__GROUPS__" not in html
        assert '"label": "생활인프라"' in html or '"label":"생활인프라"' in html
        assert '"max": 20' in html or '"max":20' in html

    def test_renders_without_groups(self):
        html = report.render([CANDIDATE], CRITERIA)
        assert "__GROUPS__" not in html
        assert "const GROUPS = [];" in html

    def test_group_columns_come_from_one_array(self):
        """헤더와 셀을 같은 GROUPS 배열로 만들어야 열이 어긋나지 않는다."""
        html = report.render([CANDIDATE], CRITERIA, GROUPS, MAXIMA)
        assert "GROUPS].reverse().forEach" in html      # 헤더 생성
        assert "GROUPS.map(g => `<td class=\"grp\">" in html   # 셀 생성

    def test_write_passes_groups_through(self, tmp_path):
        out = report.write([CANDIDATE], CRITERIA, tmp_path / "d.html", GROUPS, MAXIMA)
        assert "생활인프라" in out.read_text(encoding="utf-8")


class TestCommuteModeColumns:
    def test_shows_transit_and_driving_side_by_side(self):
        html = report.render([{**CANDIDATE, "commute_min": 40.0, "commute_mode": "자차",
                               "transit_min": 53.0, "drive_min": 40.0, "drive_km": 25.0,
                               "drive_toll": 0, "transit_to": "시청", "drive_to": "시청"}],
                             CRITERIA)
        assert "지하철·자차" in html
        assert "transit_min" in html and "drive_min" in html

    def test_transit_only_filter_exists(self):
        assert 'id="transitOnly"' in report.render([CANDIDATE], CRITERIA)


class TestPriceHistoryColumns:
    HIST = {**CANDIDATE, "price_avg_manwon": 62000, "price_peak_manwon": 70000,
            "price_peak_half": "2022H1", "price_low_manwon": 55000,
            "vs_avg_pct": 4.8, "vs_peak_pct": -7.1, "history_count": 42,
            "price_history": [{"half": "2021H1", "median": 58000, "count": 5},
                              {"half": "2021H2", "median": 65000, "count": 7},
                              {"half": "2022H1", "median": 70000, "count": 4}]}

    def test_renders_history_columns(self):
        html = report.render([self.HIST], CRITERIA)
        assert "7년평균비" in html and "전고점비" in html and "추이" in html

    def test_includes_sparkline_builder(self):
        assert "function spark(series)" in report.render([self.HIST], CRITERIA)

    def test_history_series_reaches_the_page(self):
        html = report.render([self.HIST], CRITERIA)
        assert '"half": "2021H2"' in html or '"half":"2021H2"' in html


class TestStationConditionInTitle:
    def test_shows_station_condition_only_when_required(self):
        required = report.build_title({**CRITERIA, "require_station": True,
                                       "station_max_distance_m": 800})
        assert "역세권 800m" in required

    def test_omits_station_condition_when_not_required(self):
        """필터가 아닌 조건을 제목에 쓰면 표와 어긋난 설명이 된다."""
        relaxed = report.build_title({**CRITERIA, "require_station": False,
                                      "station_max_distance_m": 800})
        assert "역세권" not in relaxed
