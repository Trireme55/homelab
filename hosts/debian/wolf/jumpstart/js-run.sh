#!/bin/bash
# Runs inside the compositor (sway), started by launcher() in startup-app.sh.
# JS_DIR (optional) is a folder under C:\ for games that aren't installed to C:\KA\<JS_GAME>.
if [ -n "${JS_DIR:-}" ]; then
  cd "$WINEPREFIX/drive_c/$JS_DIR"
else
  cd "$WINEPREFIX/drive_c/KA/$JS_GAME"
fi
wine "$JS_EXE"
wineserver -k 2>/dev/null || true
