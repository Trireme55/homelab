# How it fits together

## Network

Tailscale connects the hosts and my phones/laptops. Service ports are published
as `127.0.0.1:PORT` plus `${TS_IP}:PORT` (the host's tailnet address), so
only a few things are reachable from the LAN (Wolf/Moonlight, SSH and a couple of
web UIs, see `bootstrap/setup-security.sh`). Some services are additionally put on HTTPS
with `tailscale serve`.

## VPN containers

Two separate uses of [Gluetun](https://github.com/qdm12/gluetun) with a NordVPN
WireGuard profile:

- **qBittorrent** has no network of its own (`network_mode: service:gluetun`).
  If the tunnel drops, Gluetun's firewall drops everything, so there is no leak.
  Sonarr and Radarr join the same compose network so they can reach the web UI at
  the hostname `gluetun`.
- **Exit nodes** (`nord-exit`, `nord-exit-uk`): a Tailscale container shares
  Gluetun's network namespace and advertises itself as an exit node. A device
  opts in by picking it as its exit node. Two `ip rule`s are needed inside the
  namespace so that replies to tailnet addresses go back out `tailscale0`
  instead of into the VPN tunnel, and so tailscaled's own packets take the
  normal home route (otherwise peers fall back to DERP relays). The
  `iptables/post-rules.txt` files let Gluetun's default-drop firewall forward
  between `tailscale0` and `tun0`.
- `nord-exit-uk/reset-server.py` is a tiny localhost-only HTTP endpoint that
  restarts the UK pair to pick a new server. It runs one fixed action and takes
  no input.

## Storage

Bulk data is on an HDD at `/mnt/storage`. Two things keep containers from
quietly writing to the SSD when that mount is missing at boot:

- `systemd/docker-wait-for-storage.conf` is a drop-in that makes
  `docker.service` wait for the mount.
- The Prometheus/Loki bind mounts set `create_host_path: false`, so the
  container fails to start instead of creating the directory on the SSD.

## Monitoring

Each of `debian` and `evergreen` runs its own Prometheus, Loki, Alloy, Grafana,
cAdvisor and node_exporter. node_exporter listens on the monitoring bridge
gateway only, so Prometheus can scrape it and the LAN can't. Alloy ships the
journal and all container logs (including short-lived Wolf session containers) to
Loki. Alert rules cover disk usage, memory, and a sudden drop in free space,
and go out through a Telegram contact point.

Uptime Kuma runs on `debian` and `mini`, each watching the other, so one box
going down gets noticed by the other.

## Live TV

`hosts/debian/iptv` builds a curated M3U playlist and XMLTV guide for Jellyfin
from the Free-TV playlist and iptv-org's database. A daily timer runs the
pipeline: fetch, test each stream over HTTP, decode a few frames with the same
ffmpeg Jellyfin uses, build playlist and guide, and only deploy if sanity
checks pass. Run `iptv/fetch-api.sh` once to download the iptv-org data files
before the first run.

## Game streaming

[Wolf](https://games-on-whales.github.io/wolf/stable/) streams games to
Moonlight clients. On `debian` it is pinned to the discrete GPU
(`WOLF_RENDER_NODE`), and per-profile game data lives on the HDD. `wolf/jumpstart`
is a 32-bit Wine image used to run old CD-ROM games as Wolf apps.
