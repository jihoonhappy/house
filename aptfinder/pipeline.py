"""단계별 실행 흐름. CLI 진입점은 이 함수들만 호출한다.

분석 순서는 비용을 기준으로 짰다. 지오코딩·편의시설 조회는 카카오 호출을 쓰므로
공짜로 걸러낼 수 있는 조건(가격·면적·세대수)을 먼저 적용해 대상 수를 줄인 뒤 부른다.
"""
from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import analyze, history, matching, report
from .amenities import AmenityFinder
from .driving import DrivingTimes
from . import config as config_module
from .config import all_districts, data_dir, require_key
from .errors import MissingDataError
from .geocode import KakaoGeocoder
from .logging_util import get_logger
from .errors import ApiError
from .sources import (aptbasis, aptinfo, aptlist, reb, rtms, schools,
                      stations, subway_lines)
from .transit import TransitGraph

log = get_logger("pipeline")

CSV_COLUMNS = [
    "score", "score_transit", "score_school", "score_complex", "score_life",
    "value_per_eok", "gu", "dong", "apt", "area_band",
    "price_manwon", "price_basis",
    "price_avg_manwon", "price_peak_manwon", "price_peak_half", "price_low_manwon",
    "vs_avg_pct", "vs_peak_pct", "history_count",
    "commute_min", "commute_mode", "commute_to",
    "transit_min", "drive_min", "drive_km", "drive_toll",
    "households", "dong_count", "complex_type", "parking", "trade_count",
    "latest_deal_ym", "latest_price_manwon", "build_year",
    "station", "station_line", "station_dist_m",
    "school", "school_dist_m", "middle_school", "middle_school_dist_m",
    "middle_school_count", "high_school", "high_school_dist_m", "high_school_count",
    "academy_count", "hospital_count", "hospital_nearest_m",
    "general_hospital_nearest", "general_hospital_nearest_m",
    "mart_nearest", "mart_nearest_m", "market_nearest", "market_nearest_m",
    "addr",
]


def _budget(cfg: Mapping[str, Any]) -> int | None:
    return (cfg.get("api_limits") or {}).get("kakao_daily_call_budget")


def make_geocoder(cfg: Mapping[str, Any]) -> KakaoGeocoder:
    """설정에서 카카오 지오코더를 만든다 (캐시는 data/geocode_cache.json)."""
    return KakaoGeocoder(require_key(cfg, "kakao_rest"),
                         data_dir() / "geocode_cache.json", call_budget=_budget(cfg))


def make_amenity_finder(cfg: Mapping[str, Any]) -> AmenityFinder:
    """편의시설 조사기 (캐시는 data/amenity_cache.json)."""
    return AmenityFinder(require_key(cfg, "kakao_rest"),
                         data_dir() / "amenity_cache.json", call_budget=_budget(cfg))


def build_transit_graph(cfg: Mapping[str, Any], station_list: Sequence[Mapping[str, Any]],
                        line_rows: Sequence[Mapping[str, Any]]) -> TransitGraph:
    """역 좌표와 노선 순서로 지하철 소요시간 그래프를 만든다."""
    coords: dict[str, tuple[float, float]] = {}
    for station in station_list:
        coords.setdefault(station["name"], (station["lat"], station["lon"]))
    return TransitGraph(line_rows, coords, cfg.get("transit") or {})


def make_driving_times(cfg: Mapping[str, Any]) -> DrivingTimes | None:
    """자차 소요시간 조회기. access.driving이 꺼져 있으면 None."""
    access = cfg.get("access") or {}
    if not access.get("driving"):
        return None
    budget = (cfg.get("api_limits") or {}).get("kakao_driving_call_budget")
    return DrivingTimes(
        require_key(cfg, "kakao_rest"), data_dir() / "driving_cache.json",
        departure_hour=access.get("driving_departure_hour", 8), call_budget=budget)


def destination_coords(
    station_list: Sequence[Mapping[str, Any]], destinations: Sequence[str]
) -> dict[str, tuple[float, float]]:
    """거점역 이름 → 좌표. 자차 길찾기의 도착지로 쓴다."""
    coords: dict[str, tuple[float, float]] = {}
    for station in station_list:
        name = station["name"]
        if name in destinations and name not in coords:
            coords[name] = (station["lat"], station["lon"])
    return coords


def scoring_settings(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """점수 계산에 필요한 설정을 한 dict로 모은다."""
    amenity_radius = {name: spec.get("radius_m")
                      for name, spec in (cfg.get("amenities") or {}).items()}
    return {
        **(cfg.get("school_zone") or {}),
        "households_for_full_score": cfg.get("households_for_full_score"),
        "amenity_radius": amenity_radius,
    }


def run_collect(cfg: Mapping[str, Any]) -> None:
    """1단계: 실거래·지하철역·학교·공동주택 정보를 모은다."""
    log.info("=== 1/8 실거래가 수집 ===")
    rtms.collect(cfg, require_key(cfg, "data_go_kr"))
    log.info("=== 2/8 지하철역 좌표 ===")
    stations.collect(require_key(cfg, "seoul_open_data"))
    log.info("=== 3/8 단지 식별정보 (세대수·단지명) ===")
    reb.load(cfg.get("reb_csv"))
    log.info("=== 4/8 공동주택 정보 (주상복합 판별) ===")
    aptinfo.collect(require_key(cfg, "seoul_open_data"))
    log.info("=== 5/8 전국 단지 목록 (서울 밖 주상복합 판별) ===")
    try:
        aptlist.collect(require_key(cfg, "data_go_kr"),
                        aptlist.sido_codes(all_districts(cfg)))
    except ApiError as e:
        log.warning("단지 목록을 건너뜁니다 — 서울 밖 단지는 분류 미확인으로 남습니다.\n%s", e)
    log.info("=== 6/8 지하철 노선/역 순서 ===")
    subway_lines.collect(require_key(cfg, "seoul_open_data"))
    log.info("=== 7/8 학교 위치 ===")
    schools.collect(require_key(cfg, "neis"), make_geocoder(cfg),
                    cfg.get("school_office_codes") or schools.DEFAULT_OFFICE_CODES)
    months = cfg.get("history_months") or 84
    log.info("=== 8/8 가격 이력 %d개월(%.0f년) ===", months, months / 12)
    history.build(cfg, require_key(cfg, "data_go_kr"), all_districts(cfg))
    log.info("완료. 다음: python3 02_analyze.py")


def _load_optional(name: str) -> dict[str, Any]:
    """있으면 읽고 없으면 빈 dict. 선택적 산출물용."""
    path = data_dir() / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load(name: str) -> Any:
    path = data_dir() / name
    if not path.exists():
        raise MissingDataError(f"{path} 가 없습니다. 먼저 python3 01_collect.py 를 실행하세요.")
    return json.loads(path.read_text(encoding="utf-8"))


def run_analyze(cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    """2단계: 조건 필터 + 점수화 → data/candidates.json / candidates.csv."""
    criteria = cfg["criteria"]
    settings = scoring_settings(cfg)
    trades = _load("trades_all.json")
    station_list = _load("stations.json")
    school_list = _load("schools.json")
    line_rows = _load("subway_lines.json")
    complexes = _load("apt_info.json")
    address_index = matching.build_address_index(_load("reb_complexes.json"))
    log.info("입력: 거래 %d건 · 역 %d곳 · 학교 %d곳 · 공동주택 %d곳",
             len(trades), len(station_list), len(school_list), len(complexes))

    recent = set(rtms.recent_months(criteria["price_window_months"]))
    candidates = analyze.build_candidates(trades, cfg["area_bands"], criteria, recent)
    log.info("가격·면적·거래건수 조건 통과: %d곳", len(candidates))

    # 지오코딩 전에 세대수·매칭 조건으로 줄인다 (카카오 호출 절감)
    classified = matching.classified_regions(complexes)
    registered = [matching.attach_registry(c, address_index) for c in candidates]
    sized = [c for c in registered if matching.passes_complex_filter(c, criteria, classified)]
    log.info("단지 매칭 %d곳 → 세대수 %d+ 조건 통과: %d곳",
             sum(1 for c in registered if c["matched"]),
             criteria.get("min_households") or 0, len(sized))
    if not sized:
        return _save([], cfg)

    geocoder = make_geocoder(cfg)
    located = []
    for index, candidate in enumerate(sized, 1):
        coord = geocoder.lookup(candidate["addr"], keyword=candidate["search_keyword"])
        if coord:
            located.append({**candidate, "lat": coord[0], "lon": coord[1]})
        if index % 100 == 0:
            log.info("  지오코딩 %d/%d", index, len(sized))
    geocoder.save()
    log.info("좌표 확보: %d/%d곳", len(located), len(sized))

    # 거리·통근 조건을 먼저 걸러 유료 조회 대상을 줄인다.
    # (단지분류는 공공데이터포털 일일 호출 한도가 있어 살아남은 후보만 조회한다)
    with_distance = [analyze.attach_distances(c, station_list, school_list, settings)
                     for c in located]
    near_station = [c for c in with_distance if analyze.passes_distance(c, criteria)]
    log.info("역세권 %dm 조건 통과: %d곳", criteria["station_max_distance_m"], len(near_station))
    if not near_station:
        return _save([], cfg)

    graph = build_transit_graph(cfg, station_list, line_rows)
    destinations = (cfg.get("access") or {}).get("destinations") or []
    drives = make_driving_times(cfg)
    coords = destination_coords(station_list, destinations) if drives else {}
    commuting = []
    for index, candidate in enumerate(near_station, 1):
        try:
            commuting.append(
                analyze.attach_commute(candidate, graph, destinations, drives, coords))
        except ApiError as e:
            log.warning("자차 조회 중단, 이후는 지하철만 사용: %s", e)
            drives = None
            commuting.append(analyze.attach_commute(candidate, graph, destinations))
        if drives and index % 200 == 0:
            log.info("  자차 소요시간 %d/%d", index, len(near_station))
    if drives:
        drives.save()
        log.info("자차 조회 완료 (호출 %d건, 기준 %s)", drives.calls, drives.departure)
    reachable = [c for c in commuting if analyze.passes_commute(c, criteria)]
    limit = criteria.get("max_commute_min") or 0
    log.info("서울 접근 %s 조건 통과: %d곳",
             f"{limit}분 이내" if limit else "제한없음", len(reachable))
    if not reachable:
        return _save([], cfg)

    detailed = [matching.attach_complex_info(c, complexes) for c in reachable]
    detailed, classified = _classify_nationwide(cfg, detailed, classified)
    kept = [c for c in detailed if matching.passes_complex_filter(c, criteria, classified)]
    excluded_types = criteria.get("exclude_complex_types") or []
    dropped_type = sum(1 for c in detailed
                       if any(t in (c["complex_type"] or "") for t in excluded_types))
    unknown = sum(1 for c in detailed if not c["complex_type"])
    log.info("단지분류 확인 %d곳 · %s %d곳 제외 · 미확인 %d곳 → %d곳 (분류자료 보유 지역: %s)",
             len(detailed) - unknown, "/".join(excluded_types), dropped_type, unknown,
             len(kept), "·".join(sorted(classified)) or "없음")
    if not kept:
        return _save([], cfg)
    near_station = kept

    finder = make_amenity_finder(cfg)
    specs = cfg.get("amenities") or {}
    surveyed = []
    for index, candidate in enumerate(near_station, 1):
        surveyed.append({**candidate,
                         **finder.survey_all(candidate["lat"], candidate["lon"], specs)})
        if index % 50 == 0:
            log.info("  편의시설 조사 %d/%d", index, len(near_station))
    finder.save()
    log.info("편의시설 조사 완료 (카카오 호출 %d건)", finder.calls)

    price_history = _load_optional("price_history.json")
    if price_history:
        log.info("가격 이력 적용: %d개 단지·면적대", len(price_history))
    groups = cfg.get("score_groups") or {}
    scored = []
    for candidate in surveyed:
        with_score = {**candidate,
                      "score": analyze.score_candidate(
                          candidate, cfg["scoring"], criteria, settings)}
        by_group = analyze.group_scores(
            candidate, cfg["scoring"], criteria, settings, groups)
        scored.append(history.attach({
            **with_score,
            "value_per_eok": analyze.value_per_eok(with_score),
            **{f"score_{name}": value for name, value in by_group.items()},
        }, price_history))
    scored.sort(key=lambda c: -c["score"])
    return _save(scored, cfg)


def _classify_nationwide(
    cfg: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    classified: set[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    """서울 데이터로 분류하지 못한 단지를 전국 API로 보완한다 (목록이 있을 때만)."""
    listings_path = data_dir() / "apt_list.json"
    if not listings_path.exists():
        return [dict(c) for c in candidates], classified

    listings = json.loads(listings_path.read_text(encoding="utf-8"))
    index = matching.build_national_index(listings)
    lookup = aptbasis.AptBasisLookup(require_key(cfg, "data_go_kr"),
                                     data_dir() / "apt_basis_cache.json")
    resolved = []
    for candidate in candidates:
        try:
            resolved.append(matching.attach_national_info(candidate, index, lookup))
        except ApiError as e:
            log.warning("전국 단지분류 조회 중단: %s", e)
            resolved.extend(dict(c) for c in candidates[len(resolved):])
            break
    lookup.save()
    covered = classified | {aptinfo.normalize_sido(listing.get("sido"))
                            for listing in listings if listing.get("sido")}
    log.info("전국 단지분류 보완: %d곳 조회 (신규 확인 %d곳)", lookup.calls,
             sum(1 for c in resolved if c.get("complex_type"))
             - sum(1 for c in candidates if c.get("complex_type")))
    return resolved, covered


def _save(
    candidates: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]
) -> list[dict[str, Any]]:
    directory = data_dir()
    (directory / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(directory / "candidates.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)
    log.info("최종 후보 %d곳 → data/candidates.json · data/candidates.csv", len(candidates))
    log.info("다음: python3 03_dashboard.py")
    return list(candidates)


def run_dashboard(cfg: Mapping[str, Any]) -> Path:
    """3단계: 후보 목록을 HTML 대시보드로 만든다."""
    candidates = _load("candidates.json")
    if not candidates:
        log.warning("후보가 0곳입니다. config.yaml의 조건을 완화한 뒤 02_analyze.py를 다시 실행하세요.")
    groups = cfg.get("score_groups") or {}
    maxima = analyze.group_maxima(cfg["scoring"], groups)
    out = report.write(candidates, cfg["criteria"], groups=groups, maxima=maxima)
    log.info("대시보드 생성 완료 (%d곳) → %s", len(candidates), out)

    publish_to = (cfg.get("publish_to") or "").strip()
    if publish_to:
        published = report.write(candidates, cfg["criteria"],
                                 Path(config_module.PROJECT_ROOT) / publish_to,
                                 groups=groups, maxima=maxima)
        log.info("공개용 사본 → %s", published)
    return out
