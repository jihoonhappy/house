"""파일 캐시·수집 오케스트레이션 테스트. 실제 네트워크는 쓰지 않는다."""
import json

import pytest

from aptfinder import config, http, pipeline, report
from aptfinder.errors import ApiError, ConfigError, MissingDataError
from aptfinder.sources import aptinfo, reb, rtms, schools, stations, subway_lines

VALID_CONFIG = """
api_keys: {data_go_kr: k1, seoul_open_data: k2, neis: k3, kakao_rest: k4}
criteria:
  price_min: 60000
  price_max: 70000
  lookback_months: 12
  price_window_months: 6
  min_trade_count: 2
  min_households: 0
  max_commute_min: 0
  exclude_complex_types: ["주상복합"]
  require_complex_match: false
  area_min_m2: 59
  area_max_m2: 0
  station_max_distance_m: 500
  school_max_distance_m: 800
  school_filter: false
area_bands: [{label: "84㎡형", min: 80, max: 96}]
access: {destinations: ["강남"]}
transit: {default_speed_kmh: 37}
school_office_codes: ["B10"]
school_zone: {middle_radius_m: 1000, high_radius_m: 1500, schools_for_full_score: 3, academy_saturation: 80}
households_for_full_score: 1500
amenities:
  hospital: {kind: category, code: HP8, radius_m: 1000}
scoring: {station_distance: 40, school_distance: 30, trade_activity: 15, build_year: 15}
seoul_districts: {"11680": 강남구}
"""


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """data/ 폴더를 임시 경로로 돌려 실제 캐시를 건드리지 않는다."""
    target = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", target)
    return target


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(VALID_CONFIG, encoding="utf-8")
    return config.load(path)


class TestConfigLoad:
    def test_loads_from_disk(self, cfg):
        assert cfg["criteria"]["area_min_m2"] == 59
        assert cfg["seoul_districts"]["11680"] == "강남구"

    def test_missing_file_explains_how_to_start(self, tmp_path):
        with pytest.raises(ConfigError, match="config.example.yaml"):
            config.load(tmp_path / "nope.yaml")

    def test_broken_yaml_is_reported(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("api_keys: [unclosed\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="문법"):
            config.load(path)

    def test_non_mapping_root_is_rejected(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("- just\n- a list\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="매핑"):
            config.load(path)


def xml_page(items, total):
    body = "".join(
        f"<item><aptNm>{a}</aptNm><dealAmount>{p}</dealAmount><dealMonth>8</dealMonth>"
        f"<dealYear>2026</dealYear><excluUseAr>84.9</excluUseAr><jibun>746</jibun>"
        f"<umdNm>수서동</umdNm><buildYear>2015</buildYear></item>" for a, p in items)
    return ("<response><header><resultCode>000</resultCode></header><body><items>"
            f"{body}</items><totalCount>{total}</totalCount></body></response>")


class TestRtmsCollect:
    def test_pages_until_total_count_is_reached(self, monkeypatch, data_dir):
        pages = []

        def fake_get(url, **kwargs):
            pages.append(url)
            return xml_page([("단지A", "65,000")], total=rtms.ROWS_PER_PAGE + 1)

        monkeypatch.setattr(rtms, "get", fake_get)
        rows = rtms.fetch_month("k", "11680", "강남구", "202608", sleep=lambda s: None)
        assert len(pages) == 2
        assert len(rows) == 2

    def test_reuses_cached_month(self, monkeypatch, data_dir, cfg):
        data_dir.mkdir(parents=True)
        cached = [{"gu": "강남구", "apt": "캐시단지", "deal_ym": "202608"}]
        for month in rtms.recent_months(cfg["criteria"]["lookback_months"]):
            (data_dir / f"trades_11680_{month}.json").write_text(
                json.dumps(cached), encoding="utf-8")

        def explode(*args, **kwargs):
            raise AssertionError("캐시가 있으면 네트워크를 호출하면 안 된다")

        monkeypatch.setattr(rtms, "get", explode)
        rows = rtms.collect(cfg, "k", sleep=lambda s: None)
        assert len(rows) == 12
        assert json.loads((data_dir / "trades_all.json").read_text(encoding="utf-8"))

    def test_one_failed_month_does_not_abort_the_run(self, monkeypatch, data_dir, cfg):
        calls = {"n": 0}

        def flaky(url, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ApiError("HTTP 500")
            return xml_page([("단지A", "65,000")], total=1)

        monkeypatch.setattr(rtms, "get", flaky)
        rows = rtms.collect(cfg, "k", sleep=lambda s: None)
        assert len(rows) == 11  # 12개월 중 1개월만 실패


class TestStationsCollect:
    def test_fetches_and_caches(self, monkeypatch, data_dir):
        payload = {"subwayStationMaster": {"list_total_count": 1, "row": [
            {"BLDN_NM": "수서", "ROUTE": "3호선", "LAT": "37.487", "LOT": "127.1015"}]}}
        monkeypatch.setattr(stations, "get_json", lambda url, **kw: payload)
        result = stations.collect("key")
        assert result[0]["name"] == "수서"
        assert (data_dir / "stations.json").exists()

    def test_second_call_uses_cache(self, monkeypatch, data_dir):
        data_dir.mkdir(parents=True)
        (data_dir / "stations.json").write_text(
            json.dumps([{"name": "캐시역", "lat": 1.0, "lon": 2.0}]), encoding="utf-8")

        def explode(*args, **kwargs):
            raise AssertionError("캐시가 있으면 호출하면 안 된다")

        monkeypatch.setattr(stations, "get_json", explode)
        assert stations.collect("key")[0]["name"] == "캐시역"

    def test_zero_parsed_rows_is_an_error_with_guidance(self, monkeypatch, data_dir):
        payload = {"subwayStationMaster": {"list_total_count": 0, "row": []}}
        monkeypatch.setattr(stations, "get_json", lambda url, **kw: payload)
        with pytest.raises(ApiError, match="필드명"):
            stations.collect("key")


class FakeGeocoder:
    def __init__(self):
        self.calls = []

    def lookup(self, address, keyword=None):
        self.calls.append(address)
        return (37.5, 127.0)

    def save(self):
        pass


class TestSchoolsCollect:
    def test_geocodes_schools_but_skips_universities(self, monkeypatch, data_dir):
        payload = {"schoolInfo": [{"head": []}, {"row": [
            {"SCHUL_NM": "수서초등학교", "SCHUL_KND_SC_NM": "초등학교", "ORG_RDNMA": "주소1"},
            {"SCHUL_NM": "가락고등학교", "SCHUL_KND_SC_NM": "고등학교", "ORG_RDNMA": "주소2"},
            {"SCHUL_NM": "어느대학교", "SCHUL_KND_SC_NM": "대학교", "ORG_RDNMA": "주소3"}]}]}
        monkeypatch.setattr(schools, "get_json", lambda url, **kw: payload)
        geocoder = FakeGeocoder()
        result = schools.collect("key", geocoder)
        assert geocoder.calls == ["주소1", "주소2"]   # 대학교는 제외
        assert result[0]["lat"] == 37.5 and result[1]["lat"] == 37.5
        assert "lat" not in result[2]

    def test_reports_neis_error(self, monkeypatch, data_dir):
        monkeypatch.setattr(schools, "get_json", lambda url, **kw: {
            "RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}})
        with pytest.raises(ApiError, match="INFO-200"):
            schools.collect("key", FakeGeocoder())


class TestPipeline:
    def test_analyze_requires_collected_data(self, data_dir, cfg):
        with pytest.raises(MissingDataError, match="01_collect.py"):
            pipeline.run_analyze(cfg)

    def test_analyze_produces_candidates_json_and_csv(self, monkeypatch, data_dir, cfg):
        data_dir.mkdir(parents=True)
        trades = [{"gu": "강남구", "sgg_code": "11680", "dong": "수서동",
                   "jibun": "746", "apt": "까치마을",
                   "price_manwon": 65000, "area_m2": 84.9, "floor": "6",
                   "build_year": "2015", "deal_ym": ym}
                  for ym in rtms.recent_months(2)]
        (data_dir / "trades_all.json").write_text(json.dumps(trades), encoding="utf-8")
        (data_dir / "stations.json").write_text(json.dumps(
            [{"name": "수서", "line": "3호선", "lat": 37.4870, "lon": 127.1015},
             {"name": "강남", "line": "3호선", "lat": 37.4980, "lon": 127.0279}]), encoding="utf-8")
        (data_dir / "subway_lines.json").write_text(json.dumps(
            [{"name": "수서", "line": "3호선", "order_code": "K01"},
             {"name": "강남", "line": "3호선", "order_code": "K02"}]), encoding="utf-8")
        (data_dir / "schools.json").write_text(json.dumps(
            [{"name": "수서초", "kind": "초등학교", "lat": 37.4880, "lon": 127.1000}]),
            encoding="utf-8")
        (data_dir / "apt_info.json").write_text(json.dumps(
            [{"name": "까치마을", "complex_type": "아파트", "gu": "강남구", "dong": "수서동",
              "households": 800, "parking": 700, "heating": "지역난방", "builder": "A",
              "lat": 37.4868, "lon": 127.1012}]), encoding="utf-8")
        (data_dir / "reb_complexes.json").write_text(json.dumps(
            [{"complex_id": "1", "sgg_code": "11680", "gu": "강남구", "dong": "수서동",
              "jibun": "746", "bonbun": "746", "aliases": ["까치마을"], "households": 800,
              "dong_count": 8, "approved_on": "2015-03-02"}]), encoding="utf-8")

        class StubFinder:
            calls = 0

            def survey_all(self, lat, lon, specs):
                return {"hospital_count": 10, "hospital_nearest_m": 200,
                        "hospital_nearest": "의원"}

            def save(self):
                pass

        monkeypatch.setattr(pipeline, "make_amenity_finder", lambda c: StubFinder())
        class StubGeocoder:
            def lookup(self, address, keyword=None):
                return (37.4868, 127.1012)

            def save(self):
                pass

        monkeypatch.setattr(pipeline, "make_geocoder", lambda c: StubGeocoder())
        result = pipeline.run_analyze(cfg)
        assert len(result) == 1 and result[0]["apt"] == "까치마을"
        assert json.loads((data_dir / "candidates.json").read_text(encoding="utf-8"))
        assert "까치마을" in (data_dir / "candidates.csv").read_text(encoding="utf-8-sig")

    def test_dashboard_reads_candidates(self, data_dir, cfg, tmp_path, monkeypatch):
        data_dir.mkdir(parents=True)
        (data_dir / "candidates.json").write_text(json.dumps([]), encoding="utf-8")
        monkeypatch.setattr(report, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        out = pipeline.run_dashboard(cfg)
        assert out.exists()

    def test_collect_runs_every_source(self, monkeypatch, data_dir, cfg):
        stages = []
        monkeypatch.setattr(rtms, "collect", lambda *a, **k: stages.append("trades"))
        monkeypatch.setattr(stations, "collect", lambda *a, **k: stages.append("stations"))
        monkeypatch.setattr(reb, "load", lambda *a, **k: stages.append("reb"))
        monkeypatch.setattr(aptinfo, "collect", lambda *a, **k: stages.append("aptinfo"))
        monkeypatch.setattr(subway_lines, "collect", lambda *a, **k: stages.append("lines"))
        monkeypatch.setattr(schools, "collect", lambda *a, **k: stages.append("schools"))
        monkeypatch.setattr(pipeline, "make_geocoder", lambda c: FakeGeocoder())
        pipeline.run_collect(cfg)
        assert stages == ["trades", "stations", "reb", "aptinfo", "lines", "schools"]


class TestHttpErrors:
    def test_non_retriable_status_fails_immediately(self, monkeypatch):
        import urllib.error
        import urllib.request
        calls = {"n": 0}

        def forbidden(req, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(
                "u", 403, "Forbidden", {}, __import__("io").BytesIO(b'{"errorType":"x"}'))

        monkeypatch.setattr(urllib.request, "urlopen", forbidden)
        with pytest.raises(ApiError, match="403"):
            http.get("https://x", sleep=lambda s: None)
        assert calls["n"] == 1

    def test_non_json_response_is_reported(self, monkeypatch):
        monkeypatch.setattr(http, "get", lambda *a, **k: "<html>error page</html>")
        with pytest.raises(ApiError, match="JSON"):
            http.get_json("https://x")


class TestNationwideClassification:
    def _candidates(self):
        return [{"gu": "성남시 분당구", "dong": "정자동", "jibun": "99", "apt": "정자타워",
                 "sido": "경기", "complex_type": "", "type_checked": True},
                {"gu": "강남구", "dong": "수서동", "apt": "까치마을",
                 "sido": "서울", "complex_type": "아파트", "type_checked": True}]

    def test_skipped_when_list_is_absent(self, data_dir, cfg):
        data_dir.mkdir(parents=True)
        result, covered = pipeline._classify_nationwide(cfg, self._candidates(), {"서울"})
        assert result[0]["complex_type"] == ""
        assert covered == {"서울"}

    def test_fills_classification_when_list_exists(self, monkeypatch, data_dir, cfg):
        data_dir.mkdir(parents=True)
        (data_dir / "apt_list.json").write_text(json.dumps(
            [{"apt_code": "A41B", "name": "정자타워", "sido": "경기도",
              "sigungu": "성남시 분당구", "dong": "정자동"}]), encoding="utf-8")

        class StubLookup:
            calls = 1

            def __init__(self, *args, **kwargs):
                pass

            def lookup(self, apt_code):
                return {"complex_type": "주상복합", "households": 300, "dong_count": 1,
                        "approved_on": "2005-01-01", "heating": "", "builder": "",
                        "top_floor": 40,
                        "jibun_addr": "경기도 성남시 분당구 정자동 99 정자타워"}

            def save(self):
                pass

        monkeypatch.setattr(pipeline.aptbasis, "AptBasisLookup", StubLookup)
        result, covered = pipeline._classify_nationwide(cfg, self._candidates(), {"서울"})
        assert result[0]["complex_type"] == "주상복합"
        assert covered == {"서울", "경기"}

    def test_api_failure_leaves_candidates_untouched(self, monkeypatch, data_dir, cfg):
        data_dir.mkdir(parents=True)
        (data_dir / "apt_list.json").write_text(json.dumps(
            [{"apt_code": "A41B", "name": "정자타워", "sido": "경기도",
              "sigungu": "성남시 분당구", "dong": "정자동"}]), encoding="utf-8")

        class ExplodingLookup:
            calls = 0

            def __init__(self, *args, **kwargs):
                pass

            def lookup(self, apt_code):
                raise ApiError("등록되지 않은 서비스키")

            def save(self):
                pass

        monkeypatch.setattr(pipeline.aptbasis, "AptBasisLookup", ExplodingLookup)
        result, _ = pipeline._classify_nationwide(cfg, self._candidates(), {"서울"})
        assert len(result) == 2
        assert result[0]["complex_type"] == ""


class TestDestinationCoords:
    STATIONS = [{"name": "강남", "line": "2호선", "lat": 37.4980, "lon": 127.0279},
                {"name": "강남", "line": "신분당선", "lat": 37.4968, "lon": 127.0281},
                {"name": "수서", "line": "3호선", "lat": 37.4870, "lon": 127.1015}]

    def test_resolves_named_destinations(self):
        assert pipeline.destination_coords(self.STATIONS, ["강남"]) == {
            "강남": (37.4980, 127.0279)}

    def test_ignores_stations_not_asked_for(self):
        assert "수서" not in pipeline.destination_coords(self.STATIONS, ["강남"])

    def test_takes_the_first_entry_for_duplicated_names(self):
        coords = pipeline.destination_coords(self.STATIONS, ["강남"])
        assert coords["강남"] == (37.4980, 127.0279)   # 2호선 쪽이 먼저

    def test_unknown_destination_is_skipped(self):
        assert pipeline.destination_coords(self.STATIONS, ["없는역"]) == {}


class TestDrivingToggle:
    def test_disabled_returns_none(self, cfg, data_dir):
        assert pipeline.make_driving_times({**cfg, "access": {"driving": False}}) is None

    def test_enabled_builds_lookup(self, cfg, data_dir):
        found = pipeline.make_driving_times(
            {**cfg, "access": {"driving": True, "driving_departure_hour": 8}})
        assert found is not None and found.departure.endswith("0800")
