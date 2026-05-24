from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _gh(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, **kwargs)


def _repo() -> str:
    return os.environ.get("GH_REPO") or os.environ["GITHUB_REPOSITORY"]


def create_release(tag: str, title: str, notes: str) -> None:
    repo = _repo()
    try:
        _gh(["release", "view", tag, "--repo", repo])
        print(f"[publish] release {tag} already exists", file=sys.stderr)
    except subprocess.CalledProcessError:
        _gh([
            "release", "create", tag,
            "--repo", repo,
            "--title", title,
            "--notes", notes,
        ])
        print(f"[publish] created release {tag}", file=sys.stderr)


def upload_assets(tag: str, files: list[Path]) -> None:
    repo = _repo()
    args = ["release", "upload", tag, "--repo", repo, "--clobber", *[str(f) for f in files]]
    _gh(args)
    print(f"[publish] uploaded {len(files)} assets to {tag}", file=sys.stderr)


def asset_url(tag: str, filename: str) -> str:
    repo = _repo()
    return f"https://github.com/{repo}/releases/download/{tag}/{filename}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="out/downloaded.json")
    parser.add_argument(
        "--tag",
        default=f"weekly-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
    )
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    if not manifest:
        print("[publish] empty manifest; nothing to publish", file=sys.stderr)
        return 0

    audio_files = [Path(e["audio_path"]) for e in manifest]
    titles = [f"- {e['title']} ({e['channel']})" for e in manifest]
    notes = "Curated episodes:\n" + "\n".join(titles)

    create_release(args.tag, f"Weekly {args.tag}", notes)
    upload_assets(args.tag, audio_files)

    # enrich manifest with asset URLs for RSS step
    enriched = []
    for e in manifest:
        path = Path(e["audio_path"])
        enriched.append({**e, "asset_url": asset_url(args.tag, path.name), "release_tag": args.tag})
    Path(args.manifest).write_text(json.dumps(enriched, ensure_ascii=False, indent=2))
    print(f"[publish] enriched manifest with asset URLs", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
