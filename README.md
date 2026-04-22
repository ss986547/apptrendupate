
## 튜닝 포인트

시스템 돌려보면서 조정할 만한 것들:

**`scripts/scout.py` 상단의 `SUBREDDITS` 리스트** — 본인 관심 카테고리로 교체. r/AppIdeas나 r/SomebodyMakeThis 같은 직접 요청 서브는 꼭 유지.

**`APPSTORE_GENRES`** — 본인이 만들고 싶은 카테고리 중심으로. ID 목록은 [여기](https://affiliate.itunes.apple.com/resources/documentation/genre-mapping/).

**리뷰 스크래핑 노브** (가장 중요한 신호 소스):
- `REVIEW_APPS_PER_GENRE`(기본 5) — 각 장르의 Top N 앱 리뷰 스크래핑
- `REVIEW_PAGES_PER_APP`(기본 3) — 앱당 가져올 리뷰 페이지 수 (페이지당 ~50개)
- `LOW_STAR_THRESHOLD`(기본 3) — 이 별점 이하만 포함 (1-3성). 1-2성만 보고 싶으면 2로
- `MIN_REVIEW_LENGTH`(기본 80자) — 너무 짧은 "meh" 리뷰 필터링

**`ANALYSIS_PROMPT`** — 본인 스킬셋, 선호 수익화 모델, 개발 스타일을 반영해서 수정. 프롬프트를 구체화할수록 결과 품질이 비례해서 올라감.

**`POSTS_PER_SUB`, `COMMENTS_PER_POST`** — 더 많이 보고 싶으면 늘리되, 프롬프트가 Gemini context window(100만 토큰) 대비 너무 길어지면 요약 품질이 떨어짐.

## 리뷰 스크래핑이 왜 핵심인가

Reddit은 "이런 앱 있으면 좋겠다"는 wishful thinking이 많고, App Store 차트는 결과만 보여줍니다. 반면 **1-2성 리뷰는 이미 돈을 내고 쓴 사람이 "이 앱이 이것 때문에 구리다"라고 구체적으로 적어놓은 겁니다.** 이게 기능 갭(feature gap) 또는 새 앱 기회의 가장 직접적인 증거예요.

예를 들어 Productivity 1위 앱의 1성 리뷰 10개가 모두 "widget이 안 된다"고 하면, 그게 바로 widget-first 경쟁 앱을 만들 기회입니다. 매주 이 데이터가 쌓이면 어떤 불만이 지속적인지, 어떤 게 업데이트로 해결됐는지도 추적할 수 있음.

---

## 구조

```
ios-idea-scout/
├── .github/workflows/weekly-scout.yml   # 매월 첫째주 금요일 실행
├── scripts/scout.py                      # 메인 스크립트
├── reports/
│   ├── latest.md                         # 최신 리포트 (항상 업데이트)
│   ├── 2026-04-20-report.md              # 주차별 아카이브
│   └── 2026-04-20-raw.json               # 원본 데이터 (감사/재분석용)
├── requirements.txt
└── README.md
```

리포트를 날짜별로 보관하기 때문에 몇 달 돌리면 "어떤 트렌드가 지속되고 어떤 게 일시적이었는지" 비교 가능 — 이게 실제로 가장 가치 있는 데이터.

---
