#!/bin/bash
# Recommended backend: drive the screen with github.com/zehnm/aoostar-rs (asterctl)
# instead of AOOSTAR's closed-source agent.
#
# installs:  /opt/gem12/asterctl        (downloaded release binary)
#            /opt/gem12/sensors.py      (this repo's tiny sensor writer)
#            /opt/gem12/panels/         (where the web UI drops bg*.jpg + monitor.json)
#            aster-sensors.service, aster-panel.service
#
# usage: sudo ./install-asterctl.sh [version]
set -euo pipefail
VER="${1:-v0.2.0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/gem12

command -v python3 >/dev/null || { echo "python3 required" >&2; exit 1; }

mkdir -p "$DEST/panels" "$DEST/fonts"
cd "$DEST"

if [ ! -x "$DEST/asterctl" ]; then
  echo "== downloading asterctl $VER"
  curl -sL -o asterctl.tar.gz "https://github.com/zehnm/aoostar-rs/releases/download/$VER/asterctl-$VER-Linux-x64.tar.gz"
  curl -sL -o asterctl.hash "https://github.com/zehnm/aoostar-rs/releases/download/$VER/asterctl.hash" || true
  if [ -s asterctl.hash ]; then
    want=$(awk '{print $2}' asterctl.hash)
    have=$(sha256sum asterctl.tar.gz | awk '{print $1}')
    [ "$want" = "$have" ] && echo "   checksum OK" || { echo "   checksum MISMATCH" >&2; exit 1; }
  fi
  tar xzf asterctl.tar.gz
  cp -rn cfg fonts "$DEST"/ 2>/dev/null || true
fi

install -m 755 "$HERE/sensors.py" "$DEST/sensors.py"

# fonts: point at any CJK font you have; asterctl needs the family name used in monitor.json
cat <<'EOF'
NOTE: copy a CJK font (e.g. HarmonyOS_Sans_SC_Bold.ttf or NotoSansCJKbold) into
      /opt/gem12/fonts/ before starting, otherwise CJK labels render as boxes.
EOF

cat > /etc/systemd/system/aster-sensors.service <<EOF
[Unit]
Description=GEM12 sensor writer for asterctl
After=local-fs.target

[Service]
Type=simple
RuntimeDirectory=aster
ExecStart=/usr/bin/python3 $DEST/sensors.py /run/aster/sensors.txt 1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/aster-panel.service <<EOF
[Unit]
Description=GEM12 panel renderer (asterctl)
After=aster-sensors.service
Wants=aster-sensors.service

[Service]
Type=simple
WorkingDirectory=$DEST
ExecStart=$DEST/asterctl --config monitor.json --config-dir $DEST/panels --font-dir $DEST/fonts --sensor-path /run/aster/sensors.txt
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now aster-sensors.service
systemctl enable aster-panel.service

cat <<EOF

Installed. Next:
  1. copy a CJK font into $DEST/fonts/
  2. point the web UI at this box, e.g. in config.json:
     "deploy_cmd": "tar xzf - -C /opt/gem12/panels && systemctl restart aster-panel"
     (the web UI streams \$GEM12_STAGE as a tarball on stdin when started with: tar czf - -C \"\$GEM12_STAGE\" . | <your cmd>)
  3. python3 webui/app.py
EOF
