#!/usr/bin/env bash
# Installs and configures: ufw, fail2ban, crowdsec (+ nftables bouncer), clamav, lynis,
# plus supporting packages (unattended-upgrades, needrestart, auditd, debsums).
# Wazuh is left out on purpose; it is too heavy for this box.
#
# Run with:  sudo bash hosts/debian/bootstrap/setup-security.sh
# ufw is configured but NOT enabled unless you run it with ENABLE_UFW=1 (sudo ENABLE_UFW=1 bash ...).
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo"; exit 1; }
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a   # never prompt about restarting services during apt runs

LAN="${LAN:-192.168.1.0/24}"   # your home subnet
TS="100.64.0.0/10"          # Tailscale CGNAT range
CS_PORT=8081                # CrowdSec local API; default 8080 is taken by qBittorrent

echo "== 1/7 Base packages + dependencies"
apt-get update
apt-get install -y ca-certificates curl gnupg \
  ufw fail2ban python3-systemd \
  clamav clamav-freshclam clamav-daemon \
  lynis \
  unattended-upgrades apt-listchanges needrestart auditd debsums

echo "== 2/7 Automatic security updates (no automatic reboot)"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo "== 3/7 ufw rules (SSH/mosh from LAN + Tailscale, service ports from LAN)"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0 comment 'Tailscale'
ufw allow from "$LAN" to any port 22 proto tcp comment 'SSH LAN'
ufw allow from "$LAN" to any port 60000:61000 proto udp comment 'mosh LAN'
ufw allow from "$LAN" to any port 8096 proto tcp comment 'Jellyfin'
ufw allow from "$LAN" to any port 3001 proto tcp comment 'Uptime Kuma'
# qBittorrent: WebUI is published only on localhost and Tailscale (covered by the tailscale0 rule); no peer port (NordVPN has no port forwarding).
ufw allow from "$LAN" to any port 47984,47989,48010 proto tcp comment 'Wolf/Moonlight'
ufw allow from "$LAN" to any port 47998,47999,48000,48100,48200 proto udp comment 'Wolf/Moonlight'
if [ "${ENABLE_UFW:-0}" = "1" ]; then
  ufw --force enable
else
  echo "   ufw rules staged but firewall left DISABLED. Enable with ENABLE_UFW=1."
fi

echo "== 4/7 fail2ban (sshd jail, systemd backend, never bans LAN/Tailscale)"
cat > /etc/fail2ban/jail.local <<EOF
[DEFAULT]
backend  = systemd
bantime  = 1h
findtime = 10m
maxretry = 5
ignoreip = 127.0.0.1/8 ::1 $LAN $TS

[sshd]
enabled = true
EOF
systemctl enable fail2ban
systemctl restart fail2ban

echo "== 5/7 ClamAV (signatures first, then daemon; weekly scan of downloads)"
systemctl stop clamav-freshclam || true
freshclam
systemctl enable --now clamav-freshclam clamav-daemon
cat > /etc/systemd/system/clamav-weekly-scan.service <<'EOF'
[Unit]
Description=ClamAV weekly scan of downloads
After=clamav-daemon.service

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'mkdir -p /mnt/storage/media/downloads; clamdscan --fdpass --infected --multiscan --log=/var/log/clamav/weekly-scan.log /mnt/storage/media/downloads || [ $? -eq 1 ]'
EOF
cat > /etc/systemd/system/clamav-weekly-scan.timer <<'EOF'
[Unit]
Description=Weekly ClamAV scan

[Timer]
OnCalendar=Sun 04:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now clamav-weekly-scan.timer

echo "== 6/7 CrowdSec (official repo; Debian's copy is old and lacks the nftables bouncer)"
if ! apt-cache policy crowdsec-firewall-bouncer-nftables | grep -q 'Candidate: [0-9]'; then
  TMP="$(mktemp)"
  curl -fsSL https://install.crowdsec.net -o "$TMP"
  sh "$TMP"
  rm -f "$TMP"
  apt-get update
fi
# Block service start during install so we can move the API off port 8080 first.
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod +x /usr/sbin/policy-rc.d
apt-get install -y crowdsec
sed -i "s#127.0.0.1:8080#127.0.0.1:${CS_PORT}#" /etc/crowdsec/config.yaml /etc/crowdsec/local_api_credentials.yaml
apt-get install -y crowdsec-firewall-bouncer-nftables
sed -i "s#127.0.0.1:8080#127.0.0.1:${CS_PORT}#" /etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml
rm -f /usr/sbin/policy-rc.d
systemctl enable --now crowdsec
systemctl enable --now crowdsec-firewall-bouncer

echo "== 7/7 Lynis baseline audit"
lynis audit system --quick --no-colors > /var/log/lynis-baseline.txt 2>&1 || true
grep -E 'Hardening index|Tests performed|Warnings' /var/log/lynis-baseline.txt || true

echo
echo "-- Service status"
systemctl is-active fail2ban clamav-daemon clamav-freshclam crowdsec crowdsec-firewall-bouncer auditd || true
echo "-- ufw"
ufw status verbose | head -5
echo
echo "Lynis suggestions:  sudo grep -E 'Suggestion|Warning' /var/log/lynis-report.dat"
echo "CrowdSec:           sudo cscli metrics ; sudo cscli decisions list"
