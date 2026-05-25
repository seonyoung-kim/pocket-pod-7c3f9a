# pocket-pod

Personal YouTube → audio podcast pipeline that runs on **your LAN**.
Curates videos from a channel watchlist (recent + top view_count), extracts audio
with yt-dlp, publishes an iTunes-compatible RSS that local podcast apps can
subscribe to.

**Design:** [docs/superpowers/specs/2026-05-25-pocket-pod-redesign.md](docs/superpowers/specs/2026-05-25-pocket-pod-redesign.md)
**Plan:** [docs/superpowers/plans/2026-05-25-pocket-pod-impl.md](docs/superpowers/plans/2026-05-25-pocket-pod-impl.md)

## How it works

1. **Watchlist** — `config/watchlist.yaml`에 채널 등록. 웹 UI에서도 추가/삭제 가능.
2. **Curate** — `python -m scripts.curator` 또는 웹 UI의 [↻ Refresh Candidates]
   버튼이 각 채널의 최근 N일 영상을 yt-dlp flat extract로 가져와 조회수 상위 K개를
   후보로 제시.
3. **Approve** — 웹 콘솔 (`:8001`) 에서 후보에 [▶ Download] / [✕ Skip].
4. **Download** — 백그라운드 단일 워커가 m4a 추출 → `data/downloads/` 저장 →
   `feed.xml` 재생성.
5. **Subscribe** — 폰/태블릿의 podcast 앱에서 `http://<LAN IP>:8000/feed.xml` 구독.

## Quick start

```bash
git clone <repo>
cd pocket-pod
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 매번 실행
source .venv/bin/activate
POCKET_POD_BASE_URL=http://192.168.45.81:8000 python server.py &
POCKET_POD_BASE_URL=http://192.168.45.81:8000 python app.py
```

- 콘솔: <http://192.168.45.81:8001>
- 구독 URL: <http://192.168.45.81:8000/feed.xml>

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
| `POCKET_POD_COOKIES` | yt-dlp `--cookies` 경로 | — |
| `POCKET_POD_PROXY` | yt-dlp `--proxy` URL | — |

## Anti-bot

YouTube가 bot으로 의심해 `Sign in to confirm you're not a bot` 에러가 나면:

1. 브라우저에서 youtube.com 로그인 → `cookies.txt`로 export
2. `POCKET_POD_COOKIES=/path/to/cookies.txt` 지정

거주지 proxy가 있으면 `POCKET_POD_PROXY=http://...`도 가능.

## Tests

```bash
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
