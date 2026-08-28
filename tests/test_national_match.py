"""전국 단지분류 보완 테스트 (서울 밖 주상복합 판별)."""
import pytest

from aptfinder import matching

LISTINGS = [
    {"apt_code": "A41A", "name": "정자아파트", "sido": "경기도",
     "sigungu": "성남시 분당구", "dong": "정자동"},
    {"apt_code": "A41B", "name": "정자타워", "sido": "경기도",
     "sigungu": "성남시 분당구", "dong": "정자동"},
    {"apt_code": "A41C", "name": "다른동단지", "sido": "경기도",
     "sigungu": "성남시 분당구", "dong": "서현동"},
]

BASIS = {
    "A41A": {"apt_code": "A41A", "name": "정자아파트", "complex_type": "아파트",
             "jibun_addr": "경기도 성남시 분당구 정자동 20 정자아파트",
             "households": 500, "dong_count": 5, "approved_on": "2001-03-01",
             "heating": "지역난방", "builder": "A건설", "top_floor": 25},
    "A41B": {"apt_code": "A41B", "name": "정자타워", "complex_type": "주상복합",
             "jibun_addr": "경기도 성남시 분당구 정자동 99 정자타워",
             "households": 300, "dong_count": 1, "approved_on": "2005-01-01",
             "heating": "개별난방", "builder": "B건설", "top_floor": 40},
}


class FakeLookup:
    def __init__(self, table):
        self.table = table
        self.calls = []

    def lookup(self, apt_code):
        self.calls.append(apt_code)
        return self.table.get(apt_code)


@pytest.fixture
def index():
    return matching.build_national_index(LISTINGS)


class TestFindAptCode:
    def test_matches_by_name_within_the_same_dong(self, index):
        candidate = {"gu": "성남시 분당구", "dong": "정자동", "apt": "정자아파트"}
        assert matching.find_apt_code(candidate, index) == "A41A"

    def test_ignores_other_dong(self, index):
        candidate = {"gu": "성남시 분당구", "dong": "정자동", "apt": "다른동단지"}
        assert matching.find_apt_code(candidate, index) == ""

    def test_uses_registry_aliases(self, index):
        """실거래 표기가 달라도 부동산원 별칭으로 찾아낸다."""
        candidate = {"gu": "성남시 분당구", "dong": "정자동", "apt": "정자역타워",
                     "aliases": ["정자타워"]}
        assert matching.find_apt_code(candidate, index) == "A41B"

    def test_unknown_district_returns_blank(self, index):
        assert matching.find_apt_code(
            {"gu": "부산광역시", "dong": "어디동", "apt": "무엇"}, index) == ""

    def test_tolerates_spacing_difference_in_district(self, index):
        candidate = {"gu": "성남시분당구", "dong": "정자동", "apt": "정자아파트"}
        assert matching.find_apt_code(candidate, index) == "A41A"


class TestAttachNationalInfo:
    def test_fills_in_mixed_use_classification(self, index):
        candidate = {"gu": "성남시 분당구", "dong": "정자동", "jibun": "99",
                     "apt": "정자타워", "complex_type": ""}
        result = matching.attach_national_info(candidate, index, FakeLookup(BASIS))
        assert result["complex_type"] == "주상복합"
        assert result["type_checked"] is True

    def test_skips_candidates_already_classified(self, index):
        lookup = FakeLookup(BASIS)
        candidate = {"gu": "성남시 분당구", "dong": "정자동", "apt": "정자타워",
                     "complex_type": "아파트"}
        result = matching.attach_national_info(candidate, index, lookup)
        assert result["complex_type"] == "아파트"
        assert lookup.calls == []

    def test_rejects_when_jibun_disagrees(self, index):
        """이름은 비슷해도 지번이 다르면 다른 단지다."""
        candidate = {"gu": "성남시 분당구", "dong": "정자동", "jibun": "77",
                     "apt": "정자타워", "complex_type": ""}
        result = matching.attach_national_info(candidate, index, FakeLookup(BASIS))
        assert result["complex_type"] == ""
        assert result["type_checked"] is True

    def test_keeps_existing_household_count(self, index):
        candidate = {"gu": "성남시 분당구", "dong": "정자동", "jibun": "20",
                     "apt": "정자아파트", "complex_type": "", "households": 512}
        result = matching.attach_national_info(candidate, index, FakeLookup(BASIS))
        assert result["households"] == 512      # 부동산원 값 우선

    def test_fills_household_count_when_missing(self, index):
        candidate = {"gu": "성남시 분당구", "dong": "정자동", "jibun": "20",
                     "apt": "정자아파트", "complex_type": "", "households": None}
        result = matching.attach_national_info(candidate, index, FakeLookup(BASIS))
        assert result["households"] == 500

    def test_no_match_still_marks_lookup_attempted(self, index):
        candidate = {"gu": "성남시 분당구", "dong": "정자동", "apt": "없는단지",
                     "complex_type": ""}
        result = matching.attach_national_info(candidate, index, FakeLookup(BASIS))
        assert result["type_checked"] is True
        assert result["complex_type"] == ""


class TestDistrictNormalization:
    def test_matches_across_district_spellings(self):
        """목록 API는 '성남분당구', 설정은 '성남시 분당구'로 쓴다."""
        assert (matching.normalize_district("성남시 분당구")
                == matching.normalize_district("성남분당구")
                == matching.normalize_district("성남시분당구"))

    def test_plain_city_names_normalize(self):
        assert matching.normalize_district("과천시") == matching.normalize_district("과천")

    def test_seoul_gu_normalizes(self):
        assert matching.normalize_district("강남구") == "강남"

    def test_blank_is_safe(self):
        assert matching.normalize_district(None) == ""

    def test_index_lookup_works_across_spellings(self):
        index = matching.build_national_index(
            [{"apt_code": "A1", "name": "정자아파트", "sido": "경기도",
              "sigungu": "성남분당구", "dong": "정자동"}])
        assert matching.find_apt_code(
            {"gu": "성남시 분당구", "dong": "정자동", "apt": "정자아파트"}, index) == "A1"
