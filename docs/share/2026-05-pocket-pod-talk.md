---
marp: true
theme: default
paginate: true
footer: 'pocket-pod · 5min share · seonyoung.kim'
style: |
  section { font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
  h1 { color: #4c387c; }
  h2 { color: #333; border-bottom: 2px solid #ffd366; padding-bottom: 6px; }
  blockquote { color: #666; border-left: 4px solid #ffd366; }
  code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }
  .center { text-align: center; }
---

<!-- _class: lead -->

# 🎙️ pocket-pod

### 좋아하는 YouTube 채널을 출퇴근 podcast로 듣기

> 아이디어 · 사례 공유 · 5분

---

## 이걸 왜 만들었나

- 좋아하는 콘텐츠는 **YouTube 채널의 longform** (역사·과학·시사 — 영상 안 봐도 됨)
- 그런데 듣는 시간은 **wifi 없는 환경** — 운전, 등산, 지하철, 비행
- **YouTube Premium 안 쓰면:**
  - ❌ 영상 다운로드 안 됨 → 모바일 데이터 빠른 소모 + 신호 끊기면 끝
  - ❌ 백그라운드 재생 안 됨 → 화면 켜놔야 함, 다른 앱 못 씀
- **"오디오만 미리 받아서 podcast 앱처럼 쓸 수 있으면 좋겠다"**

---

## 아이디어 — 내 손바닥 podcast 채널을 갖자

1. 좋아하는 YouTube **채널 몇 개**를 watchlist에 등록
2. 시스템이 **최근 인기 영상**을 자동으로 골라 보여줌
3. 마음에 드는 것만 클릭 → **오디오만 추출** 해서 보관
4. 내 폰 podcast 앱이 **자동으로 다운로드**

> 한 번 세팅하면 그 다음부터는 클릭 한두 번 = 출퇴근길 콘텐츠 준비 완료

---

## 흐름 한 장으로

```
  [watchlist]    "지식인사이드"  "보다"  ...
       │
       ▼  자동 큐레이션 (최근 7일 · 조회수 상위 5개)
  [후보 리스트]   ☐ 영상1   ☐ 영상2   ☐ 영상3 ...
       │
       ▼  내가 보고 싶은 것만 ☑ 선택
  [오디오 추출]  m4a 파일로 보관
       │
       ▼  내 집 네트워크에서 RSS 발행
  [iPhone Podcasts] 🎧 출퇴근길에 자동 재생
```

---

## 사례 — 일주일 써본 모습

- watchlist 채널 **2개**만 등록
- 페이지 새로고침 → 후보 **10개** 자동 제시
- 그중 **3개** 골라서 ▶ Download
- 다음 날 아침, 폰 podcast 앱에 이미 와 있음
- 운전하면서, 산책하면서 들음

**한 번 세팅 이후 추가 작업 시간: 클릭 30초/주**

---

## 얻은 것 (생각보다 큼)

📴 **오프라인 청취** — 비행기·지하철·등산에서도 끊김 없음 (데이터 0)
🔓 **백그라운드 재생** — 화면 끄고 다른 앱 쓰면서 들음
🎯 **콘텐츠 주도권** — YouTube 알고리즘 추천이 아니라 *내가 고른 채널*만
🔒 **데이터는 내 LAN 안에** — 외부 서비스 가입·로그인 없음
🛠️ **만들기보다 쓰는 게 더 재미있는 도구** — 직접 만든 결과물을 매일 씀

---

## 아이디어 자체가 일반화 가능

- 같은 패턴으로 다른 시나리오:
  - 좋아하는 **블로거 글** → TTS → 출근길 청취
  - 매일 보는 **Slack/뉴스** 요약 → 음성 브리핑
  - 회사 **테크 채널 영상** → 사내 podcast 피드
- 핵심 패턴: **"좋은 콘텐츠는 있는데 내 일상 형식에 안 맞을 때 → 변환해서 자동 배달"**

---

<!-- _class: lead -->

## Q&A

### 채널 추천이나 다른 아이디어 환영

`my/pocket-pod` · seonyoung.kim
