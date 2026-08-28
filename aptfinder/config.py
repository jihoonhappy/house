"""설정 로드 + 검증.

API 키는 환경변수가 있으면 그쪽을 우선한다 (config.yaml에 평문으로 두지 않아도 됨).
검증은 시스템 경계에서 한 번에 수행하고, 실패하면 무엇을 고쳐야 하는지 알려준다.
"""
from __future__ import annotations
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# config.yaml의 키 이름 → 이 값을 덮어쓸 환경변수 이름
ENV_OVERRIDES = {
    "data_go_kr": "APT_DATA_GO_KR",
    "seoul_open_data": "APT_SEOUL_OPEN_DATA",
    "neis": "APT_NEIS",
    "kakao_rest": "APT_KAKAO_REST",
}

PLACEHOLDERS = {"", "여기에_키_입력", "YOUR_KEY", "PUT_YOUR_KEY_HERE"}

_REQUIRED_CRITERIA = (
    "price_min", "price_max", "lookback_months", "price_window_months",
    "min_trade_count", "area_min_m2", "area_max_m2",
    "station_max_distance_m", "school_max_distance_m",
)


def load(path: str | Path | None = None) -> dict[str, Any]:
    """config.yaml을 읽어 환경변수를 덮어씌우고 검증된 dict를 돌려준다."""
    path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    if not path.exists():
        raise ConfigError(
            f"설정 파일이 없습니다: {path}\n"
            "config.example.yaml을 config.yaml로 복사한 뒤 API 키를 채우세요."
        )
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"config.yaml 문법 오류: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml의 최상위는 매핑(key: value)이어야 합니다.")
    return validate(apply_env_overrides(raw))


def apply_env_overrides(
    cfg: Mapping[str, Any], environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """환경변수가 설정된 키만 교체한 새 dict를 반환한다 (원본 불변)."""
    environ = os.environ if environ is None else environ
    keys = dict(cfg.get("api_keys") or {})
    for name, env_name in ENV_OVERRIDES.items():
        value = environ.get(env_name)
        if value:
            keys[name] = value
    return {**cfg, "api_keys": keys}


def validate(cfg: dict[str, Any]) -> dict[str, Any]:
    """필수 항목·타입·범위를 확인한다. 통과하면 cfg를 그대로 반환."""
    criteria = cfg.get("criteria")
    if not isinstance(criteria, dict):
        raise ConfigError("config.yaml에 criteria 블록이 없습니다.")
    for key in _REQUIRED_CRITERIA:
        if key not in criteria:
            raise ConfigError(f"criteria.{key} 항목이 없습니다.")
        if not isinstance(criteria[key], (int, float)) or isinstance(criteria[key], bool):
            raise ConfigError(f"criteria.{key}는 숫자여야 합니다 (현재: {criteria[key]!r}).")

    if criteria["price_min"] > criteria["price_max"]:
        raise ConfigError("criteria.price_min이 price_max보다 큽니다.")
    if criteria["area_max_m2"] and criteria["area_min_m2"] > criteria["area_max_m2"]:
        raise ConfigError("criteria.area_min_m2가 area_max_m2보다 큽니다.")
    if not 1 <= criteria["lookback_months"] <= 60:
        raise ConfigError("criteria.lookback_months는 1~60 사이여야 합니다.")
    if criteria["price_window_months"] > criteria["lookback_months"]:
        raise ConfigError("criteria.price_window_months는 lookback_months보다 클 수 없습니다.")

    bands = cfg.get("area_bands")
    if not isinstance(bands, list) or not bands:
        raise ConfigError("config.yaml에 area_bands 목록이 없습니다.")
    for band in bands:
        if not isinstance(band, dict) or "label" not in band or "min" not in band:
            raise ConfigError(f"area_bands 항목 형식 오류: {band!r} (label/min/max 필요)")

    if not isinstance(cfg.get("scoring"), dict):
        raise ConfigError("config.yaml에 scoring 블록이 없습니다.")
    districts = all_districts(cfg)
    if not districts:
        raise ConfigError(
            "조회할 시군구가 없습니다. seoul_districts 또는 gyeonggi_districts를 채우세요.")
    for code in districts:
        if not (isinstance(code, str) and code.isdigit() and len(code) == 5):
            raise ConfigError(f"시군구코드는 5자리 숫자 문자열이어야 합니다: {code!r}")
    return cfg


def all_districts(cfg: Mapping[str, Any]) -> dict[str, str]:
    """서울·경기 시군구를 하나로 합친 {코드: 이름}."""
    merged: dict[str, str] = {}
    for key in ("seoul_districts", "gyeonggi_districts"):
        block = cfg.get(key) or {}
        if isinstance(block, dict):
            merged.update(block)
    return merged


def require_key(cfg: Mapping[str, Any], name: str) -> str:
    """API 키 하나를 꺼내되, 비었거나 예시값이면 발급 안내와 함께 중단한다."""
    value = (cfg.get("api_keys") or {}).get(name)
    if not value or str(value).strip() in PLACEHOLDERS:
        raise ConfigError(
            f"API 키 '{name}'가 비어 있습니다.\n"
            f"config.yaml의 api_keys.{name}에 입력하거나 "
            f"환경변수 {ENV_OVERRIDES.get(name, 'N/A')}를 설정하세요. (발급 방법은 README.md)"
        )
    return str(value).strip()


def data_dir() -> Path:
    """수집 캐시 폴더. 없으면 만든다."""
    DATA_DIR.mkdir(exist_ok=True)
    return DATA_DIR
