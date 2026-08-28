#!/usr/bin/env python3
"""02_analyze.py — 조건 필터링 + 점수화

세부 로직은 aptfinder 패키지에 있다. 이 파일은 실행과 오류 보고만 담당한다.
"""
import sys

from aptfinder import config, pipeline
from aptfinder.errors import AptFinderError


def main():
    try:
        pipeline.run_analyze(config.load())
    except AptFinderError as e:
        print(f"\n[중단] {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단됨 (수집한 캐시는 보존됩니다).", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
