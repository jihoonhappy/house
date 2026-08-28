"""카카오 로컬 API 공용 클라이언트 - 디스크 캐시와 일일 호출 예산 관리.

지오코딩(geocode.py)과 편의시설 조사(amenities.py)가 이 클래스를 함께 쓴다.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .errors import ApiError
from .http import get_json
from .logging_util import get_logger

DISABLED_HINT = (
    "카카오 로컬 API가 비활성화되어 있습니다.\n"
    "  developers.kakao.com → 내 애플리케이션 → 해당 앱 → 제품 설정 → 카카오맵 → 활성화 ON\n"
    "  (켠 뒤 바로 반영됩니다. 키 자체는 유효합니다.)"
)
BUDGET_EXCEEDED_HINT = (
    "카카오 로컬 API 호출 예산({budget}건)을 모두 썼습니다.\n"
    "  지금까지의 결과는 캐시에 저장했습니다. 내일 같은 명령을 다시 실행하면\n"
    "  캐시된 항목은 건너뛰고 남은 것부터 이어서 처리합니다.\n"
    "  (조건을 좁히거나 config.yaml의 api_limits.kakao_daily_call_budget을 조정하세요.)"
)
FLUSH_EVERY = 200

log = get_logger("kakao")


class CachedKakaoClient:
    """호출 결과를 파일에 캐시하고 예산을 지키는 카카오 로컬 API 클라이언트."""

    def __init__(
        self,
        api_key: str,
        cache_path: str | Path,
        delay: float = 0.05,
        sleep: Callable[[float], None] = time.sleep,
        call_budget: int | None = None,
    ) -> None:
        self.api_key = api_key
        self.cache_path = Path(cache_path)
        self.delay = delay
        self.call_budget = call_budget
        self._sleep = sleep
        self._cache = self._load_cache()
        self._dirty = 0
        self.calls = 0

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("캐시를 읽지 못해 새로 시작합니다 (%s): %s", self.cache_path.name, e)
            return {}

    def save(self) -> None:
        """캐시를 디스크에 기록한다."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        self._dirty = 0

    def cached(self, key: str) -> tuple[bool, Any]:
        """(적중여부, 값). 값이 None인 '결과 없음'도 정상 적중으로 본다."""
        if key in self._cache:
            return True, self._cache[key]
        return False, None

    def remember(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._dirty += 1
        if self._dirty >= FLUSH_EVERY:
            self.save()

    def _check_budget(self) -> None:
        if self.call_budget is not None and self.calls >= self.call_budget:
            self.save()
            raise ApiError(BUDGET_EXCEEDED_HINT.format(budget=self.call_budget))

    def request(self, url: str, params: Mapping[str, Any]) -> Any:
        """카카오 로컬 API를 한 번 호출한다. 인증 실패는 조치 안내로 바꿔 던진다."""
        self._check_budget()
        try:
            payload = get_json(
                f"{url}?{urlencode(params)}",
                headers={"Authorization": f"KakaoAK {self.api_key}"},
                timeout=15,
            )
        except ApiError as e:
            if "NotAuthorizedError" in str(e) or "HTTP 403" in str(e):
                raise ApiError(DISABLED_HINT) from e
            raise
        self.calls += 1
        self._sleep(self.delay)
        return payload
