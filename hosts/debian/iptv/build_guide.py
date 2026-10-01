#!/usr/bin/env python3
"""Build one XMLTV guide for pruned.m3u from the downloaded epg/*.xml.gz sources.

usage: build_guide.py pruned.m3u guide.xml

Matching per playlist channel: exact tvg-id, then normalised tvg-id (country suffix and
HD/East/West tags stripped), then normalised channel name. A candidate only counts if it has
programmes in the window. Channels with no real listings get a placeholder schedule
(3-hour blocks titled with the channel name) so they still show in the guide grid.
Also gives channels with an empty tvg-id a unique one (edits the m3u in place).
"""
import gzip, os, re, sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

m3u, out = sys.argv[1:3]
here = os.path.dirname(os.path.abspath(__file__))
EPG = os.path.join(here, "epg")
# source priority order (first match wins within a tier)
SOURCES = ["epg_US2", "epg_UK1", "epg_AU1", "epg_CA2", "epg_IE1", "epg_ES1", "epg_FR1",
           "epg_DISTROTV1", "mjh_pluto_us", "mjh_pluto_gb", "epg_US_LOCALS1"]
NOW = datetime.now(timezone.utc)
WIN_START, WIN_END = NOW - timedelta(hours=6), NOW + timedelta(days=7)
FILL_END = NOW + timedelta(days=15)  # generic blocks run this far so a channel is never blank between weekly rebuilds


def filler(tid, name, chno, start, end, desc):
    """3-hour generic programme blocks from start (aligned to 3h) to end."""
    out = []
    a = start.replace(minute=0, second=0, microsecond=0)
    a -= timedelta(hours=a.hour % 3)
    while a < end:
        out.append('  <programme start="%s" stop="%s" channel="%s">\n    <title>%s</title>\n%s'
                   '    <desc>%s</desc>\n  </programme>\n'
                   % (fmt(a), fmt(a + timedelta(hours=3)), escape(tid, {'"': "&quot;"}),
                      escape(clean(name).strip()), cat_xml(chno), desc))
        a += timedelta(hours=3)
    return out


def clean(s):
    return re.sub(r"[ⒼⓈⓎⒹⓄ]", "", s)


def norm_id(s):
    s = s.lower().replace("&", "and")
    s = re.sub(r"\.(us2?|uk|es|fr|ie|ca|au|com|tv|in|ng|gh|kr|jp|sg|ru|tr|it|de|cg|qa)$", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return re.sub(r"(hdeast|hdwest|east|west|hd|stream|sd)+$", "", s)


def norm_name(s):
    s = clean(s).lower().replace("&", "and")
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return re.sub(r"(hd|uk|us)+$", "", s)


def parse_time(t):
    t = t.strip()
    m = re.match(r"(\d{14})\s*([+-]\d{4})?", t)
    if not m:
        return None
    dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    off = m.group(2) or "+0000"
    sign = 1 if off[0] == "+" else -1
    dt = dt - sign * timedelta(hours=int(off[1:3]), minutes=int(off[3:5]))
    return dt.replace(tzinfo=timezone.utc)


def fmt(dt):
    return dt.strftime("%Y%m%d%H%M%S +0000")


def open_src(name):
    return gzip.open(os.path.join(EPG, name + ".xml.gz"), "rb")


import json
GENRE_CATEGORY = {"news": "News", "kids": "Kids", "movies": "Movie", "music": "Music",
                  "doc": "Documentary", "sports": "Sports"}
_gpath = os.path.join(here, "channel-genres.json")
GENRES = json.load(open(_gpath)) if os.path.exists(_gpath) else {}


def cat_xml(chno):
    c = GENRE_CATEGORY.get(GENRES.get(str(chno), {}).get("genre"))
    return "    <category>%s</category>\n" % c if c else ""


# ---- playlist ----------------------------------------------------------------------------
lines = open(m3u, encoding="utf-8").read().split("\n")
chans = []
used_ids = set()
for i, l in enumerate(lines):
    if not l.startswith("#EXTINF"):
        continue
    tid = (re.search(r'tvg-id="([^"]*)"', l) or [None, ""])[1]
    chno = re.search(r'tvg-chno="(\d+)"', l).group(1)
    name = l.split(",", 1)[-1].strip()
    if not tid:
        tid = "curated-%s" % chno
        if 'tvg-id=""' in l:
            l = l.replace('tvg-id=""', 'tvg-id="%s"' % tid, 1)
        else:
            l = l.replace("#EXTINF:-1", '#EXTINF:-1 tvg-id="%s"' % tid, 1)
        lines[i] = l
    chans.append({"line": i, "tid": tid, "name": name, "chno": chno})
    used_ids.add(tid)

# ---- pass 1: index guide channels --------------------------------------------------------
idx_exact, idx_base, idx_name = defaultdict(list), defaultdict(list), defaultdict(list)
src_channels = {}
for s in SOURCES:
    if not os.path.exists(os.path.join(EPG, s + ".xml.gz")):
        continue
    ids = {}
    for ev, el in ET.iterparse(open_src(s), events=("end",)):
        if el.tag == "channel":
            cid = el.get("id")
            names = [d.text or "" for d in el.findall("display-name")]
            ids[cid] = names
            idx_exact[cid.lower()].append((s, cid))
            idx_base[norm_id(cid)].append((s, cid))
            for n in names:
                if n:
                    idx_name[norm_name(n)].append((s, cid))
            el.clear()
        elif el.tag == "programme":
            break
    src_channels[s] = ids
    print("indexed %-16s %5d channels" % (s, len(ids)), file=sys.stderr)

SRC_COUNTRY = {"epg_US2": "us", "epg_US_LOCALS1": "us", "mjh_pluto_us": "us", "epg_UK1": "uk",
               "mjh_pluto_gb": "uk", "epg_AU1": "au", "epg_CA2": "ca", "epg_IE1": "ie", "epg_ES1": "es",
               "epg_FR1": "fr", "epg_DISTROTV1": "us"}
# channels whose name-match is known wrong (show/other channel with the same name) -> placeholder
NO_GUIDE = {"Heartland"}
# playlist tvg-id -> (source, guide id) where automatic matching picks the wrong language/feed
OVERRIDE = {"France24English.fr": ("epg_FR1", "France.24.Anglais.fr")}


def tid_country(tid):
    m = re.search(r"\.(\w+)$", tid.lower())
    return {"us2": "us"}.get(m.group(1), m.group(1)) if m else ""


cands = {}
for c in chans:
    lst = []
    if c["name"] in NO_GUIDE:
        cands[c["tid"]] = lst
        continue
    want_country = tid_country(c["tid"])
    if c["tid"] in OVERRIDE:
        lst.append((OVERRIDE[c["tid"]], "manual"))
    for tier, idx, key in (("id", idx_exact, c["tid"].lower()), ("base", idx_base, norm_id(c["tid"])),
                           ("name", idx_name, norm_name(c["name"]))):
        if key:
            pairs = sorted(idx.get(key, [])[:8], key=lambda p: SRC_COUNTRY.get(p[0]) != want_country)
            for pair in pairs[:3]:
                if (pair, tier) not in [(p, t) for p, t in lst] and pair not in [p for p, _ in lst]:
                    lst.append((pair, tier))
    cands[c["tid"]] = lst

# ---- pass 2: programmes for candidate (source, id) pairs ---------------------------------
want = defaultdict(set)
for lst in cands.values():
    for (s, cid), _ in lst:
        want[s].add(cid)
progs = defaultdict(list)  # (source, id) -> [(start, stop, title, desc)]
for s, ids in want.items():
    for ev, el in ET.iterparse(open_src(s), events=("end",)):
        if el.tag == "programme":
            cid = el.get("channel")
            if cid in ids:
                a, b = parse_time(el.get("start", "")), parse_time(el.get("stop", ""))
                if a and b and b > WIN_START and a < WIN_END:
                    t = el.find("title")
                    d = el.find("desc")
                    progs[(s, cid)].append((a, b, (t.text if t is not None else "") or "",
                                            (d.text if d is not None else "") or ""))
            el.clear()
        elif el.tag == "channel":
            el.clear()

# ---- choose + write ----------------------------------------------------------------------
stats = defaultdict(int)
written = {}
matchlog = []
with open(out, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="curated-iptv">\n')
    body = []
    for c in chans:
        if c["tid"] in written:
            continue
        pick = next(((p, t) for p, t in cands[c["tid"]] if len(progs.get(p, [])) >= 4), None)
        f.write('  <channel id="%s">\n    <display-name>%s</display-name>\n    <display-name>%s</display-name>\n  </channel>\n'
                % (escape(c["tid"], {'"': "&quot;"}), escape(clean(c["name"]).strip()), c["chno"]))
        if pick:
            (s, cid), tier = pick
            stats["real:" + tier] += 1
            first = sorted(progs[(s, cid)])[0][2]
            matchlog.append("%s\t%s\t%s\t%s\t%s\t%s" % (tier, c["chno"], clean(c["name"]).strip(), s, cid, first))
            written[c["tid"]] = "real"
            for a, b, title, desc in sorted(progs[(s, cid)]):
                body.append('  <programme start="%s" stop="%s" channel="%s">\n    <title>%s</title>\n%s%s  </programme>\n'
                            % (fmt(a), fmt(b), escape(c["tid"], {'"': "&quot;"}), escape(title or clean(c["name"])),
                               cat_xml(c["chno"]), ("    <desc>%s</desc>\n" % escape(desc)) if desc else ""))
            last_stop = max(b for _, b, _, _ in progs[(s, cid)])
            body += filler(c["tid"], c["name"], c["chno"], last_stop, FILL_END,
                           "Live stream. No further schedule is published yet.")
        else:
            stats["placeholder"] += 1
            written[c["tid"]] = "placeholder"
            body += filler(c["tid"], c["name"], c["chno"], NOW - timedelta(hours=6), FILL_END,
                           "Live stream. No schedule is published for this channel.")
    f.write("".join(body))
    f.write("</tv>\n")

open(m3u, "w", encoding="utf-8").write("\n".join(lines))
open(os.path.join(here, "guide-matches.tsv"), "w", encoding="utf-8").write(
    "tier\tchno\tplaylist name\tsource\tguide id\tfirst programme\n" + "\n".join(matchlog) + "\n")
print("channels: %d  real guide: %d  placeholder: %d" % (len(written), sum(v == "real" for v in written.values()),
                                                         sum(v == "placeholder" for v in written.values())))
print({k: v for k, v in sorted(stats.items())})
print("wrote", out, "%.1f MB" % (os.path.getsize(out) / 1e6))
