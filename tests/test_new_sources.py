"""신규 데이터 소스 테스트 - 공동주택 정보(OpenAptInfo)와 단지 식별정보(REB CSV)."""
import json

import pytest

from aptfinder import config
from aptfinder.errors import ApiError, MissingDataError
from aptfinder.sources import aptinfo, reb

APT_ROW = {
    "APT_CD": "A15679103", "APT_NM": "우리유앤미", "CMPX_CLSF": "아파트",
    "SGG_ADDR": "동작구", "EMD_ADDR": "흑석동", "APT_RDN_ADDR": "서울특별시 동작구 서달로 83",
    "TNOHSH": "206.0", "WHOL_DONG_CNT": "2.0", "PRK_CNTOM": "223.0",
    "MN_MTHD": "개별난방", "BLDR": "우리건설",
    "USE_APRV_YMD": "2003-12-26 00:00:00.0", "XCRD": "126.9596386", "YCRD": "37.5006676",
}

CSV_TEXT = """단지고유번호,필지고유번호,주소,단지명_공시가격,단지명_건축물대장,단지명_도로명주소,단지종류,동수,세대수,사용승인일
11110100000004,1111010100100560045,서울특별시 종로구 청운동 56-45,청운현대,,청운현대(아)104동,1,4,60,2000-10-02
11110200000003,1111010100100010000,서울특별시 종로구 청운동 1,청운벽산빌리지,,청운벽산빌리지,2,9,126,1988-11-11
41135100000001,4113510300100200000,경기도 성남분당구 정자동 20,정자아파트,정자아파트,정자,1,5,500,2001-03-01
11680100000001,1168010600107460000,서울특별시 강남구 수서동 746,까치마을,까치마을아파트,까치마을,1,10,1404,1993-05-01
"""


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    target = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", target)
    return target


class TestAptInfoParsing:
    def test_maps_fields_and_types(self):
        row = aptinfo.parse_rows([APT_ROW])[0]
        assert row["name"] == "우리유앤미"
        assert row["complex_type"] == "아파트"
        assert row["households"] == 206
        assert row["dong_count"] == 2
        assert row["parking"] == 223
        assert row["lat"] == pytest.approx(37.5006676)
        assert row["approved_on"] == "2003-12-26"

    def test_skips_rows_without_name(self):
        assert aptinfo.parse_rows([{**APT_ROW, "APT_NM": " "}]) == []

    def test_tolerates_missing_numbers(self):
        row = aptinfo.parse_rows([{**APT_ROW, "TNOHSH": "", "PRK_CNTOM": "***",
                                   "XCRD": "", "YCRD": ""}])[0]
        assert row["households"] is None
        assert row["parking"] is None
        assert row["lat"] is None

    def test_identifies_mixed_use_complexes(self):
        row = aptinfo.parse_rows([{**APT_ROW, "CMPX_CLSF": "주상복합"}])[0]
        assert row["complex_type"] == "주상복합"


class TestAptInfoCollect:
    def test_fetches_and_caches(self, monkeypatch, data_dir):
        payload = {"OpenAptInfo": {"list_total_count": 1, "row": [APT_ROW]}}
        monkeypatch.setattr(aptinfo, "get_json", lambda url, **kw: payload)
        result = aptinfo.collect("key")
        assert result[0]["name"] == "우리유앤미"
        assert (data_dir / "apt_info.json").exists()

    def test_uses_cache_on_second_call(self, monkeypatch, data_dir):
        data_dir.mkdir(parents=True)
        (data_dir / "apt_info.json").write_text(
            json.dumps([{"name": "캐시단지"}]), encoding="utf-8")

        def explode(*args, **kwargs):
            raise AssertionError("캐시가 있으면 호출하면 안 된다")

        monkeypatch.setattr(aptinfo, "get_json", explode)
        assert aptinfo.collect("key")[0]["name"] == "캐시단지"

    def test_reports_open_data_error(self, monkeypatch, data_dir):
        monkeypatch.setattr(aptinfo, "get_json", lambda url, **kw: {
            "RESULT": {"CODE": "ERROR-500", "MESSAGE": "서버 오류입니다."}})
        with pytest.raises(ApiError, match="ERROR-500"):
            aptinfo.collect("key")


class TestRebParsing:
    def test_keeps_only_apartments_nationwide(self):
        import csv
        import io
        rows = reb.parse_rows(csv.DictReader(io.StringIO(CSV_TEXT)))
        names = {alias for r in rows for alias in r["aliases"]}
        assert "청운벽산빌리지" not in names   # 단지종류 2 = 연립주택
        assert "정자아파트" in names           # 경기도도 포함한다
        assert len(rows) == 3

    def test_district_code_comes_from_parcel_number(self):
        import csv
        import io
        rows = reb.parse_rows(csv.DictReader(io.StringIO(CSV_TEXT)))
        jeongja = next(r for r in rows if r["dong"] == "정자동")
        assert jeongja["sgg_code"] == "41135"   # 성남시 분당구
        assert jeongja["sido"] == "경기도"

    def test_splits_jibun_into_bonbun_and_bubun(self):
        import csv
        import io
        rows = reb.parse_rows(csv.DictReader(io.StringIO(CSV_TEXT)))
        cheongun = next(r for r in rows if r["dong"] == "청운동")
        assert cheongun["jibun"] == "56-45"
        assert cheongun["bonbun"] == "56"

    def test_collects_all_name_variants_as_aliases(self):
        import csv
        import io
        rows = reb.parse_rows(csv.DictReader(io.StringIO(CSV_TEXT)))
        kkachi = next(r for r in rows if r["dong"] == "수서동")
        assert set(kkachi["aliases"]) == {"까치마을", "까치마을아파트"}
        assert kkachi["households"] == 1404


class TestRebLoad:
    def test_reads_csv_and_caches(self, tmp_path, monkeypatch, data_dir):
        monkeypatch.setattr(reb, "PROJECT_ROOT", tmp_path)
        path = tmp_path / "한국부동산원_공동주택 단지 식별정보_기본정보_20250918.csv"
        path.write_text(CSV_TEXT, encoding="utf-8-sig")
        result = reb.load()
        assert len(result) == 3
        assert (data_dir / "reb_complexes.json").exists()

    def test_missing_csv_explains_where_to_get_it(self, tmp_path, monkeypatch, data_dir):
        monkeypatch.setattr(reb, "PROJECT_ROOT", tmp_path)
        with pytest.raises(MissingDataError, match="data.go.kr"):
            reb.load()

    def test_configured_path_that_does_not_exist_is_reported(self, tmp_path, monkeypatch, data_dir):
        monkeypatch.setattr(reb, "PROJECT_ROOT", tmp_path)
        with pytest.raises(MissingDataError, match="찾을 수 없습니다"):
            reb.load("없는파일.csv")

    def test_reads_cp949_encoded_file(self, tmp_path, monkeypatch, data_dir):
        monkeypatch.setattr(reb, "PROJECT_ROOT", tmp_path)
        path = tmp_path / "한국부동산원_공동주택 단지 식별정보_x.csv"
        path.write_bytes(CSV_TEXT.encode("cp949"))
        assert len(reb.load()) == 3

    def test_index_covers_both_full_jibun_and_bonbun(self, tmp_path, monkeypatch, data_dir):
        monkeypatch.setattr(reb, "PROJECT_ROOT", tmp_path)
        (tmp_path / "한국부동산원_공동주택 단지 식별정보_y.csv").write_text(
            CSV_TEXT, encoding="utf-8-sig")
        index = reb.index_by_address(reb.load())
        assert ("11110", "청운동", "56-45") in index
        assert ("11110", "청운동", "56") in index


class TestSidoNormalization:
    def test_strips_administrative_suffix(self):
        assert aptinfo.normalize_sido("서울특별시") == "서울"
        assert aptinfo.normalize_sido("경기도") == "경기"
        assert aptinfo.normalize_sido("인천광역시") == "인천"

    def test_already_short_names_pass_through(self):
        assert aptinfo.normalize_sido("서울") == "서울"

    def test_blank_is_safe(self):
        assert aptinfo.normalize_sido(None) == ""

    def test_parse_rows_uses_normalized_sido(self):
        row = aptinfo.parse_rows([{**APT_ROW, "CTPV_ADDR": "서울특별시"}])[0]
        assert row["sido"] == "서울"
