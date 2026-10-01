#!/usr/bin/env python3
"""Health-check m3u entries: manifest -> media playlist -> first segment bytes."""
import re, sys, json, requests
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor

src, out = sys.argv[1], sys.argv[2]
groups = set(sys.argv[3].split("|"))
proxy = sys.argv[4] if len(sys.argv) > 4 else None
proxies = {"http": proxy, "https": proxy} if proxy else None

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

def parse(path):
    ents, cur = [], None
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if line.startswith("#EXTINF"):
            cur = {"inf": line, "opts": []}
            m = re.search(r'group-title="([^"]*)"', line)
            cur["group"] = m.group(1) if m else ""
            m = re.search(r'tvg-id="([^"]*)"', line)
            cur["tvgid"] = m.group(1) if m else ""
            cur["name"] = line.split(",", 1)[-1].strip()
        elif cur is not None and line.startswith("#EXTVLCOPT"):
            cur["opts"].append(line)
        elif cur is not None and line and not line.startswith("#"):
            cur["url"] = line.strip()
            ents.append(cur)
            cur = None
    return ents

def headers_for(e):
    h = {"User-Agent": UA}
    for o in e["opts"]:
        if "http-referrer=" in o: h["Referer"] = o.split("=", 1)[1]
        if "http-user-agent=" in o: h["User-Agent"] = o.split("=", 1)[1]
    return h

def check(e):
    h = headers_for(e)
    url = e["url"]
    try:
        r = requests.get(url, headers=h, timeout=12, proxies=proxies, allow_redirects=True, stream=True)
        if r.status_code != 200:
            return "http_%d" % r.status_code
        body = r.raw.read(400000, decode_content=True)
        r.close()
        txt = body.decode("utf-8", "replace")
        base = r.url
        if "#EXTM3U" not in txt:
            # a web page (e.g. a YouTube /live URL) is not a stream, however many bytes it has
            if txt.lstrip()[:15].lower().startswith(("<!doctype", "<html")) or "text/html" in r.headers.get("content-type", ""):
                return "html_page"
            # progressive stream (ts/mp4/mp3): got bytes?
            return "ok_direct" if len(body) > 20000 else "short_body"
        for _ in range(2):  # master -> media
            lines = [l.strip() for l in txt.splitlines()]
            if any(l.startswith("#EXT-X-STREAM-INF") for l in lines):
                nxt = next((l for i, l in enumerate(lines) if l and not l.startswith("#") and lines[i-1].startswith("#EXT-X-STREAM-INF")), None)
                if not nxt: return "no_variant"
                base = urljoin(base, nxt)
                r = requests.get(base, headers=h, timeout=12, proxies=proxies)
                if r.status_code != 200: return "variant_http_%d" % r.status_code
                txt = r.text
            else:
                break
        segs = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith("#")]
        if not segs: return "no_segments"
        seg = urljoin(base, segs[-1])  # newest segment
        r = requests.get(seg, headers=h, timeout=15, proxies=proxies, stream=True)
        if r.status_code != 200: return "seg_http_%d" % r.status_code
        data = r.raw.read(150000)
        r.close()
        return "ok" if len(data) > 20000 else "seg_short"
    except requests.exceptions.Timeout:
        return "timeout"
    except requests.exceptions.SSLError:
        return "ssl"
    except requests.exceptions.ConnectionError as ex:
        return "conn_err"
    except Exception as ex:
        return "err_" + type(ex).__name__

ents = [e for e in parse(src) if e["group"] in groups]
print("testing", len(ents), "channels", "via", proxy or "direct", flush=True)
with ThreadPoolExecutor(24) as ex:
    res = list(ex.map(check, ents))
for e, r in zip(ents, res): e["result"] = r
json.dump(ents, open(out, "w"), indent=1)
from collections import Counter
print(Counter(r for r in res))
print("by group (ok/total):")
for g in sorted(groups):
    t = [e for e in ents if e["group"] == g]
    print("  %-22s %d/%d" % (g, sum(e["result"].startswith("ok") for e in t), len(t)))
