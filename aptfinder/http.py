"""HTTP 유틸 - 재시도, 공공데이터포털 serviceKey 인코딩, 에러 메시지 정규화."""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote, unquote, urlencode

from .errors import ApiError

USER_AGENT = "apt-finder/1.0"
RETRIABLE_STATUS = (429, 500, 502, 503, 504)


def encode_service_key(key: str) -> str:
    """공공데이터포털 serviceKey를 정확히 1회만 URL 인코딩한다.

    포털은 같은 키를 Encoding(이미 %2B 형태)과 Decoding(원문 +) 두 가지로 준다.
    어느 쪽을 붙여넣어도 되도록 '풀었다가 다시 인코딩'한다.
    urlencode()에 함께 넣으면 Encoding 키가 이중 인코딩되어 403이 난다.
    """
    return quote(unquote(key), safe="")


def build_url(
    base: str, service_key: str | None = None, params: Mapping[str, Any] | None = None
) -> str:
    """serviceKey는 직접 인코딩해 붙이고, 나머지 파라미터만 urlencode 한다."""
    query = urlencode(params or {})
    if service_key is None:
        return f"{base}?{query}" if query else base
    head = f"serviceKey={encode_service_key(service_key)}"
    return f"{base}?{head}&{query}" if query else f"{base}?{head}"


def get(
    url: str,
    headers: Mapping[str, str] | None = None,
    timeout: int = 30,
    retries: int = 3,
    backoff: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """GET 후 본문 문자열 반환. 일시적 오류만 재시도하고, 그 외는 즉시 알린다."""
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_error = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=request_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            if e.code not in RETRIABLE_STATUS:
                raise ApiError(f"HTTP {e.code} — {body}") from e
            last_error = ApiError(f"HTTP {e.code} — {body}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = ApiError(f"네트워크 오류: {type(e).__name__}: {e}")
        if attempt < retries - 1:
            sleep(backoff * (2 ** attempt))
    raise last_error


def get_json(
    url: str,
    headers: Mapping[str, str] | None = None,
    timeout: int = 30,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """GET 후 JSON 파싱. 파싱 실패 시 응답 앞부분을 함께 보여준다."""
    text = get(url, headers=headers, timeout=timeout, retries=retries, sleep=sleep)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ApiError(f"JSON 응답을 해석하지 못했습니다: {e}\n응답 앞부분: {text[:200]}") from e
