#!/bin/bash
# pocket-pod LaunchAgent installer (macOS)
#
# Usage:
#   ./scripts/launchd/install.sh
#
# Environment overrides:
#   POCKET_POD_BASE_URL   기본값: http://<en0 IP>:8000 자동 추출 → 실패 시 http://localhost:8000
#
# 등록 후 두 LaunchAgent가 로그인 시 자동 시작:
#   - com.pocketpod.server  (:8000  정적 서버)
#   - com.pocketpod.app     (:8001  Flask 콘솔)

set -euo pipefail

HOME_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TPL_DIR="$HOME_DIR/scripts/launchd"
DST_DIR="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

# venv 확인
if [ ! -x "$HOME_DIR/.venv/bin/python" ]; then
  echo "[install] .venv 가 없어. 먼저:" >&2
  echo "  cd $HOME_DIR && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

# BASE_URL 자동 추출 (en0 IPv4 기준)
if [ -z "${POCKET_POD_BASE_URL:-}" ]; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
  if [ -n "$LAN_IP" ]; then
    POCKET_POD_BASE_URL="http://$LAN_IP:8000"
  else
    POCKET_POD_BASE_URL="http://localhost:8000"
  fi
fi

mkdir -p "$DST_DIR" "$HOME_DIR/data/logs"

for name in com.pocketpod.server com.pocketpod.app; do
  src="$TPL_DIR/$name.plist"
  dst="$DST_DIR/$name.plist"
  sed -e "s|__POCKET_POD_HOME__|$HOME_DIR|g" \
      -e "s|__POCKET_POD_BASE_URL__|$POCKET_POD_BASE_URL|g" \
      "$src" > "$dst"
  # 기존 등록 있으면 한 번 내림 (idempotent)
  launchctl bootout "gui/$UID_NUM/$name" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_NUM" "$dst"
  echo "[install] loaded: $name -> $dst"
done

cat <<EOF

✅ 등록 완료. 로그인 시 자동 실행되고 죽으면 자동 재시작.

콘솔:   ${POCKET_POD_BASE_URL%:8000}:8001
구독:   $POCKET_POD_BASE_URL/feed.xml

상태:   launchctl list | grep pocketpod
로그:   tail -f $HOME_DIR/data/logs/{server,app}.{out,err}.log
중지:   $TPL_DIR/uninstall.sh
EOF
