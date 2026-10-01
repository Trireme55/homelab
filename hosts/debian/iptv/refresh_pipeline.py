#!/usr/bin/env python3
"""Rebuild the Jellyfin Live TV playlist + guide end to end. Runs daily (guide-refresh.timer) and on demand
(landing page button -> run/refresh.request -> guide-refresh.path).

Steps: fetch Free-TV playlist -> fetch guide files -> HTTP test -> ffmpeg test -> build playlist -> build
guide -> sanity checks -> deploy to Jellyfin -> clear Jellyfin's XMLTV cache -> Refresh Guide -> verify.

Nothing is deployed unless the sanity checks pass; on any failure the previous playlist and guide stay live.
Progress and the last result are written to status.json (the landing page reads it).
"""
import fcntl, gzip, json, os, re, shutil, subprocess, sys, time, traceback, urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
LOGDIR = os.path.join(HERE, "logs")
RUNDIR = os.path.join(HERE, "run")
STATUS = os.path.join(HERE, "status.json")
JF_DIR = "/mnt/storage/jellyfin/config/iptv"
JF = "http://127.0.0.1:8096"
FREETV = "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlist.m3u8"
EPG = {  # local name -> url (epgshare01 renames files now and then; a failed download keeps the old copy)
    "epg_US2": "https://epgshare01.online/epgshare01/epg_ripper_US2.xml.gz",
    "epg_UK1": "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz",
    "epg_AU1": "https://epgshare01.online/epgshare01/epg_ripper_AU1.xml.gz",
    "epg_CA2": "https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz",
    "epg_IE1": "https://epgshare01.online/epgshare01/epg_ripper_IE1.xml.gz",
    "epg_ES1": "https://epgshare01.online/epgshare01/epg_ripper_ES1.xml.gz",
    "epg_FR1": "https://epgshare01.online/epgshare01/epg_ripper_FR1.xml.gz",
    "epg_DISTROTV1": "https://epgshare01.online/epgshare01/epg_ripper_DISTROTV1.xml.gz",
    "mjh_pluto_us": "https://i.mjh.nz/PlutoTV/us.xml.gz",
    "mjh_pluto_gb": "https://i.mjh.nz/PlutoTV/gb.xml.gz",
}
MIN_KEEP = 0.80       # abort if the new playlist has fewer than this fraction of the last one's channels
MIN_REAL_KEEP = 0.60  # ... or real-guide channels (a guide download problem shows up here)
GRACE_MISSES = 1      # a channel that worked before may fail this many consecutive runs before it's dropped

os.makedirs(WORK, exist_ok=True)
os.makedirs(LOGDIR, exist_ok=True)
os.makedirs(RUNDIR, exist_ok=True)
os.makedirs(os.path.join(HERE, "backup", "last-good"), exist_ok=True)
os.makedirs(os.path.join(HERE, "epg"), exist_ok=True)

stamp = datetime.now().strftime("%Y%m%d-%H%M")
logpath = os.path.join(LOGDIR, "refresh-%s.log" % stamp)
logf = open(logpath, "a", buffering=1)


def log(msg):
    line = "%s  %s" % (datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    logf.write(line + "\n")


def read_status():
    try:
        return json.load(open(STATUS))
    except Exception:
        return {}


def write_status(**kw):
    st = read_status()
    st.update(kw)
    tmp = STATUS + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1)
    os.replace(tmp, STATUS)


def step(name):
    log("== " + name)
    write_status(step=name)


def run(cmd, timeout, **kw):
    log("$ " + " ".join(cmd)[:200])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=HERE, **kw)
    for l in (r.stdout or "").strip().splitlines()[-12:]:
        log("   " + l[:220])
    if r.returncode != 0:
        for l in (r.stderr or "").strip().splitlines()[-8:]:
            log("   ! " + l[:220])
        raise RuntimeError("%s failed (exit %d)" % (cmd[1] if len(cmd) > 1 else cmd[0], r.returncode))
    return r.stdout or ""


def fetch(url, dest, min_bytes, is_gzip=False):
    """Download to dest; keep the old file if the new one looks wrong. Returns True if updated."""
    tmp = dest + ".new"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        if os.path.getsize(tmp) < min_bytes:
            raise ValueError("only %d bytes" % os.path.getsize(tmp))
        if is_gzip:
            with gzip.open(tmp, "rb") as g:
                while g.read(1 << 20):
                    pass
        os.replace(tmp, dest)
        return True
    except Exception as e:
        log("   download failed for %s: %s (keeping previous copy: %s)" % (url, e, os.path.exists(dest)))
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


def count_channels(path):
    try:
        return sum(1 for l in open(path, encoding="utf-8") if l.startswith("#EXTINF"))
    except FileNotFoundError:
        return 0


def jf_key():
    return open(os.path.expanduser("~/.config/jellyfin/api_key")).read().strip()


def jf(path, method="GET", timeout=30):
    req = urllib.request.Request(JF + path, method=method,
                                 headers={"Authorization": 'MediaBrowser Token="%s"' % jf_key()})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else None


def main():
    started = time.time()
    write_status(state="running", started=datetime.now().isoformat(timespec="seconds"), step="starting",
                 ok=None, message="", log=os.path.basename(logpath))
    prev_count = count_channels(os.path.join(HERE, "pruned.m3u"))
    prev_real = read_status().get("real_guide", 0)

    # 1. sources
    step("fetch Free-TV playlist")
    src = os.path.join(WORK, "freetv.m3u8")
    if not fetch(FREETV, src, 200000):
        if not os.path.exists(src):
            raise RuntimeError("cannot fetch the Free-TV playlist and there is no previous copy")
    if count_channels(src) < 1500:
        raise RuntimeError("Free-TV playlist has only %d entries, expected 1500+" % count_channels(src))

    # hand-added channels (manual-channels.m3u) ride along with Free-TV so they get the same tests
    combined = os.path.join(WORK, "combined.m3u8")
    with open(combined, "w", encoding="utf-8") as out_f:
        out_f.write(open(src, encoding="utf-8", errors="replace").read().rstrip("\n") + "\n")
        out_f.write("".join(l for l in open(os.path.join(HERE, "manual-channels.m3u"), encoding="utf-8")
                            if not l.startswith("#EXTM3U")))
    src = combined

    step("fetch guide files")
    for name, url in EPG.items():
        ok = fetch(url, os.path.join(HERE, "epg", name + ".xml.gz"), 10000, is_gzip=True)
        log("   %-14s %s" % (name, "updated" if ok else "kept old"))

    # 2. which groups to test: the ones with English/Spanish/French channels, plus any group new since last run
    groups = [g for g in open(os.path.join(HERE, "scope-groups.txt"), encoding="utf-8").read().splitlines() if g]
    groups.append("Manual")
    known = set(open(os.path.join(HERE, "known-groups.txt"), encoding="utf-8").read().splitlines())
    seen = []
    for l in open(src, encoding="utf-8", errors="replace"):
        m = re.search(r'group-title="([^"]*)"', l)
        if l.startswith("#EXTINF") and m and m.group(1) not in seen:
            seen.append(m.group(1))
    new = [g for g in seen if g not in known]
    if new:
        log("new groups this run (will be tested): %s" % ", ".join(new))
    step("test streams (HTTP)")
    results = os.path.join(WORK, "results.json")
    run([sys.executable, "check.py", src, results, "|".join(groups + new)], timeout=1800)
    step("test streams (ffmpeg)")
    run([sys.executable, "check_ffmpeg.py", results], timeout=2400)

    # 3. grace: a channel in the live playlist that fails once keeps its place for GRACE_MISSES runs
    live_urls = {l.strip() for l in open(os.path.join(HERE, "pruned.m3u"), encoding="utf-8") if l.startswith("http")}
    misses = read_status().get("misses", {})
    data = json.load(open(results))
    kept = 0
    for e in data:
        good = e["result"].startswith("ok") and e.get("ff", "ok").startswith("ok")
        if good:
            misses.pop(e["url"], None)
        elif e["url"] in live_urls:
            misses[e["url"]] = misses.get(e["url"], 0) + 1
            if misses[e["url"]] <= GRACE_MISSES:
                e["result"], e["ff"] = "ok", "ok"
                kept += 1
    misses = {u: n for u, n in misses.items() if u in live_urls}
    json.dump(data, open(results, "w"), indent=1)
    if kept:
        log("grace: kept %d channel(s) that failed once" % kept)

    # 4. build
    step("build playlist")
    pl = os.path.join(WORK, "pruned.m3u")
    run([sys.executable, "build_playlist.py", results, "guide-matches.json", pl], timeout=300)
    step("build guide")
    gd = os.path.join(WORK, "guide.xml")
    out = run([sys.executable, "build_guide.py", pl, gd], timeout=600)
    m = re.search(r"channels: (\d+)\s+real guide: (\d+)\s+placeholder: (\d+)", out)
    if not m:
        raise RuntimeError("build_guide.py gave no summary line")
    n_total, n_real, n_ph = map(int, m.groups())

    # 5. sanity checks (nothing below is touched if these fail)
    step("sanity checks")
    n_new = count_channels(pl)
    log("channels: %d now vs %d live; real-guide %d vs %d" % (n_new, prev_count, n_real, prev_real))
    if prev_count and n_new < MIN_KEEP * prev_count:
        raise RuntimeError("new playlist has %d channels vs %d live (< %d%%); keeping the live one. "
                           "Probably a network problem during testing." % (n_new, prev_count, MIN_KEEP * 100))
    if prev_real and n_real < MIN_REAL_KEEP * prev_real:
        raise RuntimeError("only %d channels matched real guide data vs %d before; keeping the live guide. "
                           "Probably a guide download problem." % (n_real, prev_real))
    import xml.etree.ElementTree as ET
    root = ET.parse(gd).getroot()
    if len(root.findall("programme")) < 1000:
        raise RuntimeError("guide.xml has almost no programmes")

    # 6. deploy
    step("deploy")
    for f in ("pruned.m3u", "guide.xml"):
        if os.path.exists(os.path.join(HERE, f)):
            shutil.copy2(os.path.join(HERE, f), os.path.join(HERE, "backup", "last-good", f))
    shutil.copy2(pl, os.path.join(HERE, "pruned.m3u"))
    shutil.copy2(gd, os.path.join(HERE, "guide.xml"))
    os.makedirs(JF_DIR, exist_ok=True)
    shutil.copy2(pl, os.path.join(JF_DIR, "pruned.m3u"))
    shutil.copy2(gd, os.path.join(JF_DIR, "guide.xml"))
    # Jellyfin keeps its own copy of the guide file and does not re-read ours unless that copy is gone
    run(["docker", "exec", "jellyfin", "sh", "-c", "rm -f /cache/xmltv/*.xml"], timeout=60)

    step("Jellyfin: Refresh Guide")
    task = next(t["Id"] for t in jf("/ScheduledTasks") if t["Key"] == "RefreshGuide")
    jf("/ScheduledTasks/Running/%s" % task, method="POST")
    time.sleep(8)
    deadline = time.time() + 2400
    while time.time() < deadline:
        time.sleep(10)
        try:
            state = jf("/ScheduledTasks/%s" % task)
        except Exception as e:
            log("   (Jellyfin busy: %s)" % e)
            continue
        write_status(step="Jellyfin: Refresh Guide (%d%%)" % round(state.get("CurrentProgressPercentage") or 0))
        if state["State"] == "Idle":
            break
    else:
        raise RuntimeError("Jellyfin's Refresh Guide did not finish within 40 minutes")

    # 7. verify what Jellyfin actually shows
    step("verify")
    uid = jf("/Users")[0]["Id"]
    chans = jf("/LiveTv/Channels?Limit=2000&UserId=%s&AddCurrentProgram=true" % uid, timeout=120)["Items"]
    no_prog = [c["Name"] for c in chans if not c.get("CurrentProgram")]
    log("Jellyfin shows %d channels; %d without a current programme" % (len(chans), len(no_prog)))
    if no_prog:
        log("   without programme: %s" % ", ".join(no_prog[:15]))
    write_status(state="idle", step="done", ok=True, finished=datetime.now().isoformat(timespec="seconds"),
                 message="OK: %d channels in Jellyfin, %d with real listings, %d with generic blocks; %d without a "
                         "current programme." % (len(chans), n_real, n_ph, len(no_prog)),
                 channels=n_new, jellyfin_channels=len(chans), real_guide=n_real, placeholder=n_ph,
                 no_programme=len(no_prog), misses=misses, seconds=round(time.time() - started))
    # remember groups so a newly appearing one is tested once, then treated as known
    with open(os.path.join(HERE, "known-groups.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(seen) + "\n")


if __name__ == "__main__":
    lock = open(os.path.join(RUNDIR, "pipeline.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another refresh is already running; exiting")
        sys.exit(0)
    try:
        main()
        # keep two weeks of logs
        for f in sorted(os.listdir(LOGDIR))[:-14]:
            os.remove(os.path.join(LOGDIR, f))
    except Exception as e:
        log("FAILED: %s" % e)
        log(traceback.format_exc())
        write_status(state="idle", step="failed", ok=False, finished=datetime.now().isoformat(timespec="seconds"),
                     message="FAILED: %s. The previous playlist and guide are still in use." % e)
        sys.exit(1)
