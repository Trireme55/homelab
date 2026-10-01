#!/usr/bin/env python3
"""Write a pruned, numbered m3u from check.py results (working channels only).

usage: build_playlist.py results.json guide-matches.json out.m3u

- Channels with a matched guide entry get their tvg-id rewritten to the guide's real id.
- Language + genre come from the iptv-org API (api_channels.json / api_feeds.json), falling
  back to Free-TV's group-title and finally to name keywords.
- tvg-chno is assigned in blocks (see LAYOUT). Numbers persist in channel-numbers.json so a
  channel keeps its number across rebuilds; dead channels keep their number reserved.
"""
import json, re, sys, os
from collections import defaultdict

res, matches, out = sys.argv[1:4]
here = os.path.dirname(os.path.abspath(__file__))
NUMFILE = os.path.join(here, "channel-numbers.json")

# ---- layout ------------------------------------------------------------------------------
# English: 100-wide genre blocks; first half (x00-x49) US, second half (x50-x99) UK/IE/CA/AU/other.
EN_GENRE = {"news": 100, "movies": 200, "kids": 300, "music": 400, "doc": 500,
            "general": 600, "other": 700, "sports": 800, "radio": 900}
# Non-English: language base + 25-wide genre slots.
LANG_BASE = {"spa": 1000, "fra": 1200, "other": 1500}
# (offset, size) inside a language block; radio shares the music slot
LANG_GENRE = {"news": (0, 40), "movies": (40, 20), "kids": (60, 20), "music": (80, 20), "radio": (80, 20),
              "doc": (100, 20), "general": (120, 60), "other": (180, 10), "sports": (190, 10)}

CAT_TO_GENRE = {}
for g, cats in {
    "kids": "kids animation family",
    "news": "news weather business legislative",
    "movies": "movies classic series comedy",
    "music": "music",
    "doc": "documentary education science travel outdoor culture cooking lifestyle",
    "sports": "sports",
    "other": "shop religious auto",
    "general": "general entertainment public interactive relax",
}.items():
    for c in cats.split():
        CAT_TO_GENRE[c] = g
GENRE_ORDER = ["kids", "news", "movies", "music", "doc", "sports", "other", "general"]
GROUP_GENRE = {"News": "news", "News (ES)": "news", "News (AR)": "news", "VOD Movies (EN)": "movies",
               "Music (EN)": "music", "Documentaries (EN)": "doc", "Weather": "news", "Business": "news"}
GROUP_LANG = {"UK": "eng", "USA": "eng", "Ireland": "eng", "Canada": "eng", "Australia": "eng",
              "VOD Movies (EN)": "eng", "Music (EN)": "eng", "Documentaries (EN)": "eng",
              "Spain": "spa", "News (ES)": "spa", "France": "fra"}
KEYWORDS = [("kids", r"kids|junior|cartoon|disney|nick|toon|gulli|clan|baby|boomerang|cbeebies|cbbc"),
            ("news", r"news|noticias|info\b|24h|24/7 news|euronews|cnn|bbc world|sky news"),
            ("movies", r"movie|cine|film|cinema|classic|retro|sitcom"),
            ("music", r"music|radio|mtv|hits"),
            ("sports", r"sport|deporte|futbol|football")]

OVR = json.load(open(os.path.join(here, "channel-overrides.json"))) if os.path.exists(
    os.path.join(here, "channel-overrides.json")) else {}
RADIO_RX = r"\bradio\b|\bfm\b|\d\s?fm\b|fm\d"
SUFFIX_LANG = {"us": "eng", "us2": "eng", "uk": "eng", "ie": "eng", "ca": "eng", "au": "eng", "za": "eng",
               "in": "eng", "ng": "eng", "gh": "eng", "sg": "eng", "es": "spa", "fr": "fra"}


def override(e):
    plain = re.sub(r"[ⒼⓈⓎⒹⓄ]", "", e["name"]).strip()
    return OVR.get(e["tvgid"]) or OVR.get(plain) or {}


channels = {c["id"]: c for c in json.load(open(os.path.join(here, "api_channels.json")))}
feeds = defaultdict(list)
for f in json.load(open(os.path.join(here, "api_feeds.json"))):
    feeds[f["channel"]].append(f)


def api_id(tvgid):
    return tvgid.split("@")[0]


def language(e):
    if "lang" in override(e):
        return override(e)["lang"]
    fl = feeds.get(api_id(e["tvgid"]))
    if fl:
        main = next((f for f in fl if f.get("is_main")), fl[0])
        langs = main.get("languages") or []
        if langs:  # the first language is the real one; English etc. are often listed as an extra
            return langs[0] if langs[0] in ("eng", "spa", "fra") else "other"
    suffix = e["tvgid"].lower().rsplit(".", 1)[-1] if "." in e["tvgid"] else ""
    return GROUP_LANG.get(e["group"]) or SUFFIX_LANG.get(suffix, "other")


def genre_reason(e):
    if "genre" in override(e):
        return override(e)["genre"], "override"
    if re.search(RADIO_RX, e["name"].lower()):
        return "radio", "name:radio"
    ch = channels.get(api_id(e["tvgid"]))
    cats = (ch or {}).get("categories") or []
    for g in GENRE_ORDER:
        if any(CAT_TO_GENRE.get(c) == g for c in cats):
            return g, "api:" + ",".join(cats)
    if e["group"] in GROUP_GENRE:
        return GROUP_GENRE[e["group"]], "group:" + e["group"]
    name = e["name"].lower()
    for g, rx in KEYWORDS:
        if re.search(rx, name):
            return g, "name"
    return "general", "default"


def genre(e):
    return genre_reason(e)[0]


def is_us(e):
    return e["tvgid"].lower().endswith(".us") or e["group"] == "USA"


def slot(e):
    """Return (block_start, block_size) for a channel."""
    lang, gen = language(e), genre(e)
    if lang == "eng":
        base = EN_GENRE[gen] + (0 if is_us(e) else 50)
        return base, 50
    off, size = LANG_GENRE[gen]
    return LANG_BASE[lang] + off, size


guide = {e["url"]: e["guide"][1] for e in json.load(open(matches))["have"]}
# Hosts that pass the health check but only ever show a shutdown/landing slate (real video, no content).
# Pluto's stitcher plays a looping "no longer available on this device, visit pluto.tv/where-to-watch"
# animation (verified by capturing frames 2026-09-28).
EXCLUDE_GROUPS = set()  # scope is by LANGUAGE (eng/spa/fra) only, not by country
BLOCK_URL_RX = r"service-stitcher\.clusters\.pluto\.tv"

good = []
seen = set()
blocked = []
for e in json.load(open(res)):
    if not e["result"].startswith("ok") or not e.get("ff", "ok").startswith("ok"):
        continue
    if re.search(BLOCK_URL_RX, e["url"]):
        blocked.append(e)
        continue
    # scope: English / Spanish / French only; these tested groups are available but not wanted (yet)
    if e["group"] in EXCLUDE_GROUPS or language(e) not in ("eng", "spa", "fra"):
        continue
    k = e["tvgid"] or e["name"]
    if k in seen:  # same channel listed twice (backup feed): keep the first working stream, one number each
        continue
    seen.add(k)
    good.append(e)

nums = json.load(open(NUMFILE)) if os.path.exists(NUMFILE) else {}
for e in blocked:  # free the numbers of purged channels
    nums.pop(e["tvgid"] or e["name"], None)
if blocked:
    print("blocked %d landing-page channels (Pluto stitcher)" % len(blocked))
used = set(nums.values())


def key(e):
    return e["tvgid"] or e["name"]


for e in sorted(good, key=lambda x: x["name"].lower()):
    e["_slot"] = slot(e)
    k = key(e)
    start, size = e["_slot"]
    if k in nums:
        if start <= nums[k] < start + size:
            continue
        used.discard(nums[k])  # genre/language changed: move the channel into its new block
        del nums[k]
    n = next((n for n in range(start, start + size) if n not in used), None)
    if n is None:  # block full: spill into the next free number after it
        n = next(n for n in range(start + size, 10000) if n not in used)
        print("WARN: block %d full, %s -> %d" % (start, e["name"], n), file=sys.stderr)
    nums[k] = n
    used.add(n)

json.dump(nums, open(NUMFILE, "w"), indent=1, sort_keys=True)
json.dump({str(nums[key(e)]): {"genre": genre(e), "lang": language(e)} for e in good},
          open(os.path.join(here, "channel-genres.json"), "w"), indent=1, sort_keys=True)

good.sort(key=lambda e: nums[key(e)])
with open(out, "w", encoding="utf-8") as f:
    f.write("#EXTM3U\n")
    for e in good:
        inf = e["inf"]
        inf = re.sub(r'\s*tvg-chno="[^"]*"', "", inf)
        inf = inf.replace("#EXTINF:-1", '#EXTINF:-1 tvg-chno="%d"' % nums[key(e)], 1)
        f.write(inf + "\n")
        for o in e["opts"]:
            f.write(o + "\n")
        f.write(e["url"] + "\n")

with open(os.path.join(here, "channel-classification.tsv"), "w", encoding="utf-8") as f:
    f.write("chno\tname\tlang\tgenre\treason\tfree-tv group\n")
    for e in good:
        g, why = genre_reason(e)
        f.write("%d\t%s\t%s\t%s\t%s\t%s\n" % (nums[key(e)], e["name"], language(e), g, why, e["group"]))
print("wrote %d working channels (%d with guide ids) to %s" % (len(good), sum(e["url"] in guide for e in good), out))
tally = defaultdict(int)
for e in good:
    tally[(language(e), genre(e), "US" if language(e) == "eng" and is_us(e) else "")] += 1
for (l, g, u), n in sorted(tally.items()):
    print("  %-5s %-8s %-3s %d" % (l, g, u, n))
