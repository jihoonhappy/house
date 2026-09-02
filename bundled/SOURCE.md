# 동봉 데이터 출처

`reb_metro.json.gz`

- **원본**: [한국부동산원_공동주택 단지 식별정보_기본정보](https://www.data.go.kr/data/15106861/fileData.do) (공공데이터포털)
- **가공**: 전국 30만 행 중 **수도권(서울·경기·인천) 아파트**만 추려 필요한 필드로 정리한 뒤 gzip 압축
- **원본 대비**: 44MB → 약 0.6MB

원본 CSV를 그대로 두면 갱신할 때마다 44MB가 git 이력에 영구히 쌓이므로 파생본만 동봉합니다.

## 갱신 방법

원본이 갱신되면 위 링크에서 새 CSV를 받아 프로젝트 폴더에 두고:

```bash
python3 tools/build_reb_bundle.py
rm -f data/reb_complexes.json      # 캐시를 비워야 새 동봉본이 반영된다
```

## 우선순위

`aptfinder/sources/reb.py`는 다음 순서로 찾습니다.

1. `data/reb_complexes.json` (수집 캐시)
2. 프로젝트 폴더의 원본 CSV — 직접 받은 게 더 최신이므로 동봉본보다 우선
3. 이 동봉본 (수도권만)

수도권 밖으로 대상을 넓히려면 원본 CSV를 직접 받아야 합니다.
