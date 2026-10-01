#!/usr/bin/env bash
# Installs Docker Engine (official Debian repo), Wolf host prerequisites,
# then starts Wolf and Jellyfin. Run with:  sudo bash hosts/debian/bootstrap/install.sh
# Needs Tailscale to be up already (Jellyfin is published on the tailnet address).
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo"; exit 1; }
USER_NAME="${SUDO_USER:?run this through sudo, not as a root login}"
BASE="$(cd "$(dirname "$0")/.." && pwd)"   # hosts/debian

echo "== 0/5 apt sources (replace install-DVD source with Debian mirrors)"
if ! grep -qE '^deb .*deb\.debian\.org' /etc/apt/sources.list; then
  cp /etc/apt/sources.list /etc/apt/sources.list.bak
  sed -i 's/^deb cdrom:/#deb cdrom:/' /etc/apt/sources.list
  cat >> /etc/apt/sources.list <<EOF

deb https://deb.debian.org/debian trixie main contrib non-free-firmware
deb https://deb.debian.org/debian trixie-updates main contrib non-free-firmware
deb https://security.debian.org/debian-security trixie-security main contrib non-free-firmware
EOF
fi

echo "== 1/5 Docker Engine + Compose plugin"
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
# NOTE: docker group membership is root-equivalent. Remove this line if you'd
# rather keep using sudo for docker.
usermod -aG docker "$USER_NAME"

echo "== 2/5 Wolf host prerequisites (uinput/uhid + udev rules)"
modprobe uinput
modprobe uhid
printf 'uinput\nuhid\n' > /etc/modules-load.d/wolf.conf
curl -fsSL https://raw.githubusercontent.com/games-on-whales/wolf/stable/85-wolf.rules \
  -o /etc/udev/rules.d/85-wolf.rules
udevadm control --reload-rules
udevadm trigger
mkdir -p /etc/wolf

echo "== 3/5 Media directory for Jellyfin"
mkdir -p /srv/media
chown "$USER_NAME":"$USER_NAME" /srv/media

echo "== 4/5 Jellyfin GPU group IDs"
TS_IP="$(tailscale ip -4 | head -n1)"
cat > "$BASE/jellyfin/.env" <<EOF
TS_IP=${TS_IP}
RENDER_GID=$(getent group render | cut -d: -f3)
VIDEO_GID=$(getent group video | cut -d: -f3)
EOF
chown "$USER_NAME":"$USER_NAME" "$BASE/jellyfin/.env"

echo "== 5/5 Start Wolf and Jellyfin"
docker compose -f "$BASE/wolf/compose.yaml" up -d
docker compose -f "$BASE/jellyfin/compose.yaml" --env-file "$BASE/jellyfin/.env" up -d

echo
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
echo
echo "Done. Log out/in (or run 'newgrp docker') so '$USER_NAME' can use docker without sudo."
echo "Wolf logs:     docker logs -f wolf   (pairing PIN link appears here when a client connects)"
echo "Jellyfin:      http://$(hostname -I | awk '{print $1}'):8096"
