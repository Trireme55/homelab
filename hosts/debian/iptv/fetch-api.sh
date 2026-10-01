#!/usr/bin/env bash
# Pull the iptv-org channel database the playlist/guide builders read.
set -euo pipefail
cd "$(dirname "$0")"
for f in channels feeds languages categories; do
  curl -fsSL "https://iptv-org.github.io/api/$f.json" -o "api_$f.json"
done
