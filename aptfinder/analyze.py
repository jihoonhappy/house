"""후보 산출 - 면적대 분리, 대표가격, 거리 필터, 점수화. 모두 순수 함수."""
from __future__ import annotations
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from .errors import ConfigError
from .geo import count_within, nearest

MAX_BUILDING_AGE = 40      # 이보다 오래되면 준공년도 점수 0
TRADE_COUNT_FOR_FULL = 20  # 이 이상 거래되면 환금성 점수 만점
UNKNOWN_BUILDING_AGE = 30  # 준공년도를 모를 때 가정하는 연식


def band_for(area_m2: float, bands: Sequence[Mapping[str, Any]]) -> str | None:
    """전용면적이 속한 구간 label. min 이상 max 미만이며 max=0은 상한 없음."""
    for band in bands:
        lower = band["min"]
        upper = band.get("max") or float("inf")
        if lower <= area_m2 < upper:
            return band["label"]
    return None


def passes_area(area_m2: float, criteria: Mapping[str, Any]) -> bool:
    """면적 하한/상한 조건 통과 여부. 상한 0은 제한 없음."""
    if area_m2 < criteria["area_min_m2"]:
        return False
    upper = criteria.get("area_max_m2") or 0
    return not (upper and area_m2 > upper)


def representative_price(
    rows: Sequence[Mapping[str, Any]],
    recent_months: set[str],
    min_trade_count: int,
) -> tuple[int, int, str]:
    """(대표가격, 사용한 거래건수, 산정근거 문자열).

    최근 창(window) 안에 거래가 충분하면 그 중앙값을, 아니면 전체 기간 중앙값을 쓴다.
    """
    recent = [r for r in rows if r["deal_ym"] in recent_months]
    if len(recent) >= min_trade_count:
        used, basis = recent, f"최근 {len(recent)}건"
    else:
        used, basis = rows, f"전체 {len(rows)}건"
    prices = [r["price_manwon"] for r in used]
    return int(statistics.median(prices)), len(used), basis


def group_by_complex_and_band(
    trades: Iterable[Mapping[str, Any]],
    bands: Sequence[Mapping[str, Any]],
    criteria: Mapping[str, Any],
) -> dict[tuple[str, str, str, str], list[Mapping[str, Any]]]:
    """(구, 동, 단지명, 면적대) → 거래목록. 면적 조건 미달 거래는 제외."""
    groups = {}
    for row in trades:
        area = row["area_m2"]
        if not passes_area(area, criteria):
            continue
        label = band_for(area, bands)
        if label is None:
            continue
        key = (row["gu"], row["dong"], row["apt"], label)
        groups.setdefault(key, []).append(row)
    return groups


def build_candidates(
    trades: Iterable[Mapping[str, Any]],
    bands: Sequence[Mapping[str, Any]],
    criteria: Mapping[str, Any],
    recent_months: set[str],
) -> list[dict[str, Any]]:
    """가격·면적·거래건수 조건을 통과한 후보 목록을 만든다."""
    candidates = []
    for (gu, dong, apt, label), rows in group_by_complex_and_band(trades, bands, criteria).items():
        if len(rows) < criteria["min_trade_count"]:
            continue
        price, used_count, basis = representative_price(
            rows, recent_months, criteria["min_trade_count"])
        if not criteria["price_min"] <= price <= criteria["price_max"]:
            continue
        latest = max(rows, key=lambda r: r["deal_ym"])
        jibun = Counter(r["jibun"] for r in rows if r["jibun"]).most_common(1)
        jibun_value = jibun[0][0] if jibun else ""
        sgg_code = rows[0].get("sgg_code", "")
        sido = sido_of(sgg_code)
        candidates.append({
            "gu": gu, "dong": dong, "apt": apt, "area_band": label,
            "sgg_code": sgg_code,
            "sido": sido,
            "jibun": jibun_value,
            "addr": " ".join(x for x in (sido, gu, dong, jibun_value) if x),
            "search_keyword": " ".join(x for x in (sido, gu, dong, apt) if x),
            "price_manwon": price,
            "price_basis": basis,
            "price_sample_count": used_count,
            "trade_count": len(rows),
            "latest_deal_ym": latest["deal_ym"],
            "latest_price_manwon": latest["price_manwon"],
            "build_year": rows[0].get("build_year", ""),
            "areas_m2": sorted({round(r["area_m2"], 2) for r in rows}),
        })
    return candidates


def attach_distances(
    candidate: Mapping[str, Any],
    stations: Sequence[Mapping[str, Any]],
    schools: Sequence[Mapping[str, Any]],
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """가장 가까운 역과 초·중·고 정보를 붙인 새 dict를 반환한다."""
    station, station_distance = nearest(candidate["lat"], candidate["lon"], stations)
    metrics = school_metrics(candidate["lat"], candidate["lon"], schools, settings or {})
    return {
        **candidate,
        "station": station["name"] if station else "",
        "station_line": station.get("line", "") if station else "",
        "station_dist_m": round(station_distance) if station else None,
        **metrics,
    }


def attach_commute(
    candidate: Mapping[str, Any],
    graph: Any,
    destinations: Sequence[str],
    driving: Any = None,
    destination_coords: Mapping[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """서울 거점까지 지하철·자차 소요시간을 붙이고, 빠른 쪽을 대표값으로 삼는다.

    실제로 사람은 더 빠른 수단을 고르므로 min을 쓴다. 다만 어느 쪽이 빨랐는지
    (commute_mode)와 각각의 값도 남겨서 판단 근거가 보이게 한다.
    """
    station = candidate.get("station")
    transit = (graph.best_access(station, destinations) if station
               else {"minutes": None, "destination": ""})

    drive: dict[str, Any] = {"minutes": None, "destination": "", "km": None, "toll": None}
    lat, lon = candidate.get("lat"), candidate.get("lon")
    if driving and destination_coords and isinstance(lat, (int, float)) \
            and isinstance(lon, (int, float)):
        drive = driving.best_access(lat, lon, destination_coords)

    options = [(transit["minutes"], "지하철", transit["destination"]),
               (drive["minutes"], "자차", drive["destination"])]
    usable = [o for o in options if o[0] is not None]
    best = min(usable, key=lambda o: o[0]) if usable else (None, "", "")

    return {
        **candidate,
        "transit_min": transit["minutes"],
        "transit_to": transit["destination"],
        "drive_min": drive["minutes"],
        "drive_to": drive["destination"],
        "drive_km": drive.get("km"),
        "drive_toll": drive.get("toll"),
        "commute_min": best[0],
        "commute_mode": best[1],
        "commute_to": best[2],
    }


def passes_commute(candidate: Mapping[str, Any], criteria: Mapping[str, Any]) -> bool:
    """통근시간 상한 조건. 상한이 0이면 제한하지 않는다."""
    limit = criteria.get("max_commute_min") or 0
    if not limit:
        return True
    minutes = candidate.get("commute_min")
    return minutes is not None and minutes <= limit


def passes_distance(candidate: Mapping[str, Any], criteria: Mapping[str, Any]) -> bool:
    """역세권(필수)·학교(선택) 거리 조건 통과 여부."""
    station_distance = candidate.get("station_dist_m")
    if station_distance is None or station_distance > criteria["station_max_distance_m"]:
        return False
    if not criteria.get("school_filter"):
        return True
    school_distance = candidate.get("school_dist_m")
    return school_distance is not None and school_distance <= criteria["school_max_distance_m"]


DEFAULT_COMMUTE_REFERENCE_MIN = 60
DEFAULT_HOUSEHOLDS_FOR_FULL = 1500
DEFAULT_SCHOOLS_FOR_FULL = 3
DEFAULT_ACADEMY_SATURATION = 80
DEFAULT_AMENITY_RADIUS = {"hospital": 1000, "mart": 1500, "market": 1500, "academy": 1000}
HOSPITAL_COUNT_FOR_FULL = 30

# 학군 세부 가중치 (합 1.0): 중학교 접근성 · 고등학교 접근성 · 학원가 밀집도
SCHOOL_ZONE_MIX = {"middle": 0.35, "high": 0.25, "academy": 0.40}

SCHOOL_KINDS = {"school": "초등학교", "middle_school": "중학교", "high_school": "고등학교"}

# 시군구코드 앞 2자리 → 시도명. 실거래 응답에는 시도명이 없어 코드로 복원한다.
SIDO_BY_CODE = {"11": "서울", "41": "경기", "28": "인천"}


def sido_of(sgg_code: str | None) -> str:
    """시군구코드에서 시도명을 얻는다. 모르면 빈 문자열."""
    return SIDO_BY_CODE.get((sgg_code or "")[:2], "")


def school_metrics(
    lat: float,
    lon: float,
    schools: Sequence[Mapping[str, Any]],
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    """초·중·고 각각의 최근접 학교와 반경 내 개수를 구한다."""
    radius = {
        "middle_school": settings.get("middle_radius_m", 1000),
        "high_school": settings.get("high_radius_m", 1500),
    }
    metrics: dict[str, Any] = {}
    for prefix, kind in SCHOOL_KINDS.items():
        of_kind = [s for s in schools if s.get("kind") == kind]
        found, distance = nearest(lat, lon, of_kind)
        metrics[prefix] = found["name"] if found else ""
        metrics[f"{prefix}_dist_m"] = round(distance) if found else None
        if prefix in radius:
            metrics[f"{prefix}_count"] = count_within(lat, lon, of_kind, radius[prefix])
    return metrics


def school_zone_score(candidate: Mapping[str, Any], settings: Mapping[str, Any]) -> float:
    """학군 점수 0~1. 중·고 접근성과 학원가 밀집도로 근사한다."""
    schools_full = settings.get("schools_for_full_score") or DEFAULT_SCHOOLS_FOR_FULL
    academy_full = settings.get("academy_saturation") or DEFAULT_ACADEMY_SATURATION
    return (
        SCHOOL_ZONE_MIX["middle"] * _saturating(candidate.get("middle_school_count"), schools_full)
        + SCHOOL_ZONE_MIX["high"] * _saturating(candidate.get("high_school_count"), schools_full)
        + SCHOOL_ZONE_MIX["academy"] * _saturating(candidate.get("academy_count"), academy_full)
    )


def score_components(
    candidate: Mapping[str, Any],
    criteria: Mapping[str, Any],
    settings: Mapping[str, Any] | None = None,
    current_year: int | None = None,
) -> dict[str, float]:
    """각 항목을 0~1로 정규화한 값. 가중치를 곱하기 전 단계."""
    settings = settings or {}
    current_year = current_year or date.today().year
    radius = {**DEFAULT_AMENITY_RADIUS, **(settings.get("amenity_radius") or {})}

    commute_limit = criteria.get("max_commute_min") or DEFAULT_COMMUTE_REFERENCE_MIN
    return {
        "commute": _closer_is_better(candidate.get("commute_min"), commute_limit),
        "station_distance": _closer_is_better(
            candidate.get("station_dist_m"), criteria["station_max_distance_m"]),
        "school_distance": _closer_is_better(
            candidate.get("school_dist_m"), criteria["school_max_distance_m"]),
        "school_zone": school_zone_score(candidate, settings),
        "households": _saturating(
            candidate.get("households"),
            settings.get("households_for_full_score") or DEFAULT_HOUSEHOLDS_FOR_FULL),
        "build_year": _build_year_score(candidate.get("build_year"), current_year),
        "hospital": (
            0.5 * _saturating(candidate.get("hospital_count"), HOSPITAL_COUNT_FOR_FULL)
            + 0.5 * _closer_is_better(candidate.get("hospital_nearest_m"), radius["hospital"])),
        "mart": _closer_is_better(candidate.get("mart_nearest_m"), radius["mart"]),
        "market": _closer_is_better(candidate.get("market_nearest_m"), radius["market"]),
        "trade_activity": _saturating(candidate.get("trade_count"), TRADE_COUNT_FOR_FULL),
    }


def score_candidate(
    candidate: Mapping[str, Any],
    weights: Mapping[str, float],
    criteria: Mapping[str, Any],
    settings: Mapping[str, Any] | None = None,
    current_year: int | None = None,
) -> float:
    """0~100 점수. 설정에 없는 가중치 항목은 무시한다."""
    components = score_components(candidate, criteria, settings, current_year)
    total = sum(weight * components[name]
                for name, weight in weights.items() if name in components)
    return round(total, 1)


def group_maxima(
    weights: Mapping[str, float], groups: Mapping[str, Mapping[str, Any]]
) -> dict[str, float]:
    """그룹별 만점. 각 그룹에 속한 항목 배점의 합."""
    return {name: sum(weights.get(item, 0) for item in spec.get("items", []))
            for name, spec in groups.items()}


def group_scores(
    candidate: Mapping[str, Any],
    weights: Mapping[str, float],
    criteria: Mapping[str, Any],
    settings: Mapping[str, Any] | None,
    groups: Mapping[str, Mapping[str, Any]],
    current_year: int | None = None,
) -> dict[str, float]:
    """교통·학군·단지·생활인프라처럼 묶어서 본 점수.

    총점을 쪼갠 것이므로 모든 그룹 점수의 합은 총점과 같다.
    """
    components = score_components(candidate, criteria, settings, current_year)
    return {
        name: round(sum(weights.get(item, 0) * components[item]
                        for item in spec.get("items", []) if item in components), 1)
        for name, spec in groups.items()
    }


def validate_groups(
    weights: Mapping[str, float], groups: Mapping[str, Mapping[str, Any]]
) -> None:
    """모든 배점 항목이 정확히 한 그룹에만 들어가는지 확인한다.

    빠지거나 겹치면 그룹 점수의 합이 총점과 달라져 표가 거짓말을 하게 된다.
    """
    seen: list[str] = []
    for name, spec in groups.items():
        for item in spec.get("items", []):
            if item not in weights:
                raise ConfigError(
                    f"score_groups['{name}']에 배점표에 없는 항목이 있습니다: {item}")
            seen.append(item)
    duplicated = sorted({item for item in seen if seen.count(item) > 1})
    if duplicated:
        raise ConfigError(f"여러 그룹에 중복된 항목이 있습니다: {', '.join(duplicated)}")
    missing = sorted(set(weights) - set(seen))
    if missing:
        raise ConfigError(f"어느 그룹에도 속하지 않은 배점 항목이 있습니다: {', '.join(missing)}")


def value_per_eok(candidate: Mapping[str, Any]) -> float | None:
    """가성비 = 억당 점수. 같은 점수면 쌀수록, 같은 값이면 점수가 높을수록 크다.

    점수 자체에는 가격을 넣지 않는다. 입지·단지 품질(점수)과 가격 부담을
    분리해서 봐야 어느 쪽을 얼마나 양보하는지가 드러나기 때문이다.
    """
    price = candidate.get("price_manwon") or 0
    score = candidate.get("score")
    if not price or score is None:
        return None
    return round(score / (price / 10000), 1)


def _build_year_score(build_year: Any, current_year: int) -> float:
    """준공년도 점수 0~1. 모르면 평균 연식으로 가정한다."""
    try:
        age = current_year - int(build_year)
    except (TypeError, ValueError):
        age = UNKNOWN_BUILDING_AGE
    if age < 0:
        age = UNKNOWN_BUILDING_AGE
    return max(0.0, 1 - age / MAX_BUILDING_AGE)


def _saturating(value: float | None, full: float) -> float:
    """value가 full 이상이면 1.0. 없으면 0.0."""
    if not value or not full:
        return 0.0
    return min(1.0, value / full)


def _closer_is_better(distance: float | None, limit: float) -> float:
    """거리를 0~1 점수로. 없거나 기준거리 이상이면 0점."""
    if distance is None or not limit:
        return 0.0
    return max(0.0, 1 - distance / limit)
