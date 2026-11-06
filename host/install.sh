#!/bin/bash
# Install the AOOSTAR-X agent as a systemd service and add a boot-time
# config guard, so a reboot never brings back the black screen or the
# vendor dashboard.
#
# Usage:  sudo ./install.sh [/root/AOOSTAR-X-linux] [switch_seconds]
set -euo pipefail

SRC_DIR="${1:-/root/AOOSTAR-X-linux}"
SWITCH="${2:-60}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ ! -x "$SRC_DIR/AOOSTAR-X" ]; then
  echo "AOOSTAR-X not found at $SRC_DIR (pass the directory as \$1)" >&2
  exit 1
fi

install -d /usr/local/lib/gem12
install -m 755 "$HERE/fix_config.py" /usr/local/lib/gem12/fix_config.py

cat > /etc/systemd/system/aoostar-x-service.service <<EOF
[Unit]
Description=AOOSTAR-X sub-screen agent
After=network.target

[Service]
Type=simple
ExecStart=$SRC_DIR/AOOSTAR-X
WorkingDirectory=$SRC_DIR
Restart=always
RestartSec=5
StandardError=file:$SRC_DIR/monitor3_error.log

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/gem12-screen-fix.service <<EOF
[Unit]
Description=GEM12 sub-screen config guard
Before=aoostar-x-service.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 /usr/local/lib/gem12/fix_config.py --dir $SRC_DIR --switch $SWITCH

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable gem12-screen-fix.service
systemctl enable aoostar-x-service.service
systemctl restart gem12-screen-fix.service
systemctl restart aoostar-x-service.service
sleep 4
systemctl --no-pager --lines=0 status gem12-screen-fix.service aoostar-x-service.service || true

echo
echo "Agent UI:  http://127.0.0.1:5123  (vendor factory default — change it)"
echo "Next:      run webui/ on any box that can reach port 5123"
