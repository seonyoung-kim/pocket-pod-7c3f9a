# pocket-pod 재설계 — 로컬 네트워크 큐레이션 podcast

- **Date:** 2026-05-25
- **Status:** Draft (awaiting review)
- **Supersedes:** [`2026-05-24-pocket-pod-design.md`](./2026-05-24-pocket-pod-design.md)
- **Companion (이식 자산):** `/Users/jupiter/youtube_audio_tool/` (검증용 PoC, 본 레포로 흡수)

## 1. 배경

기존 pocket-pod v1 (`2026-05-24-pocket-pod-design.md`)은 다음 흐름을 목표로 했다.

- GitHub Actions cron이 키워드 검색 + Gemini 점수로 큐레이션
- yt-dlp로 `.m4a` 추출 → GitHub Release 업로드 → GitHub Pages에 `feed.xml` 호스팅
- Apple Podcasts 같은 외부 클라이언트가 RSS 구독

이 흐름은 다음 사유로 폐기한다.

1. **YouTube anti-bot 차단이 누적되어 CI에서 다운로드가 안정적으로 성공하지 않았다.** (커밋 로그: `tv_simply` player_client·residential proxy·cookies 등 다중 우회 시도)
2. 외부 호스팅·완전 자동화를 굳이 가져갈 동기가 약하다. 사용자는 로컬 네트워크 안에서 podcast 앱이 구독되면 충분하다.
3. Gemini 기반 점수는 비용·API 의존이 크다. 단순 조회수 + lookback 윈도우로 충분한 큐레이션이 가능하다.

## 2. 목표

- 채널 구독 기반 큐레이션. 사용자가 watchlist에 채널을 등록하면 최근 N일 영상 중 조회수 상위 K개를 후보로 제시한다.
- 후보는 **수동 승인** 워크플로우 (웹 콘솔에서 [Download]/[Skip]). 자동 다운로드 안 한다.
- 다운로드된 m4a는 로컬 LAN에서 Range 지원 정적 서버로 서빙. iTunes 호환 RSS로 노출.
- 외부 호스팅·CI 자동화 없음. K가 직접 `python server.py & python app.py` 실행.

## 3. 비목표

- YouTube Data API key·Gemini·cron·GitHub Pages·GitHub Release 사용 안 함.
- 키워드 검색 기반 큐레이션은 향후 확장 여지로만 남김 (이번 범위 아님).
- 로컬 LLM·자막 기반 자동 요약은 미포함 (Future work에서 메모만).
- 인증/다중 사용자 지원 안 함 (LAN 내부 단독 사용 가정).

## 4. 아키텍처

```
pocket-pod/
├── server.py      :8000  Range 지원 정적 서버 (RSS + m4a 서빙)
├── app.py         :8001  Flask 큐레이션 콘솔
│
├── scripts/
│   ├── episode.py        Episode 값 타입 (재사용)
│   ├── rss_builder.py    feedgen 기반 RSS XML (재사용)
│   ├── curator.py        yt-dlp 채널 추출 + 점수 (신규)
│   └── downloader.py     m4a 다운로드 + episodes append + feed 재생성 (신규)
│
├── templates/            Jinja2: base / candidates / watchlist / episodes
├── config/watchlist.yaml 구독 채널 (사용자 편집 + 웹 UI 갱신)
├── data/
│   ├── state.json        후보·skipped·episodes·in_progress·last_errors
│   └── downloads/*.m4a
└── feed.xml              런타임 생성 (gitignore)
```

**분리 원칙:**

- `server.py`는 손대지 않는 단순 정적 서버. podcast 앱이 보는 안정성 경계.
- `app.py`는 사용자가 브라우저로 접속하는 큐레이션 콘솔. 변경 잦음.
- `scripts/curator.py` · `scripts/downloader.py`는 CLI와 Flask 양쪽이 호출하는 라이브러리.

**의존성:** `flask`, `yt-dlp`, `feedgen`, `pyyaml`, `python-dateutil`. (`google-genai`, `google-api-python-client` 제거)

**바인딩:** Flask `0.0.0.0:8001`, `http.server` `0.0.0.0:8000`. LAN 외부 노출은 방화벽에 위임. 인증 없음.

**환경 변수:**

| 변수 | 용도 | 디폴트 |
|------|------|--------|
| `POCKET_POD_BASE_URL` | RSS asset URL prefix (예: `http://192.168.45.81:8000`) | `http://localhost:8000` |
| `POCKET_POD_COOKIES` | yt-dlp `cookiefile` 경로 (anti-bot 우회) | 미설정 |
| `POCKET_POD_PROXY` | yt-dlp `proxy` URL (anti-bot 우회) | 미설정 |

## 5. 데이터 모델

### 5.1 `config/watchlist.yaml`

사용자가 직접 편집할 수 있고, 웹 UI가 atomic write (tmp + rename)로도 갱신.

```yaml
defaults:
  lookback_days: 7
  top_k: 5

channels:
  - url: https://www.youtube.com/@AndrejKarpathy
    alias: 카파시
  - url: https://www.youtube.com/@bycloudAI
    lookback_days: 14
    top_k: 3
```

- 채널 URL은 내부에서 yt-dlp로 `UCxxx` 채널 ID로 정규화하여 캐시.
- `defaults` 누락 시 코드 baseline (7일 / 5개).
- yaml 주석은 atomic 쓰기 시 보존되지 않음 (받아들임).

### 5.2 `data/state.json`

```jsonc
{
  "version": 1,
  "last_curated_at": "2026-05-25T14:30:00+09:00",

  "candidates": [
    {
      "video_id": "abc123",
      "channel_id": "UCxxx",
      "channel_name": "Andrej Karpathy",
      "channel_alias": "카파시",
      "title": "Let's reproduce GPT-2",
      "duration_sec": 7234,
      "view_count": 156789,
      "upload_date": "2026-05-20",
      "days_old": 5,
      "url": "https://www.youtube.com/watch?v=abc123",
      "thumbnail_url": "https://i.ytimg.com/vi/abc123/hqdefault.jpg",
      "score": 156789
    }
  ],

  "skipped": [
    {"video_id": "ghi456", "skipped_at": "2026-05-24T11:00:00+09:00"}
  ],

  "episodes": [
    {
      "video_id": "xyz789",
      "title": "...",
      "channel": "Andrej Karpathy",
      "duration_sec": 1234,
      "url": "https://www.youtube.com/watch?v=xyz789",
      "summary": "(yt-dlp description 첫 단락, ~500자)",
      "published_at": "2026-05-18T09:00:00Z",
      "asset_filename": "2026-05-18_xyz789_Lets_reproduce.m4a",
      "asset_bytes": 28491234,
      "downloaded_at": "2026-05-25T14:35:00+09:00"
    }
  ],

  "in_progress": ["bbb222"],
  "last_errors": {
    "ccc333": "yt-dlp: Sign in to confirm you're not a bot"
  }
}
```

| 키 | 역할 | 누가 쓰나 |
|----|------|----------|
| `candidates` | 마지막 큐레이션 결과 | curator가 매번 통째 교체 |
| `skipped` | "받지 않음" 마킹 → 다음 큐레이션에서 제외 | UI [Skip] 버튼 |
| `episodes` | 다운로드 완료 메타. RSS 빌드 입력 | downloader 성공 시 append |
| `in_progress` | 다운로드 진행 중 video_id | downloader 시작/종료 |
| `last_errors` | 최근 다운로드 실패 메시지 | downloader 실패 시 set |

**Atomic write:** tmp 파일 작성 → `os.replace()`로 원본 교체. 손상본은 `state.json.bak`에 보존.

## 6. 큐레이션

### 6.1 데이터 소스

YouTube Data API 안 씀. yt-dlp의 `extract_flat='in_playlist'`로 채널 `/videos` 페이지에서 메타만 추출.

```python
opts = {
    'quiet': True,
    'extract_flat': 'in_playlist',
    'playlistend': N,
    'cookiefile':   os.environ.get('POCKET_POD_COOKIES'),  # 선택
    'http_headers': {'User-Agent': MOBILE_UA},
    'extractor_args': {
        'youtube': {'player_client': ['tv_simply', 'web_safari', 'mweb']}
    },
    'proxy': os.environ.get('POCKET_POD_PROXY'),           # 선택
}
```

각 entry에서 `id`, `title`, `duration`, `view_count`, `upload_date`(YYYYMMDD), `uploader`, `thumbnail`을 얻는다. flat extract 누락 필드(주로 `view_count`/`upload_date`)는 후보에서 제외 (deep fallback 안 함).

### 6.2 알고리즘

```python
def curate(watchlist, state):
    seen = ({e.video_id for e in state.episodes}
            | {s.video_id for s in state.skipped})
    today = date.today()
    all_candidates = []

    for ch in watchlist.channels:
        cfg = ch.merged_with(watchlist.defaults)
        try:
            videos = fetch_channel_videos(ch.url, limit=cfg.top_k * 5)
        except yt_dlp.DownloadError as e:
            log.warning("channel %s skipped: %s", ch.alias or ch.url, e)
            continue
        cutoff = today - timedelta(days=cfg.lookback_days)
        filtered = [
            v for v in videos
            if v.upload_date and v.view_count is not None
            and v.upload_date >= cutoff
            and v.video_id not in seen
        ]
        filtered.sort(key=lambda v: v.view_count, reverse=True)
        all_candidates.extend(filtered[:cfg.top_k])

    all_candidates.sort(
        key=lambda c: (c.upload_date, c.view_count), reverse=True)
    return all_candidates
```

**점수 = `view_count`.** lookback 윈도우가 최근성을 보장하므로 별도 가중치 없음. 향후 가중치 도입 시 `Candidate.score` 필드만 공식 교체.

### 6.3 트리거

- **CLI:** `python -m scripts.curator [--channel <url>]`
- **웹:** `POST /curate` → curator 동기 호출 → 끝나면 `/` redirect
- **동시성:** `data/state.json.lock` 파일 lockfile. 중복 호출 시 409 응답.

## 7. 웹 UI

### 7.1 라우트

| Method | Path | 동작 |
|--------|------|------|
| GET | `/` | 후보 리스트 |
| POST | `/curate` | 큐레이션 실행 |
| POST | `/download/<video_id>` | 다운로드 큐 push (백그라운드) |
| POST | `/skip/<video_id>` | skip 마킹 |
| GET | `/watchlist` | 채널 관리 |
| POST | `/watchlist/add` | 채널 추가 (URL 정규화 시도) |
| POST | `/watchlist/remove` | 채널 삭제 (form: url) |
| GET | `/episodes` | 다운로드된 에피소드 목록 |
| POST | `/episodes/delete/<video_id>` | 에피소드 + 파일 삭제 |

### 7.2 화면 규칙

- 메인 정렬: `upload_date desc`, 동률 시 `view_count desc`.
- 후보 카드: 썸네일, 제목, `채널 · YYYY-MM-DD (Nd) · 길이`, `views`, `[Download] [Skip]`.
- `in_progress` 항목은 버튼 대신 ⏳ 배지. 자동 새로고침 없음.
- `last_errors` 항목은 ⚠ + 사유 + `[Retry]`.
- Subscribe URL: `http://{LAN_IP}:8000/feed.xml` 메인 헤더에 표시 + copy 버튼.

### 7.3 백그라운드 다운로드

- Flask 앱 부팅 시 단일 워커 스레드 시작. `queue.Queue` 소비.
- 워커 1개 = 직렬 처리 (yt-dlp 차단 위험 감소).
- 워커가 `in_progress` set 갱신 + `state.json` persist.
- 앱 재시작 시 in_progress는 비워짐. 진행 중이던 다운로드는 yt-dlp가 부분 파일 남기면 다음 [Retry]로 재시도.

## 8. 다운로드 플로우

```
[Download 클릭]
    ↓
download_queue.put(candidate)         # Flask 즉시 응답
    ↓
worker thread (단일)
    ├─ in_progress 마킹 + state 저장
    ├─ yt-dlp deep fetch                description, exact duration 보강
    ├─ yt-dlp 다운로드 (.m4a, anti-bot opts)
    ├─ 성공:
    │   - state.episodes.append(episode)
    │   - state.candidates에서 제거
    │   - feed.xml 재생성
    │   - in_progress 해제 + state 저장
    └─ 실패:
        - state.last_errors[video_id] = msg
        - in_progress 해제 + state 저장
```

### 8.1 에피소드 description (RSS `<description>`)

`yt-dlp` description의 **첫 단락**(첫 빈 줄 전까지, 최대 ~500자)을 `summary`로 저장.
RSS description 본문은 다음 포맷으로 구성:

```
{summary}

원본: {video_url}
```

- `summary`가 비어있으면 `(설명 없음)`로 대체하고 링크만 노출.
- feedgen의 `<link>` 태그도 동일 URL.
- 향후 자동 요약(자막→로컬 LLM)을 도입할 경우 `summary` 채우는 단계만 교체.

### 8.2 파일 규칙

- 경로: `data/downloads/{episode.audio_filename()}` (= `{YYYY-MM-DD}_{video_id}_{slug}.m4a`)
- asset_url: `{POCKET_POD_BASE_URL}/data/downloads/{filename}` (env 없으면 `http://localhost:8000`)
- 파일명 충돌 시 `_2`, `_3` 접미사 (희박)

### 8.3 retention

자동 삭제 없음. K가 Episodes 페이지 [Delete]로 수동.
향후 `watchlist.yaml`에 `retention_days` 옵션 가능.

## 9. 에러 처리

| 상황 | 감지 | 사용자 영향 | 복구 |
|------|------|------------|------|
| yt-dlp anti-bot (metadata) | `DownloadError` + msg | 후보 페이지에 채널별 ⚠ + 안내 | `POCKET_POD_COOKIES` / `POCKET_POD_PROXY` 환경변수 |
| yt-dlp anti-bot (download) | 동상 | Episodes 페이지에 ⚠ + `[Retry]` | 동상 |
| 네트워크 일시 실패 | `URLError` / timeout | 채널 단위 skip + 로그 | `[Refresh]` 재실행 |
| watchlist.yaml 파싱 실패 | `yaml.YAMLError` | Flask 500 + `*.bak` 자동 복원 | 사용자 수정 |
| state.json 손상 | `JSONDecodeError` | 빈 state로 fresh start + 손상본은 `state.json.bak`에 보존 | 자동 |
| 디스크 부족 | `OSError ENOSPC` | 다운로드 fail 메시지 | 수동 정리 |
| 동시 curate/download | lockfile | 409 응답 | 대기 |

## 10. 테스트 전략

```
tests/
├── test_curator.py        # filter/sort (mock fetch_channel_videos)
├── test_state.py          # load/save atomic write, corrupt 복구
├── test_episode.py        # 기존 유지
├── test_rss_builder.py    # 기존 유지 + description 포맷 검증
├── test_watchlist.py      # yaml add/remove/override merge
└── test_app.py            # Flask route smoke (TestClient + mock curator)
```

실제 yt-dlp 호출은 `tests/integration/`로 분리, 기본 skip (`pytest -m integration`).
CI는 두지 않는다 (GitHub Actions 폐기).

## 11. 마이그레이션

### 11.1 본 PR에서 처리

**삭제 (`git rm`):**

- `.github/workflows/curate.yml`
- `scripts/curate.py`
- `scripts/gemini_client.py`
- `scripts/youtube_client.py`
- `scripts/publish.py`
- `scripts/cleanup.py`
- `config/interests.yaml`

**수정:**

- `requirements.txt` — `google-genai`, `google-api-python-client` 제거 / `flask` 추가
- `.gitignore` — `data/`, `feed.xml`, `state.json.bak`, `*.log` 추가
- `README.md` — 새 워크플로우 기준 재작성
- `scripts/rss_builder.py` — `<description>` 본문 포맷(`summary + 원본 URL`) 점검

**추가:**

- `server.py`, `app.py`
- `scripts/curator.py`, `scripts/downloader.py`
- `templates/base.html`, `candidates.html`, `watchlist.html`, `episodes.html`
- `config/watchlist.yaml` (빈 채널 리스트)

### 11.2 K가 수동 처리

- `/Users/jupiter/youtube_audio_tool/` — 본 레포로 이식 안 함. PoC mp3 5개는 K가 직접 처리.
- 기존 pocket-pod `gh-pages` 브랜치 + GitHub Release — K가 수동 정리.
  ```bash
  gh release list --limit 100
  gh release delete <tag> --yes
  git push origin :gh-pages
  ```
  자동 삭제는 본 PR 범위 아님 (실수 시 복구 불가).

## 12. 실행

```bash
cd ~/IdeaProjects/my/pocket-pod
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 매번
source .venv/bin/activate
python server.py &        # :8000  RSS + m4a 서빙
python app.py             # :8001  큐레이션 콘솔
# 브라우저: http://192.168.45.81:8001
# podcast 앱 구독: http://192.168.45.81:8000/feed.xml
```

추후 `launchd` plist로 부팅 자동 실행 — 본 설계 미포함.

## 13. Future work (메모만)

- 키워드 검색 모드 (`config/watchlist.yaml`에 `keywords:` 섹션 추가).
- 로컬 LLM(Ollama 등) 기반 자막 → 자동 요약.
- 채널별 `retention_days` 자동 정리.
- 단순 토큰 인증 (`POCKET_POD_TOKEN` 환경변수).
