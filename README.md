# pocket-pod

Personal YouTube → audio podcast pipeline that runs on **your LAN**.
Curates videos from a channel watchlist (recent + top view_count), extracts audio
with yt-dlp, publishes an iTunes-compatible RSS that local podcast apps can
subscribe to.

**Design:** [docs/superpowers/specs/2026-05-25-pocket-pod-redesign.md](docs/superpowers/specs/2026-05-25-pocket-pod-redesign.md)
**Plan:** [docs/superpowers/plans/2026-05-25-pocket-pod-impl.md](docs/superpowers/plans/2026-05-25-pocket-pod-impl.md)

## How it works

1. **Watchlist** — `config/watchlist.yaml`에 채널 등록. 웹 UI에서도 추가/삭제 가능. 한국어 핸들 URL(`@한글이름`)은 자동으로 percent-encode 처리.
2. **Curate** — `python -m scripts.curator` 또는 웹 UI의 [↻ Refresh Candidates] 버튼이 각 채널의 최근 N일 영상을 yt-dlp flat extract로 가져와 조회수 상위 K개를 후보로 제시. 누락된 메타(view_count·upload_date)는 영상 단위 deep fetch로 1회 보강.
3. **Approve** — 웹 콘솔(`:8001`)에서 후보를 **채널별 섹션**으로 보고, 카드별 [▶ Download] / [✕ Skip] 또는 **체크박스로 묶어서 [▶ Download Selected]** (전체 선택 토글 지원).
4. **Download** — 백그라운드 단일 워커가 m4a 추출 → `data/downloads/` 저장 → `feed.xml` 재생성. RSS `<description>`에는 영상 설명 첫 단락 + 원본 YouTube URL이 함께 embed.
5. **Subscribe** — 폰/태블릿의 podcast 앱에서 `http://<LAN IP>:8000/feed.xml` 구독.

## 실행 방법

### 옵션 1: 앱처럼 자동 시작 (macOS LaunchAgent, 추천)

로그인 시 자동 실행 + 죽으면 자동 재시작. `~/Library/LaunchAgents/`에 두 plist 등록.

```bash
# 최초 1회 — venv + 의존성
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# LaunchAgent 등록 (en0 LAN IP 자동 추출)
./scripts/launchd/install.sh

# 또는 BASE_URL 직접 지정:
POCKET_POD_BASE_URL=http://192.168.45.81:8000 ./scripts/launchd/install.sh
```

상태·로그·해제:

```bash
launchctl list | grep pocketpod                            # 두 줄 보이면 OK
tail -f data/logs/{server,app}.{out,err}.log               # 실시간 로그
./scripts/launchd/uninstall.sh                             # 등록 해제
```

설치 후:
- 콘솔: <http://192.168.45.81:8001>
- 구독: <http://192.168.45.81:8000/feed.xml>

### 옵션 2: 수동 실행 (개발 / 일회성)

```bash
source .venv/bin/activate
POCKET_POD_BASE_URL=http://192.168.45.81:8000 python server.py &
POCKET_POD_BASE_URL=http://192.168.45.81:8000 python app.py
```

## Environment variables

| 변수 | 용도 | 기본값 |
|------|------|--------|
| `POCKET_POD_BASE_URL` | RSS asset URL prefix | `http://localhost:8000` |
| `POCKET_POD_APP_PORT` | Flask 콘솔 포트 | `8001` |
| `POCKET_POD_SERVER_PORT` | 정적 서버 포트 | `8000` |
| `POCKET_POD_SERVER_ROOT` | 정적 서버 working dir | repo root |
| `POCKET_POD_STATE_PATH` | state.json 경로 | `data/state.json` |
| `POCKET_POD_WATCHLIST_PATH` | watchlist.yaml 경로 | `config/watchlist.yaml` |
| `POCKET_POD_DOWNLOADS_DIR` | 오디오 저장 디렉토리 | `data/downloads` |
| `POCKET_POD_FEED_PATH` | feed.xml 출력 | `feed.xml` |
| `POCKET_POD_FEED_TITLE` | RSS title | `pocket-pod` |
| `POCKET_POD_FEED_AUTHOR` | RSS author | `pocket-pod` |
| `POCKET_POD_FEED_IMAGE_URL` | RSS cover image URL | `{POCKET_POD_BASE_URL}/cover.png` |
| `POCKET_POD_COOKIES` | yt-dlp `--cookies` 경로 (anti-bot 우회) | — |
| `POCKET_POD_PROXY` | yt-dlp `--proxy` URL | — |

LaunchAgent로 등록한 상태에서 환경 변수를 바꾸려면 `scripts/launchd/com.pocketpod.*.plist` 의 `EnvironmentVariables` dict 수정 후 `./scripts/launchd/install.sh` 재실행.

## Anti-bot

YouTube가 bot으로 의심해 메타 fetch나 다운로드가 실패하면:

1. 브라우저(`youtube.com`)에 로그인 → 확장(예: *Get cookies.txt LOCALLY*)으로 `cookies.txt` export
2. `POCKET_POD_COOKIES=/path/to/cookies.txt` 지정 후 재시작

거주지 proxy가 있으면 `POCKET_POD_PROXY=http://…` 도 동일 방식.

### 알려진 제약

- 채널 `/videos` 페이지는 tab parser와 호환되도록 `player_client`/모바일 UA를 끄고 yt-dlp default로 추출.
- 영상 단위 metadata fetch는 `process=False` 로 format selection 단계를 건너뜀.
- 일부 영상은 GVS PO Token 을 요구할 수 있음 — cookies 한 번 설정하면 거의 해결됨.

## Podcast cover

기본 cover.png는 1400×1400 보라 그라데이션 + broadcast 아이콘 워드마크.
podcast 앱에 보이는 썸네일이 이것. 자기 디자인으로 교체하려면 동일 경로에
PNG/JPEG 덮어쓰기 (1400~3000px 정사각형 권장, sRGB).

스크립트로 재생성하려면:

```bash
pip install -r requirements-dev.txt   # Pillow 포함
python scripts/gen_cover.py           # → cover.png 갱신
```

URL 자체를 외부 호스팅 이미지로 바꾸고 싶으면 `POCKET_POD_FEED_IMAGE_URL` env 사용.

## Tests

```bash
source .venv/bin/activate
pytest -v
# 실제 yt-dlp 호출은 마커로 분리 (필요 시):
pytest -m integration
```

## Manual cleanup of old gh-pages assets

이전 GitHub Actions 흐름의 잔재(`gh-pages` 브랜치, weekly releases)를 정리하려면:

```bash
gh release list --limit 100
gh release delete <tag> --yes
git push origin :gh-pages
```
