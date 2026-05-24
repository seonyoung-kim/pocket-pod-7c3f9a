# pocket-pod

Personal YouTube → audio podcast pipeline. Curates videos via Gemini, extracts
audio with yt-dlp, publishes an iTunes-compatible RSS to GitHub Pages so
Apple Podcasts can subscribe and auto-download for offline listening.

- **Repo:** https://github.com/seonyoung-kim/pocket-pod-7c3f9a (public, but URL is obscure)
- **Feed:** `https://seonyoung-kim.github.io/pocket-pod-7c3f9a/feed.xml`
- **Design:** [docs/superpowers/specs/2026-05-24-pocket-pod-design.md](docs/superpowers/specs/2026-05-24-pocket-pod-design.md)
- **Plan:** [docs/superpowers/plans/2026-05-24-pocket-pod-implementation.md](docs/superpowers/plans/2026-05-24-pocket-pod-implementation.md)

## How it works

1. **Cron** — GitHub Actions runs every **Mon & Thu 06:00 KST** (UTC `0 21 * * 0,3`). Manual trigger via Actions tab is always available.
2. **Curate** (`scripts/curate.py`) — searches YouTube Data API for each keyword in `config/interests.yaml`, filters by duration (5–90 min) and exclusion list, scores all candidates with **Gemini 2.5 Flash** (Stage 1), then optionally deep-analyzes Top 10 with the video-understanding model (Stage 2, currently disabled — see below).
3. **Download** (`scripts/download.py`) — `yt-dlp` extracts `.m4a` audio per selected episode. Uses cookies + mobile UA + multiple player clients to bypass anti-bot.
4. **Publish** (`scripts/publish.py`) — creates GitHub Release `weekly-YYYY-MM-DD`, uploads the `.m4a` files plus an `episodes.json` sidecar, then regenerates `feed.xml` from **all** active releases and pushes to the `gh-pages` branch.
5. **Cleanup** (`scripts/cleanup.py`) — deletes releases older than 14 days (and their tags). Idempotent.

## File structure

```
.github/workflows/curate.yml       cron + manual workflow
config/interests.yaml              keywords + filters
scripts/
  episode.py                       Episode value type
  youtube_client.py                YouTube Data API wrapper
  gemini_client.py                 Gemini Flash / Pro wrappers
  rss_builder.py                   iTunes-compatible RSS XML builder
  curate.py                        orchestrator (search + Gemini)
  download.py                      yt-dlp wrapper
  publish.py                       Release upload + RSS regen + gh-pages push
  cleanup.py                       retention-window release deletion
tests/                             pytest unit tests (Episode, RSS, cleanup)
docs/superpowers/                  spec + implementation plan
```

## Initial setup (one-time, already done)

1. **GitHub repo** created as public (so Release asset URLs are reachable without auth):
   ```bash
   gh repo create pocket-pod-7c3f9a --public --source=. --remote=origin --push
   ```
2. **Gemini API key** — get from https://aistudio.google.com/apikey (use a **personal Gmail**; corporate Workspace accounts often block GCP project creation). Store as repo secret:
   ```bash
   gh secret set GEMINI_API_KEY --repo seonyoung-kim/pocket-pod-7c3f9a
   ```
3. **YouTube Data API key** — in the **same** GCP project AI Studio created, enable "YouTube Data API v3" under APIs & Services → Library, then APIs & Services → Credentials → Create Credentials → API key. Store:
   ```bash
   gh secret set YOUTUBE_API_KEY --repo seonyoung-kim/pocket-pod-7c3f9a
   ```
4. **YouTube cookies** (required to bypass anti-bot — see Troubleshooting). Extract from Chrome:
   ```bash
   ~/IdeaProjects/my/pocket-pod/.venv/bin/yt-dlp \
     --cookies-from-browser chrome \
     --cookies /tmp/yt-cookies.txt \
     --simulate --no-warnings \
     "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
   # filter to YouTube/Google domains (GitHub secret limit is 48 KB)
   grep -E '^(# |\.?(youtube|google|youtu|googlevideo)\.com|\.youtu\.be)' \
     /tmp/yt-cookies.txt > /tmp/yt-cookies-min.txt
   gh secret set YOUTUBE_COOKIES --repo seonyoung-kim/pocket-pod-7c3f9a < /tmp/yt-cookies-min.txt
   rm -P /tmp/yt-cookies.txt /tmp/yt-cookies-min.txt
   ```
5. **GitHub Pages** — enabled automatically after the first successful `publish` (creates `gh-pages` branch). If Pages is not yet enabled, run:
   ```bash
   gh api -X POST /repos/seonyoung-kim/pocket-pod-7c3f9a/pages \
     -f source.branch=gh-pages -f source.path=/
   ```

## Subscribe (iPhone Apple Podcasts)

After at least one successful run:

1. iPhone → **Podcasts** app → **Library** tab → top-right `•••` → **"Follow a Show by URL…"**
2. Paste: `https://seonyoung-kim.github.io/pocket-pod-7c3f9a/feed.xml`
3. Tap **Follow**. Episodes appear within 1–2 minutes.
4. Show settings → enable **Auto-Download** for offline listening with no WiFi.

## Editing interests

`config/interests.yaml`:

```yaml
keywords:
  - 희야기
excludes: []
duration:
  min_minutes: 5
  max_minutes: 90
recency_days: 14
top_n: 5
stage1_top_n: 10
```

Push changes to `main`; the next cron picks them up. No restart required.

## Operations

| Task | Command |
|------|---------|
| Trigger a run now | `gh workflow run curate-and-publish --repo seonyoung-kim/pocket-pod-7c3f9a` |
| Check latest run | `gh run list --repo seonyoung-kim/pocket-pod-7c3f9a --limit 5` |
| Watch live | `gh run watch --repo seonyoung-kim/pocket-pod-7c3f9a <RUN_ID>` |
| Inspect failed step log | `gh run view <RUN_ID> --repo seonyoung-kim/pocket-pod-7c3f9a --log-failed \| head -200` |
| List releases | `gh release list --repo seonyoung-kim/pocket-pod-7c3f9a` |
| Pause publishing | comment out the `schedule:` block in `.github/workflows/curate.yml` |

## Local dev

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest

# argparse check
.venv/bin/python -m scripts.curate --help

# real dry-run (Stage 1 only) — needs both API keys in env
GEMINI_API_KEY=... YOUTUBE_API_KEY=... \
  .venv/bin/python -m scripts.curate --dry-run
```

Unit tests cover `Episode`, RSS builder, and cleanup cutoff logic. The
network-bound modules (YouTube/Gemini/yt-dlp/gh) are smoke-tested via the
first real workflow run, not mocked.

## Troubleshooting / known issues

### Gemini Pro free-tier is `limit: 0`
On the Google AI free tier, `gemini-2.5-pro` has zero daily requests for new
projects (only `gemini-2.5-flash` has a usable allowance). Stage 2 (video
understanding) is therefore **disabled by default** via the env var
`POCKET_POD_SKIP_STAGE2=1` set in the workflow.

To **re-enable Stage 2** (better curation):
- Enable billing on the GCP project tied to `GEMINI_API_KEY`, or
- Switch `_PRO_MODEL` in `scripts/gemini_client.py` to a model your key has
  quota for (`gemini-2.5-flash` is OK but slow for video analysis), and
- Remove `POCKET_POD_SKIP_STAGE2: "1"` from `.github/workflows/curate.yml`.

### YouTube `Sign in to confirm you're not a bot`
GitHub Actions data-center IPs are aggressively challenged by YouTube.
Mitigation in this repo:
- `--extractor-args "youtube:player_client=tv_simply,web_safari,mweb"`
- Mobile Safari User-Agent
- **YouTube cookies** from the K's logged-in Chrome session, stored in the
  `YOUTUBE_COOKIES` secret. The workflow's *"Write YouTube cookies"* step
  materializes it to `out/cookies.txt`, which `download.py` picks up via
  `POCKET_POD_COOKIES_FILE`.

**Cookies expire.** When downloads start failing again with the bot
challenge, re-run the extraction in *Initial setup* step 4 to refresh the
secret.

### GitHub Pages 404 right after first publish
Pages build is async; allow 2–3 minutes after the first `publish` run before
the `feed.xml` URL becomes reachable.

### Workflow hangs on Curate step
If a run sits in `Curate` for more than ~15 minutes, it's almost certainly
Stage 2 video analysis stuck on Gemini rate-limit backoff. Confirm
`POCKET_POD_SKIP_STAGE2: "1"` is set in the workflow.

## Security model

- Repo is **public** but the slug `pocket-pod-7c3f9a` is obscure — discovery
  by guessing is unlikely. **Do not curate sensitive content** — anyone who
  learns the feed URL can listen.
- All API keys live in **GitHub Secrets**, never in code or commits.
- The `YOUTUBE_COOKIES` secret contains K's logged-in YouTube session.
  Treat it as a password: refresh on suspected compromise, never paste its
  value into chat/screenshots, never commit the cookies file.

## Future enhancements (deliberately out of scope)

- Channel weighting (`channels_preferred` in `interests.yaml`)
- Multilingual (English content)
- AI-generated audio intro/summary spliced ahead of the original audio
- Per-episode "listened" feedback to auto-learn interests
- Signed/private RSS URLs

---

Generated with `superpowers:brainstorming` → `writing-plans` →
`subagent-driven-development` flow. See `docs/superpowers/` for the
underlying spec and 14-task implementation plan that built this.
