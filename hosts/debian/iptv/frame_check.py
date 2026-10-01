#!/usr/bin/env python3
"""Content check for candidates: grab ~14s of a stream with host ffmpeg and judge the pictures.
usage: frame_check.py results.json [threads]   (adds "frames": {...} and "fc": verdict)
Verdicts: ok | black | flat (solid colour) | static (identical frames = still image/slate) | silent
| novideo | fail:<why>.  A thumbnail is saved to candidates/thumbs/<n>.jpg; frames' perceptual hashes
are compared afterwards so many channels sharing one picture (a shutdown slate) are flagged 'slate'."""
import json, re, subprocess, sys, os, hashlib, collections, threading
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
here = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1]; threads = int(sys.argv[2]) if len(sys.argv) > 2 else 12
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
W, H = 64, 36
ents = json.load(open(path))

def grab(i, e):
    ua, hdr = UA, []
    for o in e["opts"]:
        if "http-user-agent=" in o: ua = o.split("=", 1)[1]
        if "http-referrer=" in o and o.split("=", 1)[1]: hdr = ["-headers", "Referer: %s\r\n" % o.split("=", 1)[1]]
    thumb = os.path.join(here, "candidates", "thumbs", "%d.jpg" % i)
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "info", "-rw_timeout", "15000000", "-user_agent", ua] + hdr + \
          ["-t", "14", "-i", e["url"],
           "-map", "0:v:0", "-vf", "fps=1/3.5,scale=%d:%d,format=gray" % (W, H), "-f", "rawvideo", "pipe:1",
           "-map", "0:v:0", "-vf", "fps=1/7,scale=320:-2", "-frames:v", "2", "-update", "1", "-y", thumb,
           "-map", "0:a:0?", "-af", "volumedetect", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=70)
    except subprocess.TimeoutExpired:
        return {"fc": "fail:timeout"}
    raw = r.stdout; n = len(raw) // (W * H)
    err = r.stderr.decode("utf-8", "replace")
    if n == 0:
        why = [l for l in err.splitlines() if l.strip()]
        return {"fc": "novideo" if "Stream map" in err or "matches no streams" in err else "fail:" + (why[-1][:70] if why else "nodata")}
    fr = [raw[k * W * H:(k + 1) * W * H] for k in range(n)]
    def mean(b): return sum(b) / len(b)
    def std(b):
        m = mean(b); return (sum((x - m) ** 2 for x in b) / len(b)) ** .5
    means = [mean(f) for f in fr]; stds = [std(f) for f in fr]
    diffs = [sum(abs(a - b) for a, b in zip(fr[k], fr[k + 1])) / (W * H) for k in range(n - 1)]
    m = re.search(r"mean_volume: (-?[\d.]+) dB", err)
    vol = float(m.group(1)) if m else None
    ph = hashlib.md5(bytes(x >> 5 for x in fr[-1][::7])).hexdigest()[:10]  # coarse hash of last frame
    out = {"n": n, "bright": round(max(means)), "std": round(max(stds), 1),
           "motion": round(max(diffs), 2) if diffs else None, "vol": vol, "hash": ph}
    if max(means) < 14: out["fc"] = "black"
    elif max(stds) < 5: out["fc"] = "flat"
    elif n >= 3 and max(diffs) < 0.6: out["fc"] = "static"
    elif vol is not None and vol < -80: out["fc"] = "silent"
    else: out["fc"] = "ok"
    return out

todo = [(i, e) for i, e in enumerate(ents) if e["result"].startswith("ok")]
# checkpoint: every result is appended to <results>.ckpt as it lands, so a killed run resumes where it stopped
ckpt = path + ".ckpt"
cache = {}
if os.path.exists(ckpt):
    for line in open(ckpt):
        try: d = json.loads(line); cache[d["i"]] = d["r"]
        except Exception: pass
lock = threading.Lock()
def work(t):
    i, e = t
    if i in cache: return cache[i]
    r = grab(i, e)
    with lock:
        open(ckpt, "a").write(json.dumps({"i": i, "r": r}) + "\n")
    return r
print("frame-checking %d streams (%d already in checkpoint)" % (len(todo), len(cache)), flush=True)
done = 0
with ThreadPoolExecutor(threads) as ex:
    for (i, e), r in zip(todo, ex.map(work, todo)):
        e["frames"] = r; e["fc"] = r["fc"]; e["thumb"] = i
        done += 1
        if done % 100 == 0: print(done, flush=True)
# many different channels showing the very same picture = a slate, not content
chans = collections.defaultdict(set)
for _, e in todo:
    if e["fc"] in ("ok", "slate"): chans[e["frames"]["hash"]].add(e["tvgid"].split("@")[0])
for _, e in todo:
    if e["fc"] in ("ok", "slate"):
        e["fc"] = "slate" if len(chans[e["frames"]["hash"]]) >= 3 else "ok"
json.dump(ents, open(path, "w"), indent=1)
print(collections.Counter(e["fc"].split(":")[0] for _, e in todo))
