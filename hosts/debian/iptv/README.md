# Live TV playlist and guide pipeline

Builds a curated live-TV playlist (M3U) and program guide (XMLTV) for Jellyfin from free public sources: the Free-TV playlist and the iptv-org channel database. Only channels that pass health checks make it into the final playlist.

## How a refresh works

refresh_pipeline.py runs the whole chain, daily on a timer and on demand from a button on the landing page:

1. Fetch the Free-TV playlist and the guide files
2. HTTP test every channel (check.py)
3. Decode test with Jellyfin's own ffmpeg (check_ffmpeg.py)
4. Build the pruned playlist (build_playlist.py)
5. Build one guide for it (build_guide.py)
6. Run sanity checks
7. Deploy to Jellyfin, clear its XMLTV cache, refresh the guide, and verify

Nothing is deployed unless the sanity checks pass, so a failed run leaves the previous playlist and guide live. Progress and the last result are written to status.json, which the landing page reads.

## Scripts

| Script | What it does |
| --- | --- |
| fetch-api.sh | Downloads the iptv-org channel database (the api_*.json files, which are not committed) |
| refresh_pipeline.py | Orchestrates the full refresh described above |
| check.py | Health check: manifest, then media playlist, then first segment bytes |
| check_ffmpeg.py | Second-stage check: decodes real video frames with Jellyfin's ffmpeg |
| build_playlist.py | Writes the pruned, numbered playlist from check results; channel numbers persist across rebuilds |
| build_guide.py | Builds one XMLTV guide, matching by tvg-id, then normalised tvg-id, then channel name; unmatched channels get a placeholder schedule |
| build_candidates.py | Lists English, French and Spanish iptv-org streams not already in the lineup, as candidates to add |
| frame_check.py | Content check for candidates: grabs a few seconds of video and flags black, flat, static or silent streams |
| refresh-web.py | Small endpoint behind the landing page's refresh button |

## Inputs

channel-overrides.json, known-groups.txt, scope-groups.txt and freetv-epg-urls.txt are the selection, naming and guide-source inputs the scripts read. manual-channels.m3u is for hand-added channels and is currently empty.

## Scheduling (systemd/)

| Unit | Role |
| --- | --- |
| guide-refresh.timer | Starts the daily refresh |
| guide-refresh.service | Runs refresh_pipeline.py |
| guide-refresh.path | Starts the service when run/refresh.request appears |
| guide-refresh-web.service | Runs refresh-web.py |

The refresh button never runs a command itself. refresh-web.py listens on 127.0.0.1 only and is exposed to the tailnet through tailscale serve. A POST just creates run/refresh.request, and systemd does the rest, so the web process needs no privileges. Requests are single-flight and rate-limited.

Unit paths assume the repo lives in /opt/homelab and a homelab user exists (see the top-level README).

## Requirements

Python 3 with requests and Pillow, curl, and the Jellyfin container (its ffmpeg is used for the decode checks). Media paths assume the storage disk is mounted at /mnt/storage.
