"""도메인 예외. 사용자가 무엇을 해야 하는지 알 수 있는 메시지를 담는다."""


class AptFinderError(Exception):
    """이 도구가 스스로 진단한 오류의 최상위 타입."""


class ConfigError(AptFinderError):
    """설정 파일이 없거나, 값이 비었거나, 범위를 벗어남."""


class ApiError(AptFinderError):
    """외부 API 호출 실패. 원인과 조치 방법을 메시지에 담는다."""


class MissingDataError(AptFinderError):
    """앞 단계 산출물이 없어 진행할 수 없음."""
