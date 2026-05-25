#!/bin/bash
# pocket-pod LaunchAgent uninstaller (macOS)

set -euo pipefail

DST_DIR="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

for name in com.pocketpod.server com.pocketpod.app; do
  launchctl bootout "gui/$UID_NUM/$name" 2>/dev/null || true
  rm -f "$DST_DIR/$name.plist"
  echo "[uninstall] removed: $name"
done

echo
echo "✅ LaunchAgent 해제 완료. 데이터(data/, feed.xml)는 그대로 유지됨."
