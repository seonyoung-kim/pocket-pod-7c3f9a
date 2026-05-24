# pocket-pod

Personal YouTube → audio podcast pipeline. Curates videos via Gemini, extracts
audio with yt-dlp, publishes an iTunes-compatible RSS to GitHub Pages.

## How it works

1. GitHub Actions cron runs every Mon & Thu 06:00 KST (also manual trigger via Actions tab).
2. `scripts/curate.py` searches YouTube for `config/interests.yaml` keywords, scores via Gemini Flash, then deep-analyzes Top 10 with Gemini Pro → Top 5.
3. `scripts/download.py` extracts m4a audio with yt-dlp.
4. `scripts/publish.py` creates a GitHub Release (`weekly-YYYY-MM-DD`), uploads the m4a files + `episodes.json`, regenerates `feed.xml` from all active releases, pushes to `gh-pages` branch.
5. `scripts/cleanup.py` deletes releases older than 14 days.

## Subscribe (iPhone Apple Podcasts)

After the first run finishes:
1. `feed.xml` URL: `https://<owner>.github.io/<repo>/feed.xml`
2. iPhone → Podcasts → Library → top-right `…` → "Follow a Show by URL" → paste feed URL.

## Local dev

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest

# dry-run (stops after Stage 1, no Pro calls)
GEMINI_API_KEY=... YOUTUBE_API_KEY=... .venv/bin/python -m scripts.curate --dry-run
```

## Editing interests

`config/interests.yaml` — push changes to `main`, next cron picks them up.
