"""전국 단지 목록·기본정보 API 테스트 (네트워크 없음)."""
import json

import pytest

from aptfinder import config
from aptfinder.errors import ApiError
from aptfinder.sources import aptbasis, aptlist

ITEM = {
    "kaptCode": "A15679103", "kaptName": "우리유앤미", "codeAptNm": "아파트",
    "kaptAddr": "서울특별시 동작구 흑석동 329 우리유앤미",
    "doroJuso": "서울특별시 동작구 서달로 83", "bjdCode": "1159010500",
    "kaptdaCnt": "206.0", "kaptDongCnt": "2", "kaptTopFloor": "17",
    "codeHeatNm": "개별난방", "kaptBcompany": "우리건설", "kaptUsedate": "20031226",
}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    target = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", target)
    return target


class TestParseItem:
    def test_maps_all_fields(self):
        row = aptbasis.parse_item(ITEM)
        assert row["complex_type"] == "아파트"
        assert row["households"] == 206
        assert row["dong_count"] == 2
        assert row["top_floor"] == 17
        assert row["approved_on"] == "2003-12-26"
        assert row["jibun_addr"].startswith("서울특별시 동작구 흑석동 329")

    def test_identifies_mixed_use(self):
        assert aptbasis.parse_item({**ITEM, "codeAptNm": "주상복합"})["complex_type"] == "주상복합"

    def test_empty_response_is_none(self):
        assert aptbasis.parse_item(None) is None
        assert aptbasis.parse_item({"kaptCode": None}) is None

    def test_bad_use_date_is_blank(self):
        assert aptbasis.parse_item({**ITEM, "kaptUsedate": "  "})["approved_on"] == ""


class TestLookup:
    def _payload(self, item):
        return {"response": {"body": {"item": item}}}

    def test_fetches_and_caches(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(aptbasis, "get_json",
                            lambda url, **kw: calls.append(url) or self._payload(ITEM))
        lookup = aptbasis.AptBasisLookup("key", tmp_path / "c.json")
        assert lookup.lookup("A15679103")["complex_type"] == "아파트"
        assert lookup.lookup("A15679103")["complex_type"] == "아파트"
        assert len(calls) == 1

    def test_blank_code_needs_no_call(self, monkeypatch, tmp_path):
        def explode(*args, **kwargs):
            raise AssertionError("빈 코드로 호출하면 안 된다")

        monkeypatch.setattr(aptbasis, "get_json", explode)
        assert aptbasis.AptBasisLookup("key", tmp_path / "c.json").lookup("") is None

    def test_cache_survives_reload(self, monkeypatch, tmp_path):
        monkeypatch.setattr(aptbasis, "get_json", lambda url, **kw: self._payload(ITEM))
        first = aptbasis.AptBasisLookup("key", tmp_path / "c.json")
        first.lookup("A15679103")
        first.save()

        def explode(*args, **kwargs):
            raise AssertionError("캐시가 있으면 호출하면 안 된다")

        monkeypatch.setattr(aptbasis, "get_json", explode)
        assert aptbasis.AptBasisLookup("key", tmp_path / "c.json").lookup("A15679103")

    def test_corrupted_cache_is_ignored(self, monkeypatch, tmp_path):
        path = tmp_path / "c.json"
        path.write_text("{broken", encoding="utf-8")
        monkeypatch.setattr(aptbasis, "get_json", lambda url, **kw: self._payload(ITEM))
        assert aptbasis.AptBasisLookup("key", path).lookup("A15679103")

    def test_unregistered_key_explains_how_to_apply(self, monkeypatch, tmp_path):
        def unregistered(*args, **kwargs):
            raise ApiError("HTTP 403 SERVICE_KEY_IS_NOT_REGISTERED_ERROR")

        monkeypatch.setattr(aptbasis, "get_json", unregistered)
        with pytest.raises(ApiError, match="15058453"):
            aptbasis.AptBasisLookup("key", tmp_path / "c.json").lookup("A1")


class TestAptList:
    def _payload(self, items, total=None):
        return {"response": {"body": {"items": {"item": items},
                                      "totalCount": total if total is not None else len(items)}}}

    ROW = {"kaptCode": "A41A", "kaptName": "정자아파트", "as1": "경기도",
           "as2": "성남시 분당구", "as3": "정자동"}

    def test_parses_items(self):
        assert aptlist.parse_items([self.ROW])[0] == {
            "apt_code": "A41A", "name": "정자아파트", "sido": "경기도",
            "sigungu": "성남시 분당구", "dong": "정자동"}

    def test_skips_rows_without_code(self):
        assert aptlist.parse_items([{"kaptName": "코드없음"}]) == []

    def test_single_item_response_is_wrapped(self, monkeypatch):
        monkeypatch.setattr(aptlist, "get_json", lambda url, **kw: self._payload(self.ROW, 1))
        assert len(aptlist.fetch_sido("key", "41")) == 1

    def test_empty_response_is_handled(self, monkeypatch):
        monkeypatch.setattr(aptlist, "get_json",
                            lambda url, **kw: {"response": {"body": {"totalCount": 0}}})
        assert aptlist.fetch_sido("key", "41") == []

    def test_sido_codes_are_deduplicated(self):
        assert aptlist.sido_codes(["11680", "11350", "41135", "28185"]) == ["11", "28", "41"]

    def test_collect_writes_cache(self, monkeypatch, data_dir):
        monkeypatch.setattr(aptlist, "get_json", lambda url, **kw: self._payload([self.ROW]))
        rows = aptlist.collect("key", ["41"])
        assert rows[0]["apt_code"] == "A41A"
        assert (data_dir / "apt_list.json").exists()

    def test_collect_uses_cache(self, monkeypatch, data_dir):
        data_dir.mkdir(parents=True)
        (data_dir / "apt_list.json").write_text(
            json.dumps([{"apt_code": "CACHED"}]), encoding="utf-8")

        def explode(*args, **kwargs):
            raise AssertionError("캐시가 있으면 호출하면 안 된다")

        monkeypatch.setattr(aptlist, "get_json", explode)
        assert aptlist.collect("key", ["41"])[0]["apt_code"] == "CACHED"

    def test_unregistered_key_explains_how_to_apply(self, monkeypatch, data_dir):
        def unregistered(*args, **kwargs):
            raise ApiError("HTTP 403 SERVICE_KEY_IS_NOT_REGISTERED_ERROR")

        monkeypatch.setattr(aptlist, "get_json", unregistered)
        with pytest.raises(ApiError, match="15057332"):
            aptlist.collect("key", ["41"])

    def test_zero_results_is_an_error(self, monkeypatch, data_dir):
        monkeypatch.setattr(aptlist, "get_json", lambda url, **kw: self._payload([]))
        with pytest.raises(ApiError, match="0건"):
            aptlist.collect("key", ["41"])
