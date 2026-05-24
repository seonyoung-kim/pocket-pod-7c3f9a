from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

from dateutil.parser import isoparse


def should_delete(published_at_iso: str, retention_days: int, now: datetime) -> bool:
    published = isoparse(published_at_iso)
    return (now - published) > timedelta(days=retention_days)


def _gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--prefix", default="weekly-")
    args = parser.parse_args()

    repo = os.environ.get("GH_REPO") or os.environ["GITHUB_REPOSITORY"]
    now = datetime.now(timezone.utc)

    p = _gh(["release", "list", "--repo", repo, "--limit", "100", "--json", "tagName,publishedAt"])
    releases = json.loads(p.stdout)

    deleted = 0
    for rel in releases:
        tag = rel["tagName"]
        if not tag.startswith(args.prefix):
            continue
        if should_delete(rel["publishedAt"], args.retention_days, now):
            _gh(["release", "delete", tag, "--repo", repo, "--yes", "--cleanup-tag"])
            print(f"[cleanup] deleted {tag}", file=sys.stderr)
            deleted += 1

    print(f"[cleanup] deleted {deleted} release(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
