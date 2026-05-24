from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from scripts.rss_builder import build_feed_xml, FeedMeta, FeedEpisode


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


def list_all_releases() -> list[dict]:
    repo = _repo()
    p = _gh(["release", "list", "--repo", repo, "--limit", "100", "--json", "tagName,publishedAt,assets,name,body"])
    return json.loads(p.stdout)


def collect_feed_episodes_from_releases(releases: list[dict]) -> list[FeedEpisode]:
    """Build FeedEpisode list from release notes + asset metadata.

    Release notes are simple bullet lists; we don't parse them.
    Instead, we expect each release to have a sibling 'episodes.json' asset
    that publish.py uploaded — see Step 2.
    """
    out: list[FeedEpisode] = []
    repo = _repo()
    for rel in releases:
        tag = rel["tagName"]
        episodes_asset = next(
            (a for a in rel.get("assets", []) if a["name"] == "episodes.json"),
            None,
        )
        if episodes_asset is None:
            continue
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / "episodes.json"
            _gh(["release", "download", tag, "--repo", repo, "--pattern", "episodes.json", "--dir", td, "--clobber"])
            data = json.loads(local.read_text())
        for e in data:
            out.append(FeedEpisode(
                video_id=e["video_id"],
                title=e["title"],
                channel=e["channel"],
                duration_sec=e["duration_sec"],
                url=e["url"],
                summary=e["summary"],
                published_at=e["published_at"],
                asset_url=e["asset_url"],
                asset_bytes=e["asset_bytes"],
            ))
    out.sort(key=lambda e: e.published_at, reverse=True)
    return out


def publish_pages(feed_xml: bytes) -> None:
    """Push feed.xml + index.html to gh-pages branch via worktree."""
    repo = _repo()
    pages_url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/"
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Add gh-pages worktree
        subprocess.run(
            ["git", "fetch", "origin", "gh-pages"],
            capture_output=True,
        )
        branch_exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/gh-pages"]
        ).returncode == 0
        if branch_exists:
            subprocess.run(
                ["git", "worktree", "add", str(td_path), "gh-pages"],
                check=True,
            )
        else:
            subprocess.run(
                ["git", "worktree", "add", "--orphan", "-b", "gh-pages", str(td_path)],
                check=True,
            )
            # Clean orphan worktree
            for child in td_path.iterdir():
                if child.name == ".git":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        (td_path / "feed.xml").write_bytes(feed_xml)
        (td_path / "index.html").write_text(
            f"<!doctype html><meta charset=utf-8><title>pocket-pod</title>"
            f"<h1>pocket-pod</h1><p>RSS: <a href=\"feed.xml\">feed.xml</a></p>"
        )
        (td_path / ".nojekyll").write_text("")
        subprocess.run(["git", "-C", str(td_path), "add", "-A"], check=True)
        # Allow empty commit (no changes) to avoid failure
        status = subprocess.run(
            ["git", "-C", str(td_path), "status", "--porcelain"],
            capture_output=True, text=True,
        )
        if status.stdout.strip():
            subprocess.run(
                ["git", "-C", str(td_path), "commit", "-m", f"publish feed @ {datetime.now(timezone.utc).isoformat()}"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(td_path), "push", "origin", "gh-pages"],
                check=True,
            )
            print(f"[publish] pushed gh-pages; feed at {pages_url}feed.xml", file=sys.stderr)
        else:
            print("[publish] no changes to gh-pages", file=sys.stderr)
        subprocess.run(["git", "worktree", "remove", str(td_path), "--force"])


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

    # Build episodes.json that future RSS generation will consume.
    # Append to manifest first so it has asset_url populated.
    # NOTE: we know asset_url before upload because we control the tag + filename.
    enriched_for_release = []
    for e in manifest:
        path = Path(e["audio_path"])
        enriched_for_release.append({
            "video_id": e["video_id"],
            "title": e["title"],
            "channel": e["channel"],
            "duration_sec": e["duration_sec"],
            "url": e["url"],
            "summary": e["summary"],
            "published_at": e["published_at"],
            "asset_url": asset_url(args.tag, path.name),
            "asset_bytes": e["asset_bytes"],
        })
    episodes_json = Path("out") / "episodes.json"
    episodes_json.write_text(json.dumps(enriched_for_release, ensure_ascii=False, indent=2))

    create_release(args.tag, f"Weekly {args.tag}", notes)
    upload_assets(args.tag, audio_files + [episodes_json])

    # Regenerate RSS from ALL active releases.
    releases = list_all_releases()
    feed_episodes = collect_feed_episodes_from_releases(releases)
    repo = _repo()
    owner, name = repo.split("/")
    meta = FeedMeta(
        title="pocket-pod",
        description="K's curated YouTube audio feed",
        link=f"https://{owner}.github.io/{name}/",
        author="K",
        image_url=f"https://{owner}.github.io/{name}/cover.png",
        category="Education",
    )
    feed_xml = build_feed_xml(meta, feed_episodes)
    publish_pages(feed_xml)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
