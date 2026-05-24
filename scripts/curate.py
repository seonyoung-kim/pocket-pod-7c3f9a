from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from scripts.episode import Episode
from scripts.youtube_client import YouTubeClient, VideoCandidate
from scripts.gemini_client import GeminiClient


def _load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _within_duration(cand: VideoCandidate, cfg: dict) -> bool:
    lo = cfg["duration"]["min_minutes"] * 60
    hi = cfg["duration"]["max_minutes"] * 60
    return lo <= cand.duration_sec <= hi


def _excluded(cand: VideoCandidate, excludes: list[str]) -> bool:
    text = f"{cand.title} {cand.description}"
    return any(ex in text for ex in excludes)


def _collect_candidates(
    yt: YouTubeClient, cfg: dict
) -> list[VideoCandidate]:
    seen: set[str] = set()
    ids: list[str] = []
    for kw in cfg["keywords"]:
        for vid in yt.search_recent(kw, cfg["recency_days"], max_results=25):
            if vid not in seen:
                seen.add(vid)
                ids.append(vid)
    meta = yt.fetch_metadata(ids)
    return [m for m in meta if _within_duration(m, cfg) and not _excluded(m, cfg.get("excludes", []))]


def _candidate_to_dict(c: VideoCandidate) -> dict:
    return {
        "video_id": c.video_id,
        "title": c.title,
        "channel": c.channel,
        "description": c.description[:500],
        "duration_sec": c.duration_sec,
        "view_count": c.view_count,
        "published_at": c.published_at.isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/interests.yaml")
    parser.add_argument("--out", default="out/selected.json")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stop after Stage 1 (no Pro calls, no fileData)",
    )
    args = parser.parse_args()

    cfg_path = Path(args.config)
    cfg = _load_config(cfg_path)
    interests_text = cfg_path.read_text()

    yt = YouTubeClient()
    gem = GeminiClient()

    print(f"[curate] collecting candidates for keywords={cfg['keywords']}", file=sys.stderr)
    candidates = _collect_candidates(yt, cfg)
    print(f"[curate] {len(candidates)} candidates after filter", file=sys.stderr)
    if not candidates:
        print("[curate] no candidates; exiting", file=sys.stderr)
        return 0

    cand_dicts = [_candidate_to_dict(c) for c in candidates]
    stage1 = gem.score_candidates(interests_text, cand_dicts)
    stage1_sorted = sorted(stage1, key=lambda s: s.score, reverse=True)
    top1 = stage1_sorted[: cfg["stage1_top_n"]]
    print(f"[curate] Stage 1 Top {len(top1)}: " + ", ".join(s.video_id for s in top1), file=sys.stderr)

    if args.dry_run:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(
            [{"video_id": s.video_id, "score": s.score, "reason": s.reason} for s in top1],
            ensure_ascii=False, indent=2,
        ))
        print(f"[curate] dry-run wrote {out_path}", file=sys.stderr)
        return 0

    cand_by_id = {c.video_id: c for c in candidates}
    skip_stage2 = os.environ.get("POCKET_POD_SKIP_STAGE2") == "1"

    if skip_stage2:
        # Free-tier quota for Pro=0; Flash video understanding is slow/quota-heavy.
        # Fall back to Stage 1 ranking only.
        selected_s1 = top1[: cfg["top_n"]]
        episodes = [
            Episode(
                video_id=s1.video_id,
                title=cand_by_id[s1.video_id].title,
                channel=cand_by_id[s1.video_id].channel,
                duration_sec=cand_by_id[s1.video_id].duration_sec,
                url=cand_by_id[s1.video_id].url,
                summary=s1.reason or cand_by_id[s1.video_id].title,
                published_at=cand_by_id[s1.video_id].published_at,
                score=s1.score,
            )
            for s1 in selected_s1
            if s1.video_id in cand_by_id
        ]
        print(f"[curate] Stage 2 skipped (env POCKET_POD_SKIP_STAGE2=1)", file=sys.stderr)
    else:
        verdicts = []
        for s1 in top1:
            cand = cand_by_id.get(s1.video_id)
            if cand is None:
                continue
            try:
                v = gem.deep_analyze(cand.url, interests_text)
                verdicts.append((cand, v))
                print(f"[curate] Stage 2 {cand.video_id} score={v.score:.1f}", file=sys.stderr)
            except Exception as e:
                print(f"[curate] Stage 2 failed for {cand.video_id}: {e}", file=sys.stderr)

        verdicts.sort(key=lambda x: x[1].score, reverse=True)
        selected = verdicts[: cfg["top_n"]]

        episodes = [
            Episode(
                video_id=c.video_id,
                title=c.title,
                channel=c.channel,
                duration_sec=c.duration_sec,
                url=c.url,
                summary=v.summary,
                published_at=c.published_at,
                score=v.score,
            )
            for c, v in selected
        ]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        [ep.to_dict() for ep in episodes],
        ensure_ascii=False, indent=2,
    ))
    print(f"[curate] wrote {len(episodes)} episodes to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
