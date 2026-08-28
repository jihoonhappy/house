"""단지 매칭 테스트 - 주소 정확매칭과 이름+좌표 결합매칭."""
import pytest

from aptfinder import matching

REB = [
    {"complex_id": "1", "sgg_code": "11305", "gu": "강북구", "dong": "미아동",
     "jibun": "1353", "bonbun": "1353",
     "aliases": ["에스케이북한산시티", "에스케이북한산시티아파트"],
     "households": 3830, "dong_count": 47, "approved_on": "2004-05-20"},
    {"complex_id": "2", "sgg_code": "11350", "gu": "노원구", "dong": "상계동",
     "jibun": "771-1", "bonbun": "771",
     "aliases": ["상계주공11단지아파트", "상계주공11(고층)"],
     "households": 1944, "dong_count": 16, "approved_on": "1988-11-30"},
]

APT_INFO = [
    {"name": "SK북한산시티아파트", "complex_type": "아파트", "gu": "강북구", "dong": "미아동",
     "households": 3830, "parking": 2000, "heating": "지역난방", "builder": "SK건설",
     "lat": 37.6180, "lon": 127.0130},
    {"name": "회기역하트리움", "complex_type": "주상복합", "gu": "동대문구", "dong": "휘경동",
     "households": 582, "parking": 300, "heating": "개별난방", "builder": "H",
     "lat": 37.5896, "lon": 127.0576},
    {"name": "좌표없는단지", "complex_type": "아파트", "gu": "강북구", "dong": "미아동",
     "households": 100, "parking": None, "heating": "", "builder": "",
     "lat": None, "lon": None},
]


class TestNormalizeName:
    def test_strips_suffixes_and_spaces(self):
        assert matching.normalize_name("동아그린 아파트") == matching.normalize_name("동아그린")

    def test_maps_korean_transliteration_to_roman(self):
        assert matching.normalize_name("에스케이북한산시티") == matching.normalize_name("SK북한산시티")

    def test_drops_parenthetical_qualifier(self):
        assert matching.normalize_name("상계주공11(고층)") == matching.normalize_name("상계주공11")

    def test_empty_input_is_safe(self):
        assert matching.normalize_name("") == ""
        assert matching.normalize_name(None) == ""


class TestAddressMatch:
    def test_exact_jibun_match(self):
        index = matching.build_address_index(REB)
        found = matching.match_by_address(
            {"sgg_code": "11350", "dong": "상계동", "jibun": "771-1"}, index)
        assert found["complex_id"] == "2"

    def test_falls_back_to_bonbun(self):
        index = matching.build_address_index(REB)
        found = matching.match_by_address(
            {"sgg_code": "11350", "dong": "상계동", "jibun": "771-9"}, index)
        assert found["complex_id"] == "2"

    def test_returns_none_for_unknown_address(self):
        index = matching.build_address_index(REB)
        assert matching.match_by_address(
            {"sgg_code": "11680", "dong": "수서동", "jibun": "999"}, index) is None

    def test_missing_jibun_is_handled(self):
        index = matching.build_address_index(REB)
        assert matching.match_by_address(
            {"sgg_code": "11305", "dong": "미아동", "addr": "서울 강북구 미아동"}, index) is None

    def test_missing_district_code_is_handled(self):
        index = matching.build_address_index(REB)
        assert matching.match_by_address({"dong": "미아동", "jibun": "1353"}, index) is None

    def test_falls_back_to_parsing_address_when_jibun_absent(self):
        index = matching.build_address_index(REB)
        found = matching.match_by_address(
            {"sgg_code": "11305", "dong": "미아동", "addr": "서울 강북구 미아동 1353"}, index)
        assert found["complex_id"] == "1"


class TestComplexInfoMatch:
    def test_matches_across_transliteration_using_aliases(self):
        candidate = {"apt": "에스케이북한산시티", "lat": 37.6181, "lon": 127.0131}
        found = matching.match_complex_info(
            candidate, REB[0]["aliases"], APT_INFO, max_distance_m=400, min_similarity=0.55)
        assert found["name"] == "SK북한산시티아파트"

    def test_rejects_nearby_but_differently_named_complex(self):
        """91m 떨어진 다른 단지에 잘못 붙어 주상복합으로 오분류되면 안 된다."""
        candidate = {"apt": "휘경제이스카이아파트", "lat": 37.5897, "lon": 127.0577}
        found = matching.match_complex_info(
            candidate, ["휘경제이스카이아파트"], APT_INFO,
            max_distance_m=400, min_similarity=0.55)
        assert found is None

    def test_rejects_match_beyond_distance_limit(self):
        candidate = {"apt": "에스케이북한산시티", "lat": 37.7000, "lon": 127.0130}
        assert matching.match_complex_info(
            candidate, REB[0]["aliases"], APT_INFO, 400, 0.55) is None

    def test_skips_entries_without_coordinates(self):
        candidate = {"apt": "좌표없는단지", "lat": 37.6180, "lon": 127.0130}
        assert matching.match_complex_info(candidate, ["좌표없는단지"], APT_INFO, 400, 0.55) is None

    def test_candidate_without_coordinates_returns_none(self):
        assert matching.match_complex_info(
            {"apt": "무엇", "lat": None, "lon": None}, ["무엇"], APT_INFO, 400, 0.55) is None


class TestEnrich:
    def setup_method(self):
        self.index = matching.build_address_index(REB)

    def test_adds_households_and_complex_type(self):
        candidate = {"sgg_code": "11305", "gu": "강북구", "dong": "미아동", "jibun": "1353",
                     "apt": "에스케이북한산시티",
                     "addr": "서울 강북구 미아동 1353", "lat": 37.6181, "lon": 127.0131}
        result = matching.enrich(candidate, self.index, APT_INFO)
        assert result["households"] == 3830
        assert result["dong_count"] == 47
        assert result["complex_type"] == "아파트"
        assert result["parking"] == 2000
        assert result["matched"] is True

    def test_replaces_coordinates_with_official_ones(self):
        candidate = {"sgg_code": "11305", "gu": "강북구", "dong": "미아동", "jibun": "1353",
                     "apt": "에스케이북한산시티",
                     "addr": "서울 강북구 미아동 1353", "lat": 37.6181, "lon": 127.0131}
        result = matching.enrich(candidate, self.index, APT_INFO)
        assert (result["lat"], result["lon"]) == (37.6180, 127.0130)

    def test_unmatched_address_marks_unknown(self):
        candidate = {"sgg_code": "11680", "gu": "강남구", "dong": "수서동", "jibun": "999",
                     "apt": "없는단지",
                     "addr": "서울 강남구 수서동 999", "lat": 37.48, "lon": 127.09}
        result = matching.enrich(candidate, self.index, APT_INFO)
        assert result["households"] is None
        assert result["complex_type"] == ""
        assert result["matched"] is False

    def test_keeps_original_coordinates_when_complex_info_missing(self):
        candidate = {"sgg_code": "11350", "gu": "노원구", "dong": "상계동", "jibun": "771-1",
                     "apt": "상계주공11(고층)",
                     "addr": "서울 노원구 상계동 771-1", "lat": 37.66, "lon": 127.06}
        result = matching.enrich(candidate, self.index, APT_INFO)
        assert result["households"] == 1944       # REB는 매칭됨
        assert result["complex_type"] == ""       # OpenAptInfo는 미매칭
        assert (result["lat"], result["lon"]) == (37.66, 127.06)


class TestComplexTypeFilter:
    def test_excludes_configured_types(self):
        criteria = {"exclude_complex_types": ["주상복합"], "require_complex_match": True,
                    "min_households": 300}
        assert matching.passes_complex_filter(
            {"complex_type": "주상복합", "households": 500, "matched": True}, criteria) is False

    def test_accepts_plain_apartment(self):
        criteria = {"exclude_complex_types": ["주상복합"], "require_complex_match": True,
                    "min_households": 300}
        assert matching.passes_complex_filter(
            {"complex_type": "아파트", "households": 500, "matched": True}, criteria) is True

    def test_household_minimum_is_enforced(self):
        criteria = {"exclude_complex_types": ["주상복합"], "require_complex_match": True,
                    "min_households": 300}
        assert matching.passes_complex_filter(
            {"complex_type": "아파트", "households": 120, "matched": True}, criteria) is False

    def test_unmatched_is_dropped_when_match_required(self):
        criteria = {"exclude_complex_types": ["주상복합"], "require_complex_match": True,
                    "min_households": 0}
        assert matching.passes_complex_filter(
            {"complex_type": "", "households": None, "matched": False}, criteria) is False

    def test_unmatched_is_kept_when_match_not_required(self):
        criteria = {"exclude_complex_types": ["주상복합"], "require_complex_match": False,
                    "min_households": 0}
        assert matching.passes_complex_filter(
            {"complex_type": "", "households": None, "matched": False}, criteria) is True

    def test_partial_type_names_are_matched(self):
        """'도시형 생활주택(주상복합)'도 주상복합으로 걸러야 한다."""
        criteria = {"exclude_complex_types": ["주상복합"], "require_complex_match": True,
                    "min_households": 0}
        assert matching.passes_complex_filter(
            {"complex_type": "도시형 생활주택(주상복합)", "households": 500, "matched": True},
            criteria) is False


class TestUnknownComplexType:
    CRITERIA = {"exclude_complex_types": ["주상복합"], "require_complex_match": True,
                "require_type_known": True, "min_households": 0}

    def test_drops_candidate_whose_type_could_not_be_determined(self):
        candidate = {"complex_type": "", "households": 500, "matched": True,
                     "type_checked": True}
        assert matching.passes_complex_filter(candidate, self.CRITERIA) is False

    def test_keeps_candidate_before_type_lookup_has_run(self):
        """지오코딩 전 1차 필터에서는 분류가 비어 있는 게 정상이다."""
        candidate = {"complex_type": "", "households": 500, "matched": True}
        assert matching.passes_complex_filter(candidate, self.CRITERIA) is True

    def test_keeps_unknown_type_when_rule_is_off(self):
        criteria = {**self.CRITERIA, "require_type_known": False}
        candidate = {"complex_type": "", "households": 500, "matched": True,
                     "type_checked": True}
        assert matching.passes_complex_filter(candidate, criteria) is True

    def test_attach_complex_info_marks_the_lookup(self):
        result = matching.attach_complex_info(
            {"apt": "없는단지", "lat": 37.5, "lon": 127.0, "aliases": []}, [])
        assert result["type_checked"] is True
        assert result["complex_type"] == ""


class TestRegionalClassificationCoverage:
    CRITERIA = {"exclude_complex_types": ["주상복합"], "require_complex_match": True,
                "require_type_known": True, "min_households": 0}
    COMPLEXES = [{"sido": "서울", "complex_type": "아파트"},
                 {"sido": "서울", "complex_type": "주상복합"},
                 {"sido": "경기", "complex_type": ""}]

    def test_reports_regions_that_have_classification_data(self):
        assert matching.classified_regions(self.COMPLEXES) == {"서울"}

    def test_unknown_type_is_dropped_inside_covered_region(self):
        candidate = {"sido": "서울", "complex_type": "", "households": 500,
                     "matched": True, "type_checked": True}
        assert matching.passes_complex_filter(
            candidate, self.CRITERIA, {"서울"}) is False

    def test_unknown_type_is_kept_outside_covered_region(self):
        """경기도는 분류 자료가 없으므로 미확인을 이유로 버리면 안 된다."""
        candidate = {"sido": "경기", "complex_type": "", "households": 500,
                     "matched": True, "type_checked": True}
        assert matching.passes_complex_filter(
            candidate, self.CRITERIA, {"서울"}) is True

    def test_known_excluded_type_is_dropped_everywhere(self):
        candidate = {"sido": "경기", "complex_type": "주상복합", "households": 500,
                     "matched": True, "type_checked": True}
        assert matching.passes_complex_filter(
            candidate, self.CRITERIA, {"서울"}) is False


class TestSimilarityScale:
    def test_identical_names_score_one(self):
        assert matching.similarity("정자아파트", "정자아파트") == 1.0

    def test_suffix_only_difference_still_scores_one(self):
        assert matching.similarity("동아그린", "동아그린아파트") == 1.0

    def test_containment_is_discounted_by_length(self):
        """'정자'가 '정자타워'에 들어간다고 같은 단지로 보면 안 된다."""
        partial = matching.similarity("정자", "정자타워")
        assert 0.5 < partial < 1.0

    def test_longer_shared_prefix_scores_higher(self):
        assert (matching.similarity("정자한신", "정자한신아파트2단지")
                > matching.similarity("정자", "정자한신아파트2단지"))
