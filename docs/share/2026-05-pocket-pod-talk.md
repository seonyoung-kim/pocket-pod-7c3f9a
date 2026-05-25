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

- 아이폰12 미니 (배터리 용량), 저렴한 요금제 (데이터 적음)
- 주로 YouTube 콘텐츠 소비 (무료, YouTube Premium 아님) 
  - ❌ 영상 다운로드 안 됨 → 모바일 데이터 빠른 소모 + 신호 끊기면 끝
  - ❌ 백그라운드 재생 안 됨 → 화면 켜놔야 함, 다른 앱 못 씀, 배터리 소모 큼
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

> 도구는 `yt-dlp` + Flask 콘솔(:8001) + 정적 RSS 서버(:8000), macOS LaunchAgent 로 항상 실행.

---

## 부딪힌 다섯 가지 — "YouTube 는 친절하지 않다"

| # | 증상 | 한 줄로 |
|---|------|--------|
| 1 | `@지식인사이드` URL 을 `yt-dlp` 가 raw 로 못 읽음 | **한글 핸들** percent-encode 안 됨 |
| 2 | 후보 리스트가 매번 **0개** | flat extract 에 `view_count` / `upload_date` 누락 |
| 3 | "Unable to recognize tab page" | anti-bot 우회 옵션이 채널 페이지를 깨뜨림 |
| 4 | 다운로드만 가면 "Only images available" | `player_client` 가 GVS PO Token 요구 |
| 5 | LaunchAgent 자동 실행 시 `yt-dlp not found` | system PATH 에 venv·brew 없음 |

다음 슬라이드부터 각각의 진단·해결.

---

## 큐레이션 — 한국 채널 특정 (사례 1·2)

**증상 ①** — `https://www.youtube.com/@지식인사이드` 로 요청 보내면
```
ExtractorError: Unable to recognize tab page
```
→ yt-dlp 가 URL 을 raw 로 받음. **path 만 percent-encode** 하면 정상.

**증상 ②** — flat extract 결과:
```
h6hZNwiMMx4   NA   NA   "쎄함은 과학입니다" FBI 요원이 ...
```
한국 채널의 `/videos` 페이지는 `view_count` / `upload_date` 가 비어 있음.
→ 후보 정렬·필터 정보가 없어 **0개**.
→ 영상 ID 만 받고, 영상 단위 **deep fetch 1회** 로 보강 (`process=False` 로 format selection 단계 skip).

---

## 다운로드 — anti-bot 옵션의 미로 (사례 3·4)

pocket-pod 초기 코드는 anti-bot 회피용으로 `player_client=tv_simply,web_safari,mweb` 박아둠.

| 같은 옵션을 어디 쓰느냐 | 결과 |
|---|---|
| 채널 `/videos` (tab 페이지) | ❌ tab parser 와 비호환 → "Unable to recognize tab page" |
| 영상 deep metadata | ❌ format selection 단계에서 깨짐 → "Requested format is not available" |
| 영상 audio 다운로드 | ❌ GVS PO Token 요구 → "Only images are available" |

**해결**: 옵션 빼고 **yt-dlp default** 가 가장 잘 됨. anti-bot 은 `POCKET_POD_COOKIES` env 로만.

> "방어 옵션을 너무 일찍 박아두면, 그게 새로운 장애가 된다."

---

## 백그라운드 실행 — LaunchAgent 환경 (사례 5)

macOS LaunchAgent 로 등록해서 자동 실행되게 했는데:

```
FileNotFoundError: [Errno 2] No such file or directory: 'yt-dlp'
ERROR: ffprobe and ffmpeg not found.
```

LaunchAgent 가 spawn 하는 process 의 `PATH` 는 **시스템 기본값**.
- venv 의 `yt-dlp` 보이지 않음
- homebrew 의 `ffmpeg` 도 안 보임 (`/opt/homebrew/bin` 누락)

**해결**: 코드에서 절대경로 자동 resolve.
- `_ytdlp_binary()` → `sys.executable` 옆 + PATH fallback
- `_ffmpeg_location()` → brew 위치 probe 후 `--ffmpeg-location` 명시

> 환경이 바뀌면 동작이 바뀐다. 같은 코드, 다른 PATH = 다른 버그.

---

## 일주일 써본 사례

- watchlist: **지식인사이드 + 보다** 2개
- 자동 큐레이션 후보: 채널당 5개씩 **10개**
- 그중 골라 다운로드:
  - 카파시 *"AI-native 의 역량"* (24m)
  - 보다 *"호르무즈 해협"* (28m)
  - 지식인사이드 *"AI로봇 근황"* (19m)
- iPhone Apple Podcasts 에서 LAN 피드 구독 → 자동 fetch, 오프라인 청취 OK

세팅 이후 추가 작업: **클릭 30초/주**

---

## 얻은 인사이트

🎯 **단순한 욕망** ("오디오만 쓰고 싶다") 이 의외로 많은 장애를 통과해야 풀린다
🌐 **공식 API 없이 yt-dlp 한 줄로 모든 채널 데이터를 받지만**, 한국어 채널·anti-bot·macOS 환경의 미묘한 차이가 줄줄이 막음
🧰 **"방어 옵션을 일찍 박지 말 것"** — 같은 옵션이 어디선 회피, 어디선 차단
🔁 **자가-도구의 미덕** — 매일 쓰는 도구라 모든 장애를 직접 해결할 동기가 있음
🪄 **확장 가능** — 같은 패턴으로 블로그→TTS, 사내 영상→사내 podcast 등

---

<!-- _class: lead -->

## Q&A

### 비슷한 상황 / 다른 채널 추천 / 패턴 응용 환영

`my/pocket-pod` · seonyoung.kim
