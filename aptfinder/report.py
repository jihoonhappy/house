"""후보 목록 → 지도+표 HTML 대시보드."""
from __future__ import annotations
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .errors import MissingDataError

TEMPLATE_PATH = Path(__file__).parent / "templates" / "dashboard.html"


def build_title(
    criteria: Mapping[str, Any], regions: Sequence[str] | None = None
) -> str:
    """조건을 그대로 제목에 노출해 무엇을 보고 있는지 헷갈리지 않게 한다."""
    low = criteria["price_min"] / 10000
    high = criteria["price_max"] / 10000
    parts = [f"{low:g}~{high:g}억"]
    if criteria.get("area_min_m2"):
        parts.append(f"전용 {criteria['area_min_m2']}㎡+")
    if criteria.get("min_households"):
        parts.append(f"{criteria['min_households']}세대+")
    parts.append(f"역세권 {criteria['station_max_distance_m']}m")
    if criteria.get("max_commute_min"):
        parts.append(f"서울 {criteria['max_commute_min']}분")
    if criteria.get("exclude_complex_types"):
        parts.append("/".join(criteria["exclude_complex_types"]) + " 제외")
    area = "·".join(regions) if regions else "서울"
    return f"실거주 아파트 후보 ({area} · " + " · ".join(parts) + ")"


def regions_of(candidates: Sequence[Mapping[str, Any]]) -> list[str]:
    """후보에 실제로 등장하는 시도 목록 (서울을 앞에 둔다)."""
    found = {c.get("sido") for c in candidates if c.get("sido")}
    return sorted(found, key=lambda name: (name != "서울", name))


def render(
    candidates: Sequence[Mapping[str, Any]],
    criteria: Mapping[str, Any],
    groups: Mapping[str, Mapping[str, Any]] | None = None,
    maxima: Mapping[str, float] | None = None,
) -> str:
    """HTML 문자열을 만든다. </script> 조기 종료를 막기 위해 '<'를 이스케이프."""
    if not TEMPLATE_PATH.exists():
        raise MissingDataError(f"대시보드 템플릿이 없습니다: {TEMPLATE_PATH}")
    payload = json.dumps(candidates, ensure_ascii=False).replace("<", "\\u003c")
    group_meta = [{"key": name, "label": spec.get("label", name),
                   "max": (maxima or {}).get(name, 0)}
                  for name, spec in (groups or {}).items()]
    return (TEMPLATE_PATH.read_text(encoding="utf-8")
            .replace("__TITLE__", build_title(criteria, regions_of(candidates)))
            .replace("__GROUPS__", json.dumps(group_meta, ensure_ascii=False))
            .replace("__DATA__", payload))


def write(
    candidates: Sequence[Mapping[str, Any]],
    criteria: Mapping[str, Any],
    out_path: str | Path | None = None,
    groups: Mapping[str, Mapping[str, Any]] | None = None,
    maxima: Mapping[str, float] | None = None,
) -> Path:
    """대시보드 파일을 쓰고 경로를 반환한다."""
    out_path = Path(out_path) if out_path else PROJECT_ROOT / "dashboard.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(candidates, criteria, groups, maxima), encoding="utf-8")
    return out_path
