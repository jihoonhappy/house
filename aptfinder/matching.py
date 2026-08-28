"""실거래 단지를 공공 단지 데이터와 이어 붙인다.

두 단계로 나눈다.
  1) 지번 주소 정확매칭 → 한국부동산원 식별정보 (세대수·동수·사용승인일·단지명 별칭)
  2) 별칭 + 좌표 근접매칭 → 서울시 공동주택 정보 (주상복합 여부·정확 좌표·주차대수)

2단계에 좌표만 쓰면 91m 떨어진 다른 단지에 붙어 멀쩡한 아파트를 주상복합으로
오분류하는 사고가 난다. 그래서 이름 유사도를 통과한 후보만 거리로 고른다.
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .geo import haversine_m

# 한글 음차 ↔ 영문 표기 (에스케이북한산시티 ↔ SK북한산시티)
TRANSLITERATIONS = {
    "에스케이": "SK", "엘지": "LG", "지에스": "GS", "케이씨씨": "KCC",
    "에스에이치": "SH", "디에이치": "DH", "아이파크": "IPARK",
    "에이치": "H", "케이티": "KT", "씨제이": "CJ", "엘에이치": "LH",
}
NAME_SUFFIXES = re.compile(r"(아파트|APT|단지)$")
NON_NAME = re.compile(r"[^0-9A-Z가-힣]")
# 시군구 표기가 데이터마다 다르다: "성남시 분당구" / "성남분당구" / "성남시분당구"
DISTRICT_NOISE = re.compile(r"[\s시군구]")
PARENTHETICAL = re.compile(r"\(.*?\)")

DEFAULT_MAX_DISTANCE_M = 400
DEFAULT_MIN_SIMILARITY = 0.55
DISTANCE_PENALTY = 0.3  # 이름 점수 대비 거리의 영향력


def normalize_name(name: str | None) -> str:
    """단지명을 비교 가능한 형태로 정규화한다."""
    text = (name or "").upper()
    for korean, roman in TRANSLITERATIONS.items():
        text = text.replace(korean.upper(), roman)
    text = PARENTHETICAL.sub("", text)
    text = NAME_SUFFIXES.sub("", text.strip())
    return NON_NAME.sub("", text)


CONTAINMENT_BASE = 0.6   # 포함관계만으로 주는 기본 점수


def similarity(left: str, right: str) -> float:
    """0~1 이름 유사도.

    완전히 같으면 1.0. 한쪽이 다른 쪽을 포함하면 길이 비율만큼만 인정한다.
    ('정자'가 '정자타워'에 들어간다고 같은 단지로 보면 안 되기 때문)
    """
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        ratio = min(len(a), len(b)) / max(len(a), len(b))
        return CONTAINMENT_BASE + (1 - CONTAINMENT_BASE) * ratio
    return difflib.SequenceMatcher(None, a, b).ratio()


def build_address_index(complexes: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], dict]:
    """(시군구코드, 동, 지번) → 단지. 본번 키도 함께 넣어 부번 차이를 흡수한다.

    지역 이름 표기가 데이터마다 달라(수원장안구 / 수원시 장안구) 코드로 맞춘다.
    """
    index: dict[tuple[str, str, str], dict] = {}
    for complex_ in complexes:
        code, dong = complex_["sgg_code"], complex_["dong"]
        index.setdefault((code, dong, complex_["bonbun"]), dict(complex_))
        index[(code, dong, complex_["jibun"])] = dict(complex_)
    return index


def _jibun_of(candidate: Mapping[str, Any]) -> str:
    """후보의 지번. 없으면 주소 마지막 토큰에서 찾아본다."""
    jibun = (candidate.get("jibun") or "").strip()
    if jibun:
        return jibun
    parts = (candidate.get("addr") or "").split()
    if len(parts) < 4:
        return ""
    return parts[-1] if parts[-1][:1].isdigit() else ""


def match_by_address(
    candidate: Mapping[str, Any], address_index: Mapping[tuple[str, str, str], dict]
) -> dict[str, Any] | None:
    """시군구코드+동+지번 정확매칭 후 본번 매칭으로 보완한다."""
    code, jibun = candidate.get("sgg_code"), _jibun_of(candidate)
    if not code or not jibun:
        return None
    dong = candidate["dong"]
    key = (code, dong, jibun)
    if key in address_index:
        return address_index[key]
    return address_index.get((code, dong, jibun.split("-")[0]))


def match_complex_info(
    candidate: Mapping[str, Any],
    aliases: Sequence[str],
    complexes: Iterable[Mapping[str, Any]],
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> dict[str, Any] | None:
    """이름 유사도를 통과한 것 중 가장 가까운 단지를 고른다."""
    lat, lon = candidate.get("lat"), candidate.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    names = [name for name in [*aliases, candidate.get("apt")] if name]

    best, best_score = None, 0.0
    for complex_ in complexes:
        other_lat, other_lon = complex_.get("lat"), complex_.get("lon")
        if not isinstance(other_lat, (int, float)) or not isinstance(other_lon, (int, float)):
            continue
        distance = haversine_m(lat, lon, other_lat, other_lon)
        if distance > max_distance_m:
            continue
        name_score = max((similarity(name, complex_["name"]) for name in names), default=0.0)
        if name_score < min_similarity:
            continue
        score = name_score - (distance / max_distance_m) * DISTANCE_PENALTY
        if score > best_score:
            best, best_score = complex_, score
    return dict(best) if best else None


def attach_registry(
    candidate: Mapping[str, Any], address_index: Mapping[tuple[str, str, str], dict]
) -> dict[str, Any]:
    """지번 주소로 세대수·동수·사용승인일·단지명 별칭을 붙인다 (좌표 불필요).

    지오코딩 전에 부를 수 있어, 세대수 조건으로 후보를 먼저 줄이면 호출을 크게 아낀다.
    """
    registry = match_by_address(candidate, address_index) or {}
    return {
        **candidate,
        "complex_id": registry.get("complex_id", ""),
        "households": registry.get("households"),
        "dong_count": registry.get("dong_count"),
        "approved_on": registry.get("approved_on", ""),
        "aliases": registry.get("aliases", []),
        "matched": bool(registry),
    }


def attach_complex_info(
    candidate: Mapping[str, Any],
    complexes: Iterable[Mapping[str, Any]],
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> dict[str, Any]:
    """단지분류(주상복합 여부)·주차대수와 공식 좌표를 붙인다. 좌표가 필요하다."""
    info = match_complex_info(
        candidate, candidate.get("aliases") or [], complexes,
        max_distance_m, min_similarity) or {}
    enriched = {
        **candidate,
        "complex_type": info.get("complex_type", ""),
        "parking": info.get("parking"),
        "heating": info.get("heating", ""),
        "builder": info.get("builder", ""),
        # 분류 조회를 이미 시도했다는 표시. 지오코딩 전 1차 필터와 구분하기 위해 필요하다.
        "type_checked": True,
    }
    if info.get("lat") and info.get("lon"):
        enriched["lat"], enriched["lon"] = info["lat"], info["lon"]
    return enriched


def enrich(
    candidate: Mapping[str, Any],
    address_index: Mapping[tuple[str, str, str], dict],
    complexes: Iterable[Mapping[str, Any]],
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> dict[str, Any]:
    """두 단계를 한 번에 적용한다 (좌표가 이미 있는 후보용)."""
    return attach_complex_info(
        attach_registry(candidate, address_index), complexes, max_distance_m, min_similarity)


def normalize_district(name: str | None) -> str:
    """시군구명을 비교 가능한 형태로. '성남시 분당구'와 '성남분당구'를 같게 만든다."""
    return DISTRICT_NOISE.sub("", name or "")


def build_national_index(
    listings: Iterable[Mapping[str, Any]]
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """(정규화 시군구, 동) → 단지 목록. 전국 단지코드를 이름으로 찾기 위한 버킷."""
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for listing in listings:
        key = (normalize_district(listing.get("sigungu")), listing.get("dong", ""))
        index.setdefault(key, []).append(dict(listing))
    return index


def find_apt_code(
    candidate: Mapping[str, Any],
    national_index: Mapping[tuple[str, str], list[dict[str, Any]]],
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> str:
    """같은 시군구·동 안에서 이름이 가장 비슷한 단지의 단지코드."""
    bucket = national_index.get(
        (normalize_district(candidate.get("gu")), candidate.get("dong", "")), [])
    names = [n for n in [*(candidate.get("aliases") or []), candidate.get("apt")] if n]
    best, best_score = "", min_similarity
    for listing in bucket:
        score = max((similarity(name, listing["name"]) for name in names), default=0.0)
        if score > best_score:
            best, best_score = listing["apt_code"], score
    return best


def attach_national_info(
    candidate: Mapping[str, Any],
    national_index: Mapping[tuple[str, str], list[dict[str, Any]]],
    lookup: Any,
) -> dict[str, Any]:
    """서울 데이터로 분류하지 못한 단지를 전국 API로 보완한다.

    이미 분류를 아는 단지는 건드리지 않는다. 조회 결과의 지번 주소가 후보와
    다르면 잘못 짚은 것으로 보고 버린다 (엉뚱한 단지를 주상복합으로 만들지 않기 위함).
    """
    if candidate.get("complex_type"):
        return dict(candidate)
    apt_code = find_apt_code(candidate, national_index)
    info = lookup.lookup(apt_code) if apt_code else None
    if not info or not _jibun_agrees(candidate, info):
        return {**candidate, "type_checked": True}
    return {
        **candidate,
        "complex_type": info.get("complex_type", ""),
        "households": candidate.get("households") or info.get("households"),
        "dong_count": candidate.get("dong_count") or info.get("dong_count"),
        "approved_on": candidate.get("approved_on") or info.get("approved_on", ""),
        "heating": info.get("heating", ""),
        "builder": info.get("builder", ""),
        "top_floor": info.get("top_floor"),
        "type_checked": True,
    }


def _jibun_agrees(candidate: Mapping[str, Any], info: Mapping[str, Any]) -> bool:
    """조회된 단지의 지번 주소가 후보의 동·지번과 맞는지 확인한다."""
    address = info.get("jibun_addr") or ""
    if not address:
        return True                      # 주소가 없으면 이름 매칭 결과를 믿는다
    dong = candidate.get("dong") or ""
    if dong and dong not in address:
        return False
    jibun = _jibun_of(candidate)
    if not jibun:
        return True
    bonbun = jibun.split("-")[0]
    return re.search(rf"(?<!\d){re.escape(bonbun)}(?!\d)", address) is not None


def classified_regions(complexes: Iterable[Mapping[str, Any]]) -> set[str]:
    """단지분류 데이터가 존재하는 시도 집합.

    분류 자료가 없는 지역까지 '미확인이면 탈락' 규칙을 적용하면 그 지역 후보가
    전멸한다. 커버리지를 데이터에서 직접 읽어 규칙 적용 범위를 정한다.
    """
    return {c["sido"] for c in complexes if c.get("sido") and c.get("complex_type")}


def passes_complex_filter(
    candidate: Mapping[str, Any],
    criteria: Mapping[str, Any],
    classified: set[str] | None = None,
) -> bool:
    """주상복합 제외·세대수 하한·매칭 필수 여부를 확인한다.

    classified를 주면, 분류 자료가 있는 시도에서만 '분류 미확인 탈락'을 적용한다.
    """
    if criteria.get("require_complex_match") and not candidate.get("matched"):
        return False

    complex_type = candidate.get("complex_type") or ""
    excluded_types = criteria.get("exclude_complex_types") or []
    for excluded in excluded_types:
        if excluded and excluded in complex_type:
            return False

    # 분류를 조회했는데도 알 수 없으면 주상복합인지 확인할 방법이 없다.
    # 제외 조건이 걸려 있다면 확인되지 않은 단지도 버린다.
    # 단, 애초에 분류 자료가 없는 지역에는 적용하지 않는다.
    in_covered_region = classified is None or candidate.get("sido") in classified
    if (criteria.get("require_type_known") and excluded_types and in_covered_region
            and candidate.get("type_checked") and not complex_type):
        return False

    minimum = criteria.get("min_households") or 0
    if minimum:
        households = candidate.get("households")
        if households is None or households < minimum:
            return False
    return True
