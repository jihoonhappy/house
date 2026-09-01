"""가격 이력 집계.

7년치 원본 거래는 130만 건·280MB에 달해 통째로 들고 있을 수 없다. 대신 수집
캐시를 한 달씩 읽어 "단지 × 면적대 × 반기" 중앙값으로 접어 둔다 (수백 KB).

반기로 묶는 이유: 단지·면적대 단위로 쪼개면 분기당 거래가 0~2건뿐이라
중앙값이 흔들린다. 반기면 추세를 보기에 충분하면서 표본도 견딘다.
"""
from __future__ import annotations

import json
import statistics
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from .analyze import band_for
from .config import data_dir
from .errors import ApiError
from .logging_util import get_logger
from .sources import rtms

log = get_logger("history")

KEY_SEPARATOR = "|"


def half_year(deal_ym: str | None) -> str | None:
    """'202308' → '2023H2'. 형식이 아니면 None."""
    text = (deal_ym or "").strip()
    if len(text) != 6 or not text.isdigit():
        return None
    month = int(text[4:6])
    if not 1 <= month <= 12:
        return None
    return f"{text[:4]}H{1 if month <= 6 else 2}"


def key_of(sgg_code: str, dong: str, apt: str, band: str) -> str:
    return KEY_SEPARATOR.join((sgg_code, dong, apt, band))


def accumulate(
    index: dict[str, dict[str, list[int]]],
    trades: Iterable[Mapping[str, Any]],
    bands: Sequence[Mapping[str, Any]],
) -> None:
    """거래 목록을 (단지×면적대×반기) → 가격목록에 누적한다 (제자리 갱신)."""
    for row in trades:
        band = band_for(row["area_m2"], bands)
        half = half_year(row.get("deal_ym"))
        if band is None or half is None:
            continue
        key = key_of(row.get("sgg_code", ""), row.get("dong", ""), row.get("apt", ""), band)
        index.setdefault(key, {}).setdefault(half, []).append(row["price_manwon"])


def summarise(index: Mapping[str, Mapping[str, list[int]]]) -> dict[str, dict[str, Any]]:
    """누적된 가격목록을 반기 중앙값 시계열과 요약값으로 접는다."""
    summary: dict[str, dict[str, Any]] = {}
    for key, halves in index.items():
        series = [{"half": half, "median": int(statistics.median(prices)),
                   "count": len(prices)}
                  for half, prices in sorted(halves.items())]
        every_price = [p for prices in halves.values() for p in prices]
        medians = [point["median"] for point in series]
        peak = max(series, key=lambda point: point["median"])
        summary[key] = {
            "series": series,
            "avg_manwon": round(statistics.mean(every_price)),
            "peak_manwon": peak["median"],
            "peak_half": peak["half"],
            "low_manwon": min(medians),
            "total_count": len(every_price),
        }
    return summary


def attach(
    candidate: Mapping[str, Any], summary: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """후보에 가격 이력과 전고점·평균 대비 위치를 붙인다."""
    found = summary.get(key_of(candidate.get("sgg_code", ""), candidate.get("dong", ""),
                               candidate.get("apt", ""), candidate.get("area_band", "")))
    if not found:
        return {**candidate, "price_history": [], "price_avg_manwon": None,
                "price_peak_manwon": None, "price_peak_half": "",
                "price_low_manwon": None, "history_count": 0,
                "vs_peak_pct": None, "vs_avg_pct": None}

    price = candidate.get("price_manwon") or 0
    return {
        **candidate,
        "price_history": found["series"],
        "price_avg_manwon": found["avg_manwon"],
        "price_peak_manwon": found["peak_manwon"],
        "price_peak_half": found["peak_half"],
        "price_low_manwon": found["low_manwon"],
        "history_count": found["total_count"],
        "vs_peak_pct": round((price / found["peak_manwon"] - 1) * 100, 1)
        if price and found["peak_manwon"] else None,
        "vs_avg_pct": round((price / found["avg_manwon"] - 1) * 100, 1)
        if price and found["avg_manwon"] else None,
    }


def build(
    cfg: Mapping[str, Any],
    service_key: str,
    districts: Mapping[str, str],
    sleep: Callable[[float], None] = time.sleep,
    force: bool = False,
) -> dict[str, dict[str, Any]]:
    """설정된 기간의 거래를 한 달씩 읽어 이력 요약을 만든다.

    수집 캐시는 rtms와 같은 파일을 쓰므로 이미 받은 달은 다시 받지 않는다.
    원본을 한 번에 메모리에 올리지 않도록 월 단위로 처리한다.
    """
    cache = data_dir() / "price_history.json"
    if cache.exists() and not force:
        summary = json.loads(cache.read_text(encoding="utf-8"))
        log.info("가격 이력: 캐시 사용 (%d개 단지·면적대)", len(summary))
        return summary

    months = rtms.recent_months(cfg.get("history_months") or 84)
    bands = cfg["area_bands"]
    index: dict[str, dict[str, list[int]]] = {}
    directory = data_dir()
    fetched = failed = 0

    for position, (lawd_cd, gu_name) in enumerate(districts.items(), 1):
        for deal_ymd in months:
            path = directory / f"trades_{lawd_cd}_{deal_ymd}.json"
            if path.exists():
                rows = rtms._with_district_code(
                    json.loads(path.read_text(encoding="utf-8")), lawd_cd, gu_name)
            else:
                try:
                    rows = rtms.fetch_month(service_key, lawd_cd, gu_name, deal_ymd, sleep=sleep)
                except ApiError as e:
                    log.warning("  ! %s %s 실패: %s", gu_name, deal_ymd, e)
                    failed += 1
                    continue
                path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
                rows = rtms._with_district_code(rows, lawd_cd, gu_name)
                fetched += 1
                sleep(0.2)
            accumulate(index, rows, bands)
        log.info("  이력 수집 %d/%d 시군구 (%s)", position, len(districts), gu_name)

    summary = summarise(index)
    cache.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    log.info("가격 이력 %d개 단지·면적대 (신규 수집 %d개월분, 실패 %d) → %s",
             len(summary), fetched, failed, cache)
    return summary
