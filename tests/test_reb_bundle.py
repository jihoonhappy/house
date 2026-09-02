"""동봉된 단지 데이터(수도권 파생본) 테스트."""
import gzip
import json

import pytest

from aptfinder import config
from aptfinder.errors import MissingDataError
from aptfinder.sources import reb

CSV_TEXT = """단지고유번호,필지고유번호,주소,단지명_공시가격,단지명_건축물대장,단지명_도로명주소,단지종류,동수,세대수,사용승인일
11680100000001,1168010600107460000,서울특별시 강남구 수서동 746,까치마을,까치마을아파트,까치마을,1,10,1404,1993-05-01
41135100000001,4113510300100200000,경기도 성남분당구 정자동 20,정자아파트,,정자,1,5,500,2001-03-01
26110100000001,2611010100100010000,부산광역시 중구 영주동 1,부산아파트,,부산아파트,1,3,100,1990-01-01
"""

BUNDLE = [{"complex_id": "1", "sgg_code": "11680", "sido": "서울특별시", "gu": "강남구",
           "dong": "수서동", "jibun": "746", "bonbun": "746",
           "aliases": ["까치마을"], "households": 1404, "dong_count": 10,
           "approved_on": "1993-05-01"}]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    target = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", target)
    return target


def write_bundle(root, rows):
    path = root / "bundled" / reb.BUNDLE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(
        json.dumps(rows, ensure_ascii=False).encode("utf-8"), 9))
    return path


class TestMetroFilter:
    def test_keeps_only_capital_area(self):
        import csv
        import io
        rows = reb.parse_rows(csv.DictReader(io.StringIO(CSV_TEXT)))
        metro = reb.metro_only(rows)
        assert {r["sgg_code"] for r in metro} == {"11680", "41135"}   # 부산 제외

    def test_keeps_incheon(self):
        assert reb.metro_only([{"sgg_code": "28185"}]) == [{"sgg_code": "28185"}]

    def test_drops_rows_without_code(self):
        assert reb.metro_only([{"sgg_code": ""}]) == []


class TestBundleFallback:
    def test_uses_bundle_when_csv_is_absent(self, tmp_path, monkeypatch, data_dir):
        monkeypatch.setattr(reb, "PROJECT_ROOT", tmp_path)
        write_bundle(tmp_path, BUNDLE)
        loaded = reb.load()
        assert loaded[0]["sgg_code"] == "11680"
        assert (data_dir / "reb_complexes.json").exists()

    def test_csv_wins_over_bundle_when_both_exist(self, tmp_path, monkeypatch, data_dir):
        """직접 받은 원본이 더 최신이므로 동봉본보다 우선한다."""
        monkeypatch.setattr(reb, "PROJECT_ROOT", tmp_path)
        write_bundle(tmp_path, BUNDLE)
        (tmp_path / "한국부동산원_공동주택 단지 식별정보_x.csv").write_text(
            CSV_TEXT, encoding="utf-8-sig")
        loaded = reb.load()
        assert len(loaded) == 3          # CSV는 전국 3건, 동봉본은 1건

    def test_error_when_neither_exists(self, tmp_path, monkeypatch, data_dir):
        monkeypatch.setattr(reb, "PROJECT_ROOT", tmp_path)
        with pytest.raises(MissingDataError, match="data.go.kr"):
            reb.load()

    def test_corrupted_bundle_is_reported(self, tmp_path, monkeypatch, data_dir):
        monkeypatch.setattr(reb, "PROJECT_ROOT", tmp_path)
        path = tmp_path / "bundled" / reb.BUNDLE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not gzip")
        with pytest.raises(MissingDataError, match="동봉"):
            reb.load()

    def test_cache_still_wins_over_everything(self, tmp_path, monkeypatch, data_dir):
        monkeypatch.setattr(reb, "PROJECT_ROOT", tmp_path)
        write_bundle(tmp_path, BUNDLE)
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "reb_complexes.json").write_text(
            json.dumps([{"sgg_code": "CACHED"}]), encoding="utf-8")
        assert reb.load()[0]["sgg_code"] == "CACHED"
