# homelab

Configs and scripts for the three machines in my house that run media, game
streaming and monitoring. Everything is Docker Compose where possible and
plain systemd/bash where not. Secrets are never committed: every service that
needs some has a `.env.example` next to its compose file.

| Host | What it is | What runs on it |
|---|---|---|
| `debian` | Desktop PC, SSD + big HDD, AMD GPU plus Intel iGPU | Wolf (game streaming), Jellyfin, Sonarr/Radarr, qBittorrent, Immich, NordVPN exit nodes, Samba, monitoring |
| `evergreen` | Small desktop, NVMe + 2 TB HDD, Intel iGPU | File hub (Samba + File Browser), Windows VMs under QEMU/KVM, second Wolf, monitoring |
| `mini` | Mac mini running Debian | Uptime Kuma and node_exporter, installed natively |

All three are on the same Tailscale tailnet. Most services bind to loopback and
the tailnet address only, and are reached over Tailscale.

## Layout

```
hosts/
  debian/
    bootstrap/      first-boot scripts: Docker + Wolf prerequisites, firewall/fail2ban/crowdsec, smartd
    wolf/           Wolf compose file and the JumpStart (Wine) app image
    jellyfin/ sonarr/ radarr/ qbittorrent/ immich/
    nord-exit/ nord-exit-uk/   Tailscale exit nodes that leave through NordVPN
    monitoring/     Prometheus, Loki, Alloy, Grafana (provisioned dashboards + alerts)
    uptime-kuma/ samba/ docker-prune/ systemd/
    iptv/           Live TV playlist + guide builder for Jellyfin
  evergreen/        filehub/, monitoring/, samba/, win11/ (VM snapshot helper), wolf/
  mini/             bootstrap/ (node_exporter + Kuma units, power-on-after-outage unit)
docs/               how the pieces fit together
```

## Using it

Nothing here is a one-command install. The usual routine on a host:

```sh
git clone <this repo> /opt/homelab
cd /opt/homelab/hosts/debian/jellyfin
cp .env.example .env && $EDITOR .env
docker compose up -d
```

`hosts/debian/bootstrap/install.sh` does the Docker + Wolf groundwork on a fresh
Debian 13 install; read it before running it, it edits apt sources.

Paths in the systemd units assume the repo lives in `/opt/homelab` and that a
`homelab` user exists (in the `docker` group where a unit talks to Docker).
Media and bulk data live on a separate disk mounted at `/mnt/storage`; see
[docs/architecture.md](docs/architecture.md) for why compose files refuse to
start without it.

## Notes

- Image tags are pinned to specific versions (set October 2026), except Wolf and its JumpStart base image, which follow the project's `stable` and `edge` channels. To upgrade, change the tag on purpose, then run `docker compose pull && docker compose up -d` in that service's folder.
- The Grafana alert contact point reads its Telegram token from the
  environment. See `hosts/debian/monitoring/.env.example`.
