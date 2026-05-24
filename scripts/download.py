from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts.episode import Episode


def download_episode(ep: Episode, out_dir: Path) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ep.audio_filename()
    cmd = [
        "yt-dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "--extract-audio",
        "--audio-format", "m4a",
        "--no-playlist",
        "--no-progress",
        "-o", str(out_path.with_suffix("")) + ".%(ext)s",
        ep.url,
    ]
    print(f"[download] {ep.video_id} → {out_path.name}", file=sys.stderr)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"[download] FAILED {ep.video_id}: {e.stderr[-400:]}", file=sys.stderr)
        return None
    if not out_path.exists():
        print(f"[download] file missing after yt-dlp: {out_path}", file=sys.stderr)
        return None
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected", default="out/selected.json")
    parser.add_argument("--out-dir", default="out/audio")
    parser.add_argument("--manifest", default="out/downloaded.json")
    args = parser.parse_args()

    selected_path = Path(args.selected)
    out_dir = Path(args.out_dir)

    raw = json.loads(selected_path.read_text())
    episodes = [Episode.from_dict(d) for d in raw]

    manifest: list[dict] = []
    for ep in episodes:
        path = download_episode(ep, out_dir)
        if path is None:
            continue
        entry = ep.to_dict()
        entry["audio_path"] = str(path)
        entry["asset_bytes"] = path.stat().st_size
        manifest.append(entry)

    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"[download] manifest with {len(manifest)} entries → {manifest_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
