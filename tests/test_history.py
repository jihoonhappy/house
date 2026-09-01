"""가격 이력 집계 테스트."""
import json

import pytest

from aptfinder import history

BANDS = [{"label": "59㎡형", "min": 55, "max": 66},
         {"label": "84㎡형", "min": 80, "max": 96}]


def trade(apt="까치마을", area=84.9, price=60000, ym="202301", dong="수서동"):
    return {"gu": "강남구", "sgg_code": "11680", "dong": dong, "jibun": "746", "apt": apt,
            "price_manwon": price, "area_m2": area, "floor": "6",
            "build_year": "1993", "deal_ym": ym}


class TestHalfYear:
    def test_first_half(self):
        assert history.half_year("202301") == "2023H1"
        assert history.half_year("202306") == "2023H1"

    def test_second_half(self):
        assert history.half_year("202307") == "2023H2"
        assert history.half_year("202312") == "2023H2"

    def test_malformed_is_none(self):
        assert history.half_year("20") is None
        assert history.half_year("") is None


class TestAccumulate:
    def test_groups_by_complex_band_and_half(self):
        index = {}
        history.accumulate(index, [trade(ym="202301", price=60000),
                                   trade(ym="202305", price=62000),
                                   trade(ym="202308", price=70000)], BANDS)
        key = "11680|수서동|까치마을|84㎡형"
        assert sorted(index[key]) == ["2023H1", "2023H2"]
        assert index[key]["2023H1"] == [60000, 62000]

    def test_separates_area_bands(self):
        index = {}
        history.accumulate(index, [trade(area=59.9, price=40000),
                                   trade(area=84.9, price=60000)], BANDS)
        assert len(index) == 2

    def test_skips_trades_outside_any_band(self):
        index = {}
        history.accumulate(index, [trade(area=30.0)], BANDS)
        assert index == {}


class TestSummarise:
    RAW = {"11680|수서동|까치마을|84㎡형": {
        "2023H1": [60000, 62000], "2023H2": [70000],
        "2024H1": [66000], "2024H2": [58000, 60000]}}

    def test_produces_sorted_series(self):
        out = history.summarise(self.RAW)["11680|수서동|까치마을|84㎡형"]
        assert [p["half"] for p in out["series"]] == ["2023H1", "2023H2", "2024H1", "2024H2"]
        assert [p["median"] for p in out["series"]] == [61000, 70000, 66000, 59000]
        assert [p["count"] for p in out["series"]] == [2, 1, 1, 2]

    def test_reports_average_of_all_trades(self):
        out = history.summarise(self.RAW)["11680|수서동|까치마을|84㎡형"]
        assert out["avg_manwon"] == 62667      # (60+62+70+66+58+60)/6 만원 반올림

    def test_reports_peak_and_when(self):
        out = history.summarise(self.RAW)["11680|수서동|까치마을|84㎡형"]
        assert out["peak_manwon"] == 70000
        assert out["peak_half"] == "2023H2"

    def test_reports_trough(self):
        out = history.summarise(self.RAW)["11680|수서동|까치마을|84㎡형"]
        assert out["low_manwon"] == 59000

    def test_counts_total_trades(self):
        assert history.summarise(self.RAW)["11680|수서동|까치마을|84㎡형"]["total_count"] == 6


class TestAttach:
    SUMMARY = {"11680|수서동|까치마을|84㎡형": {
        "series": [{"half": "2023H1", "median": 60000, "count": 2}],
        "avg_manwon": 62667, "peak_manwon": 70000, "peak_half": "2023H2",
        "low_manwon": 59000, "total_count": 6}}

    def test_attaches_matching_history(self):
        candidate = {"sgg_code": "11680", "dong": "수서동", "apt": "까치마을",
                     "area_band": "84㎡형", "price_manwon": 63000}
        out = history.attach(candidate, self.SUMMARY)
        assert out["price_avg_manwon"] == 62667
        assert out["price_peak_manwon"] == 70000
        assert out["price_history"] == self.SUMMARY["11680|수서동|까치마을|84㎡형"]["series"]

    def test_computes_gap_to_peak(self):
        candidate = {"sgg_code": "11680", "dong": "수서동", "apt": "까치마을",
                     "area_band": "84㎡형", "price_manwon": 63000}
        out = history.attach(candidate, self.SUMMARY)
        assert out["vs_peak_pct"] == -10.0       # 63000 / 70000 - 1

    def test_computes_gap_to_average(self):
        candidate = {"sgg_code": "11680", "dong": "수서동", "apt": "까치마을",
                     "area_band": "84㎡형", "price_manwon": 63000}
        assert history.attach(candidate, self.SUMMARY)["vs_avg_pct"] == 0.5

    def test_missing_history_leaves_blanks(self):
        out = history.attach({"sgg_code": "99999", "dong": "x", "apt": "y",
                              "area_band": "84㎡형", "price_manwon": 50000}, self.SUMMARY)
        assert out["price_avg_manwon"] is None
        assert out["price_history"] == []
        assert out["vs_peak_pct"] is None
