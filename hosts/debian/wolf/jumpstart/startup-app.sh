#!/bin/bash
set -e
source /opt/gow/bash-lib/utils.sh
source /opt/gow/launch-comp.sh

# Wolf sets JS_GAME (folder name, e.g. 4G) and JS_EXE (file name, e.g. 4G.EXE).
: "${JS_GAME:?JS_GAME not set}"
: "${JS_EXE:?JS_EXE not set}"

export WINEPREFIX="$HOME/prefix"

# Each paired client gets its own copy of the pre-installed prefix the first
# time it launches, so saves are per client and two people can play at once.
if [ ! -d "$WINEPREFIX/drive_c" ]; then
  gow_log "First launch for this client: copying Wine prefix (~650 MB)"
  cp -a /template "$WINEPREFIX"
fi

# The game checks for its CD in D:. Point it at the read-only disc mount.
ln -sfn /disc "$WINEPREFIX/dosdevices/d:"
wine reg add 'HKLM\Software\Wine\Drives' /v 'd:' /d cdrom /f >/dev/null 2>&1 || true

launcher /usr/local/bin/js-run
