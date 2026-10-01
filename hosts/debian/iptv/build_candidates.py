#!/usr/bin/env python3
"""Build candidates/candidates.m3u: every iptv-org stream in English/French/Spanish that is not
already in the live lineup. Sorted English first. Group-title = language so check.py can filter.
usage: build_candidates.py streams.json out.m3u"""
import json, re, sys, os, collections
here = os.path.dirname(os.path.abspath(__file__))
st = json.load(open(sys.argv[1]))
ch = {c["id"]: c for c in json.load(open(os.path.join(here, "api_channels.json")))}
fd = collections.defaultdict(dict)
for f in json.load(open(os.path.join(here, "api_feeds.json"))):
    fd[f["channel"]][f["id"]] = f
live = {l.strip() for l in open(os.path.join(here, "pruned.m3u"), encoding="utf-8") if l.startswith("http")}
BLOCK = re.compile(r"service-stitcher\.clusters\.pluto\.tv")
G = {"eng": "English", "fra": "French", "spa": "Spanish"}
rows, seen = [], set()
for s in st:
    c = ch.get(s.get("channel"))
    if not c or c.get("closed") or c.get("is_nsfw") or s["url"] in live or s["url"] in seen or BLOCK.search(s["url"]):
        continue
    feeds = fd[c["id"]]
    f = feeds.get(s.get("feed")) or next((x for x in feeds.values() if x.get("is_main")), None) or next(iter(feeds.values()), None)
    langs = (f or {}).get("languages") or []
    if not langs or langs[0] not in G:
        continue
    seen.add(s["url"])
    cats = ",".join(c.get("categories") or []) or "general"
    tid = c["id"] + ("@" + s["feed"] if s.get("feed") else "")
    name = s.get("title") or c["name"]
    rows.append((list(G).index(langs[0]), cats, name, tid, c["country"], G[langs[0]], s))
rows.sort(key=lambda r: (r[0], r[1], r[2].lower()))
with open(sys.argv[2], "w", encoding="utf-8") as o:
    o.write("#EXTM3U\n")
    for _, cats, name, tid, country, grp, s in rows:
        o.write('#EXTINF:-1 tvg-id="%s" tvg-name="%s" tvg-country="%s" tvg-cats="%s" group-title="%s",%s\n'
                % (tid, name.replace('"', "'"), country or "", cats, grp, name))
        if s.get("referrer"): o.write("#EXTVLCOPT:http-referrer=%s\n" % s["referrer"])
        if s.get("user_agent"): o.write("#EXTVLCOPT:http-user-agent=%s\n" % s["user_agent"])
        o.write(s["url"] + "\n")
print(collections.Counter(r[5] for r in rows))
