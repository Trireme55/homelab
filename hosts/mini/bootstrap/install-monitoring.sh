#!/bin/bash
# Run with sudo on the Mac Mini. Installs node_exporter + Uptime Kuma as
# systemd services. Kuma's own npm setup and the node_exporter download are
# expected to be done already, as the normal user, in ~/uptime-kuma and ~/monitoring-setup.
set -euo pipefail

APP_USER="${SUDO_USER:?run this through sudo}"
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"

# --- node_exporter ---
id -u node_exporter &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin node_exporter

install -m 0755 ${APP_HOME}/monitoring-setup/node_exporter-1.12.1.linux-amd64/node_exporter /usr/local/bin/node_exporter

cat > /etc/systemd/system/node_exporter.service <<'EOF'
[Unit]
Description=Prometheus Node Exporter
After=network-online.target
Wants=network-online.target

[Service]
User=node_exporter
Group=node_exporter
ExecStart=/usr/local/bin/node_exporter
Restart=on-failure
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes

[Install]
WantedBy=multi-user.target
EOF

# --- Uptime Kuma ---
cat > /etc/systemd/system/uptime-kuma.service <<EOF
[Unit]
Description=Uptime Kuma
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_HOME}/uptime-kuma
ExecStart=/usr/bin/node server/server.js
Restart=on-failure
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now node_exporter
systemctl enable --now uptime-kuma

sleep 2
echo "=== node_exporter status ==="
systemctl --no-pager status node_exporter | head -5
echo "=== uptime-kuma status ==="
systemctl --no-pager status uptime-kuma | head -5
