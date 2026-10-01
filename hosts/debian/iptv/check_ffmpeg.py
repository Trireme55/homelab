#!/usr/bin/env python3
"""Second-stage health check: decode real video frames with Jellyfin's own ffmpeg.

usage: check_ffmpeg.py results.json [container]

check.py's HTTP test follows redirects and counts bytes, which passes streams ffmpeg refuses
(e.g. ad-beacon segment URLs) or that carry no video. Playback in Jellyfin uses ffmpeg, so this
runs the same binary in the same container and only accepts a stream if it decodes video frames.
Adds "ff": "ok" | "fail:<reason>" to every entry whose HTTP result was ok.
"""
import json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

path = sys.argv[1]
container = sys.argv[2] if len(sys.argv) > 2 else "jellyfin"
FFMPEG = "/usr/lib/jellyfin-ffmpeg/ffmpeg"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

entries = json.load(open(path))


def attempt(e, stream_map, frames):
    ua, headers = UA, ""
    for o in e["opts"]:
        if "http-user-agent=" in o:
            ua = o.split("=", 1)[1]
        if "http-referrer=" in o and o.split("=", 1)[1]:
            headers = "Referer: %s\r\n" % o.split("=", 1)[1]
    cmd = ["docker", "exec", container, FFMPEG, "-nostdin", "-loglevel", "error", "-rw_timeout", "20000000",
           "-user_agent", ua]
    if headers:
        cmd += ["-headers", headers]
    cmd += ["-i", e["url"], "-map", stream_map] + frames + ["-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    err = r.stderr or ""
    if r.returncode == 0 and "does not contain any stream" not in err:
        return True, ""
    if "allowed_segment_extensions" in err:
        return False, "hls segment extension not allowed"
    lines = [l for l in err.strip().splitlines() if l.strip()]
    return False, (lines[-1] if lines else "exit %d" % r.returncode)[:90]


def run(e):
    ok, why = attempt(e, "0:v:0", ["-frames:v", "3"])
    if not ok and why == "timeout":
        ok, why = attempt(e, "0:v:0", ["-frames:v", "3"])  # one retry for slow starts
    if ok:
        return "ok"
    if "Invalid argument" in why or "matches no streams" in why or "Stream map" in why:
        ok2, _ = attempt(e, "0:a:0", ["-t", "5"])  # audio-only (radio)
        if ok2:
            return "ok-audio"
    return "fail:" + why


todo = [e for e in entries if e["result"].startswith("ok") and "ff" not in e]
print("ffmpeg-testing %d channels in %s" % (len(todo), container), flush=True)
with ThreadPoolExecutor(10) as ex:
    for e, r in zip(todo, ex.map(run, todo)):
        e["ff"] = r
json.dump(entries, open(path, "w"), indent=1)
from collections import Counter
print(Counter(e["ff"] if e["ff"].startswith("ok") else e["ff"][:60] for e in todo))
