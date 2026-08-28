"""외부 응답 파싱 테스트 - 실제 API 응답 구조를 그대로 축약해 사용."""
from datetime import date

import pytest

from aptfinder.errors import ApiError
from aptfinder.sources import rtms, schools, stations

TRADE_XML = """<?xml version="1.0" encoding="utf-8"?>
<response><header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>
<body><items>
<item><aptNm>까치마을</aptNm><buildYear>1993</buildYear><cdealType> </cdealType>
<dealAmount>145,000</dealAmount><dealMonth>6</dealMonth><dealYear>2026</dealYear>
<excluUseAr>34.44</excluUseAr><floor>6</floor><jibun>746</jibun>
<sggCd>11680</sggCd><umdNm>수서동</umdNm></item>
<item><aptNm>해제단지</aptNm><buildYear>2001</buildYear><cdealType>O</cdealType>
<dealAmount>999,000</dealAmount><dealMonth>6</dealMonth>
<dealYear>2026</dealYear>
<excluUseAr>84.90</excluUseAr><floor>3</floor><jibun>100</jibun>
<sggCd>11680</sggCd><umdNm>수서동</umdNm></item>
<item><aptNm>가격없음</aptNm><dealAmount>  </dealAmount><dealMonth>6</dealMonth>
<dealYear>2026</dealYear><excluUseAr>59.9</excluUseAr>
<umdNm>수서동</umdNm></item>
</items><numOfRows>1000</numOfRows><pageNo>1</pageNo>
<totalCount>223</totalCount></body></response>"""


class TestRecentMonths:
    def test_crosses_year_boundary(self):
        assert rtms.recent_months(3, date(2026, 2, 15)) == ["202602", "202601", "202512"]

    def test_includes_current_month_first(self):
        assert rtms.recent_months(1, date(2026, 8, 28)) == ["202608"]


class TestParseTrades:
    def test_parses_normal_row(self):
        rows = rtms.parse_trades(TRADE_XML, "강남구")
        assert len(rows) == 1
        row = rows[0]
        assert row["apt"] == "까치마을"
        assert row["price_manwon"] == 145000
        assert row["area_m2"] == pytest.approx(34.44)
        assert row["deal_ym"] == "202606"
        assert row["dong"] == "수서동"
        assert row["gu"] == "강남구"

    def test_excludes_cancelled_deals(self):
        assert all(r["apt"] != "해제단지" for r in rtms.parse_trades(TRADE_XML, "강남구"))

    def test_skips_rows_without_price(self):
        assert all(r["apt"] != "가격없음" for r in rtms.parse_trades(TRADE_XML, "강남구"))

    def test_raises_on_api_error_code(self):
        bad = ("<response><header><resultCode>30</resultCode>"
               "<resultMsg>SERVICE KEY IS NOT REGISTERED ERROR</resultMsg></header></response>")
        with pytest.raises(ApiError, match="30"):
            rtms.parse_trades(bad, "강남구")

    def test_raises_on_malformed_xml(self):
        with pytest.raises(ApiError, match="파싱"):
            rtms.parse_trades("<not xml", "강남구")

    def test_total_count(self):
        assert rtms.total_count(TRADE_XML) == 223
        assert rtms.total_count("<a></a>") is None


class TestStations:
    def test_parses_live_field_names(self):
        rows = [{"BLDN_ID": "0150", "BLDN_NM": "서울역", "ROUTE": "1호선",
                 "LAT": "37.556228", "LOT": "126.972135"}]
        assert stations.parse_rows(rows) == [
            {"name": "서울역", "line": "1호선", "lat": 37.556228, "lon": 126.972135}]

    def test_falls_back_to_alternate_field_names(self):
        rows = [{"STATN_NM": "시청", "LINE_NM": "2호선",
                 "CRDNT_Y": "37.5647", "CRDNT_X": "126.9771"}]
        assert stations.parse_rows(rows)[0]["name"] == "시청"

    def test_drops_rows_without_coordinates(self):
        assert stations.parse_rows([{"BLDN_NM": "좌표없음"}]) == []

    def test_reports_open_data_error(self):
        with pytest.raises(ApiError, match="ERROR-500"):
            stations._extract_rows({"RESULT": {"CODE": "ERROR-500", "MESSAGE": "서버 오류입니다."}})


class TestSchools:
    def test_parses_neis_row(self):
        rows = [{"SCHUL_NM": "가락고등학교", "SCHUL_KND_SC_NM": "고등학교",
                 "ORG_RDNMA": "서울특별시 송파구 송이로 42"}]
        assert schools.parse_rows(rows) == [
            {"name": "가락고등학교", "kind": "고등학교", "addr": "서울특별시 송파구 송이로 42"}]

    def test_skips_rows_without_name(self):
        assert schools.parse_rows([{"SCHUL_KND_SC_NM": "초등학교"}]) == []
