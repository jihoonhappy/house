"""serviceKey 인코딩·재시도·설정 검증 테스트."""
import pytest

from aptfinder import config
from aptfinder.errors import ApiError, ConfigError
from aptfinder.http import build_url, encode_service_key, get

ENCODED = "abc%2Bdef%3D%3D"
DECODED = "abc+def=="


class TestServiceKey:
    def test_encoding_key_is_not_double_encoded(self):
        """이 회귀 테스트가 깨지면 실거래 API가 403으로 죽는다."""
        assert encode_service_key(ENCODED) == ENCODED

    def test_decoding_key_is_encoded_once(self):
        assert encode_service_key(DECODED) == ENCODED

    def test_build_url_keeps_service_key_intact(self):
        url = build_url("https://x/y", ENCODED, {"LAWD_CD": "11680"})
        assert url == f"https://x/y?serviceKey={ENCODED}&LAWD_CD=11680"
        assert "%25" not in url


class TestRetry:
    def test_retries_transient_failure_then_succeeds(self, monkeypatch):
        import urllib.request
        calls = {"n": 0}

        class FakeResponse:
            def read(self):
                return b"ok"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise TimeoutError("slow")
            return FakeResponse()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        assert get("https://x", sleep=lambda s: None) == "ok"
        assert calls["n"] == 3

    def test_gives_up_after_retries(self, monkeypatch):
        import urllib.request

        def always_fail(req, timeout=None):
            raise TimeoutError("slow")

        monkeypatch.setattr(urllib.request, "urlopen", always_fail)
        with pytest.raises(ApiError, match="네트워크"):
            get("https://x", sleep=lambda s: None)


BASE = {
    "api_keys": {"data_go_kr": "k", "seoul_open_data": "k", "neis": "k", "kakao_rest": "k"},
    "criteria": {"price_min": 60000, "price_max": 70000, "lookback_months": 12,
                 "price_window_months": 6, "min_trade_count": 2, "area_min_m2": 59,
                 "area_max_m2": 0, "station_max_distance_m": 500,
                 "school_max_distance_m": 800},
    "area_bands": [{"label": "59㎡형", "min": 55, "max": 66}],
    "scoring": {"station_distance": 40, "school_distance": 30,
                "trade_activity": 15, "build_year": 15},
    "seoul_districts": {"11680": "강남구"},
}


class TestConfigValidation:
    def test_accepts_valid_config(self):
        assert config.validate(BASE) is BASE

    def test_rejects_inverted_price_range(self):
        broken = {**BASE, "criteria": {**BASE["criteria"], "price_min": 80000}}
        with pytest.raises(ConfigError, match="price_min"):
            config.validate(broken)

    def test_rejects_window_longer_than_lookback(self):
        broken = {**BASE, "criteria": {**BASE["criteria"], "price_window_months": 24}}
        with pytest.raises(ConfigError, match="price_window_months"):
            config.validate(broken)

    def test_rejects_missing_area_bands(self):
        broken = {k: v for k, v in BASE.items() if k != "area_bands"}
        with pytest.raises(ConfigError, match="area_bands"):
            config.validate(broken)

    def test_rejects_non_numeric_criteria(self):
        broken = {**BASE, "criteria": {**BASE["criteria"], "price_min": "육억"}}
        with pytest.raises(ConfigError, match="숫자"):
            config.validate(broken)


class TestKeyResolution:
    def test_env_overrides_file_value(self):
        merged = config.apply_env_overrides(BASE, {"APT_KAKAO_REST": "from-env"})
        assert merged["api_keys"]["kakao_rest"] == "from-env"
        assert BASE["api_keys"]["kakao_rest"] == "k"  # 원본 불변

    def test_env_absent_keeps_file_value(self):
        assert config.apply_env_overrides(BASE, {})["api_keys"]["neis"] == "k"

    def test_placeholder_key_is_rejected(self):
        empty = {**BASE, "api_keys": {**BASE["api_keys"], "kakao_rest": ""}}
        with pytest.raises(ConfigError, match="APT_KAKAO_REST"):
            config.require_key(empty, "kakao_rest")
