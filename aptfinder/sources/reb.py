"""한국부동산원 공동주택 단지 식별정보 CSV 적재.

지번 주소를 키로 실거래 단지와 정확히 맞출 수 있고, 세대수·동수·사용승인일과
단지명 3종(공시가격/건축물대장/도로명주소)을 제공한다.
단지명 별칭은 다른 데이터셋(OpenAptInfo)과 매칭할 때 쓴다.

파일: data.go.kr '한국부동산원_공동주택 단지 식별정보_기본정보' (활용신청 없이 다운로드)
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT, data_dir
from ..errors import MissingDataError
from ..logging_util import get_logger

APARTMENT_TYPE = "1"  # 1=아파트, 2=연립주택, 3=다세대주택
CSV_KEYWORD = "공동주택 단지 식별정보"
ENCODINGS = ("utf-8-sig", "cp949", "euc-kr")

# 지번 주소의 끝부분만 본다. 시·군·구 표기는 지역마다 달라(수원장안구, 부천원미구)
# 이름 대신 필지고유번호 앞 5자리(시군구코드)를 키로 쓴다.
JIBUN = re.compile(r"^(\d+)(?:-(\d+))?$")

log = get_logger("reb")


def find_csv(configured: str | None = None) -> Path:
    """설정된 경로 또는 프로젝트 폴더에서 CSV를 찾는다."""
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.exists():
            return path
        raise MissingDataError(f"설정된 REB CSV를 찾을 수 없습니다: {path}")
    # macOS는 파일명을 NFD로 저장하므로 정규화해서 비교한다 (한글 glob이 어긋남)
    keyword = unicodedata.normalize("NFC", CSV_KEYWORD)
    matches = sorted(
        path for path in PROJECT_ROOT.glob("*.csv")
        if keyword in unicodedata.normalize("NFC", path.name)
    )
    if not matches:
        raise MissingDataError(
            "한국부동산원 공동주택 단지 식별정보 CSV가 없습니다.\n"
            "  https://www.data.go.kr/data/15106861/fileData.do 에서 내려받아\n"
            f"  {PROJECT_ROOT} 에 두거나 config.yaml의 reb_csv에 경로를 적으세요."
        )
    return matches[-1]


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise MissingDataError(f"CSV 인코딩을 판별하지 못했습니다: {path}")


def parse_rows(rows: Iterable[Mapping[str, str]]) -> list[dict[str, Any]]:
    """아파트 행만 남기고 필요한 필드로 정리한다 (전국).

    시군구코드는 필지고유번호 앞 5자리다. 실거래 응답의 sggCd와 같은 체계라
    지역 이름 표기가 달라도 정확히 맞출 수 있다.
    """
    parsed = []
    for row in rows:
        if row.get("단지종류") != APARTMENT_TYPE:
            continue
        parts = (row.get("주소") or "").split()
        if len(parts) < 3:
            continue
        match = JIBUN.match(parts[-1])
        pnu = (row.get("필지고유번호") or "").strip()
        if not match or len(pnu) < 5:
            continue
        dong, (bonbun, bubun) = parts[-2], match.groups()
        sgg_code = pnu[:5]
        aliases = {
            (row.get("단지명_공시가격") or "").strip(),
            (row.get("단지명_건축물대장") or "").strip(),
            (row.get("단지명_도로명주소") or "").strip(),
        } - {""}
        parsed.append({
            "complex_id": (row.get("단지고유번호") or "").strip(),
            "sgg_code": sgg_code,
            "sido": parts[0],
            "gu": parts[1],
            "dong": dong,
            "jibun": f"{bonbun}-{bubun}" if bubun else bonbun,
            "bonbun": bonbun,
            "aliases": sorted(aliases),
            "households": int(row.get("세대수") or 0) or None,
            "dong_count": int(row.get("동수") or 0) or None,
            "approved_on": (row.get("사용승인일") or "").strip(),
        })
    return parsed


def load(configured_path: str | None = None, force: bool = False) -> list[dict[str, Any]]:
    """CSV를 읽어 서울 아파트 단지 목록을 반환한다 (JSON으로 캐시)."""
    cache = data_dir() / "reb_complexes.json"
    if cache.exists() and not force:
        complexes = json.loads(cache.read_text(encoding="utf-8"))
        log.info("단지 식별정보: 캐시 사용 (%d건)", len(complexes))
        return complexes

    path = find_csv(configured_path)
    log.info("단지 식별정보 CSV 읽는 중: %s", path.name)
    complexes = parse_rows(csv.DictReader(io.StringIO(_read_text(path))))
    if not complexes:
        raise MissingDataError(
            f"{path.name} 에서 아파트 행을 찾지 못했습니다. 컬럼명을 확인하세요."
        )
    cache.write_text(json.dumps(complexes, ensure_ascii=False), encoding="utf-8")
    log.info("아파트 단지 %d건 → %s", len(complexes), cache)
    return complexes


def index_by_address(complexes: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], dict]:
    """(시군구코드, 동, 지번) → 단지. 본번 키도 함께 넣어 부번 차이를 흡수한다."""
    index: dict[tuple[str, str, str], dict] = {}
    for complex_ in complexes:
        index.setdefault((complex_["sgg_code"], complex_["dong"], complex_["bonbun"]), complex_)
        index[(complex_["sgg_code"], complex_["dong"], complex_["jibun"])] = complex_
    return index
