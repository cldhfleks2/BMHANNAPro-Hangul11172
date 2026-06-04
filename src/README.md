# src/ — 폰트 제작 파이프라인 (개발자용)

이 폴더는 완성판 TTF를 만들 때 사용한 도구입니다.
**폰트를 설치해서 쓰기만 할 사람은 이 폴더를 볼 필요가 없습니다.**
다른 한글 폰트의 누락 음절을 채우는 데 재사용할 수 있습니다 (MIT).

## 실행 방법

```bash
cd src
python3 -m venv .venv && ./.venv/bin/pip install fonttools Pillow numpy

# 보완할 원본 TTF를 source_font.ttf 라는 이름으로 이 폴더에 둔 뒤:
./.venv/bin/python phase2_parts.py      # 자소 부품 추출
./.venv/bin/python phase3_compose.py    # 누락 음절 조립 → output/ 에 TTF 생성
./.venv/bin/python phase4_validate.py   # 전수 렌더링 검증
```

## 파일 설명

| 파일 | 역할 |
|---|---|
| `hannalib.py` | 자소 분리·채점·합성 공용 라이브러리 |
| `analyze.py` | 폰트 구조 진단 (커버리지, 빈 글리프, GSUB) |
| `phase1_coverage.py` | 자소 분해 + donor 커버리지 매트릭스 |
| `phase2_parts.py` | 부품 라이브러리 추출 (호환 자모 기준 채점) |
| `phase2b_check.py` | 조립 가능성 전수 검사 |
| `phase3_compose.py` | 누락 음절 조립 + TTF 주입 |
| `phase4_validate.py` | 전수 렌더링 자동 검증 |
| `phase4_sheets.py` | 시각 검수용 시트 이미지 생성 |
| `regression_suite.json` | 검수에서 지적됐던 글자 목록 (회귀 검사용) |

작업 과정 전체 기록은 [docs/REPORT.md](../docs/REPORT.md) 참고.
