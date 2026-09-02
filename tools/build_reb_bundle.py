#!/usr/bin/env python3
"""한국부동산원 CSV(44MB) → 저장소 동봉용 수도권 사본(약 0.6MB) 생성.

원본은 30만 행 전국 데이터지만 이 도구가 쓰는 건 수도권 아파트의 몇 개 필드뿐이다.
원본을 저장소에 두면 갱신할 때마다 44MB가 이력에 영구히 쌓이므로 파생본만 둔다.

    python3 tools/build_reb_bundle.py                 # 자동 탐색한 CSV로 생성
    python3 tools/build_reb_bundle.py path/to.csv     # 경로 지정
"""
import csv
import gzip
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aptfinder.sources import reb  # noqa: E402


def main() -> int:
    configured = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        source = reb.find_csv(configured)
    except Exception as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 1

    text = reb._read_text(source)
    everything = reb.parse_rows(csv.DictReader(io.StringIO(text)))
    metro = reb.metro_only(everything)

    out = reb.bundle_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(
        json.dumps(metro, ensure_ascii=False).encode("utf-8"), 9))

    print(f"원본 {source.name}: {source.stat().st_size / 1024 / 1024:.0f}MB")
    print(f"전국 아파트 {len(everything):,}건 → 수도권 {len(metro):,}건")
    print(f"동봉본 → {out} ({out.stat().st_size / 1024 / 1024:.2f}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
