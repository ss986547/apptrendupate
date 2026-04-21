# iOS App Idea Scout

주 1회 자동으로 Reddit, Hacker News, App Store 차트 + **경쟁 앱의 저평점 리뷰**, Product Hunt에서 시그널을 수집해서 Gemini로 분석하고 iOS 앱 아이디어 리포트를 생성하는 시스템.

**운영 비용: $0** (Gemini 무료 티어 + GitHub Actions 무료 티어)

## 생성되는 리포트 구조

1. 이번 주 user pain patterns
2. **경쟁사 약점 분석** (저평점 리뷰 기반 — 기존 앱이 뭘 못 하고 있는지)
3. App Store / Product Hunt / HN 마켓 시그널
4. **Top 5 iOS 앱 기회** (MVP 스코프, 수익화, 경쟁 체크 포함)
5. 피해야 할 아이디어
6. "이번 주의 베팅" 추천

---

## 셋업 (최초 1회, 약 15분)

### 1. GitHub 레포 만들기

Public 레포로 만들면 GitHub Actions 완전 무제한. Private으로 하려면 월 2,000분 한도인데 이 워크플로우는 월 40분 정도만 씁니다.

이 폴더를 GitHub에 push.

### 2. Gemini API 키 받기 (무료, 2분)

1. https://aistudio.google.com/app/apikey 접속
2. "Create API key" 클릭
3. 키 복사. 신용카드 등록 불필요.

무료 티어로 gemini-2.5-pro를 하루 100번 쓸 수 있는데, 우리는 주 1번만 씀.

### 3. (선택) Telegram 또는 Discord 알림 세팅

**Telegram Bot:**
1. Telegram에서 `@BotFather` 검색 → `/newbot` → 봇 이름 설정 → **토큰** 받기
2. 만든 봇에 아무 메시지나 보내기
3. `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` 접속해서 `chat.id` 확인

**Discord Webhook:**
1. 본인 Discord 서버 → 채널 설정 → Integrations → Webhooks → New Webhook
2. Webhook URL 복사

둘 다 세팅 안 해도 GitHub 레포 `reports/` 폴더에 리포트가 커밋됨.

### 4. GitHub Secrets 등록

레포 → Settings → Secrets and variables → Actions → New repository secret

필수:
- `GEMINI_API_KEY`

선택:
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `DISCORD_WEBHOOK_URL`

> **Reddit API 키 불필요** — Reddit의 공개 JSON 엔드포인트(`.json` suffix)로 데이터를 가져옵니다. 앱 생성, 승인 절차 전혀 없이 동작.

### 5. 첫 실행 테스트

레포 → Actions 탭 → "Weekly iOS Idea Scout" → "Run workflow" 수동 실행. 3-5분 후 `reports/YYYY-MM-DD-report.md` 생성 확인.

---

## 스케줄

매주 **금요일 오후 5시 (Pacific)** 자동 실행. 주말에 받아서 다음 주 계획을 세울 수 있는 타이밍.

**DST 주의**: cron은 UTC 기준이라 `0 0 * * 6`(토요일 00:00 UTC)으로 설정되어 있습니다. PDT(서머타임, 3-11월) 기간에는 정확히 금 17:00 PT, PST(11-3월) 기간에는 금 16:00 PT로 1시간 빠르게 돌아갑니다. 정확히 맞추고 싶으면 매년 11월/3월에 한 번씩 바꾸거나, 그냥 "금요일 오후" 정도로 두고 쓰세요.

변경하려면 `.github/workflows/weekly-scout.yml`의 cron 값 수정:
```yaml
- cron: '0 0 * * 6'  # 분 시 일 월 요일 (UTC 기준)
```

---

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
├── .github/workflows/weekly-scout.yml   # 매주 월요일 실행
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

## 로컬 실행 (옵션)

GitHub Actions 없이 본인 맥에서 돌리려면:

```bash
export GEMINI_API_KEY=...
pip install -r requirements.txt
python scripts/scout.py
```

macOS에서 crontab으로 스케줄링하려면:
```bash
0 17 * * 5 cd /path/to/ios-idea-scout && /usr/bin/python3 scripts/scout.py
```
