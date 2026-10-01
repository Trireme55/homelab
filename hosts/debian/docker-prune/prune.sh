#!/bin/bash
# Weekly cleanup of long-exited Docker containers.
# Only removes containers stopped for 72h+, so anything from active use
# (Wolf game sessions that exit between runs, etc.) is never touched.
set -euo pipefail
echo "=== $(date) ==="
docker container prune -f --filter "until=72h"
