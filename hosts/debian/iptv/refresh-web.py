#!/usr/bin/env python3
"""Tiny "refresh the Live TV guide" endpoint for the landing page.

Listens on 127.0.0.1 only; exposed to the tailnet (only) via `tailscale serve --set-path /guide-refresh`.
GET shows the last result and a confirm page; POST asks for a rebuild by creating run/refresh.request.
systemd (guide-refresh.path) sees that file and starts guide-refresh.service, so this process needs no
privileges and no user input ever reaches a command. Single-flight (the pipeline holds a lock) and
rate-limited.
"""
import fcntl
import json
import os
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8097
HERE = os.path.dirname(os.path.abspath(__file__))
REQUEST = os.path.join(HERE, "run", "refresh.request")
LOCK = os.path.join(HERE, "run", "pipeline.lock")
STATUS = os.path.join(HERE, "status.json")
COOLDOWN = 1800  # seconds between requests

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Refresh the Live TV guide</title>
<link rel="stylesheet" href="/style.css">
</head>
<body>
<div class="wrap">
  <header>
    <h1>Refresh the Live TV guide</h1>
    <p class="subtitle">Rebuild the channel list and schedule now</p>
  </header>
  <section>
    <div class="grid" style="grid-template-columns: 1fr;">
      <div class="card">
        <div class="card-header"><h3>{title}</h3></div>
        {body}
      </div>
    </div>
  </section>
  <p class="subtitle"><a href="/jellyfin/">&larr; Back to the Jellyfin guide</a></p>
  <footer>debian &middot; tailnet only</footer>
</div>
</body>
</html>
"""

WHY = """<p>The Live TV channel list and guide rebuild <strong>automatically every day at about 4:30 am</strong>.
Use this button only if something looks wrong before then. Good reasons:</p>
<ul>
<li>The guide is empty, or channels show "No program information".</li>
<li>Several channels won't play or show a black screen (a stream died and hasn't been dropped yet).</li>
<li>A channel that should be there is missing, or a working one disappeared.</li>
</ul>
<p>What it does: re-downloads the channel list and schedules, tests every stream, drops the ones that don't play,
rebuilds the guide and reloads it into Jellyfin. It takes <strong>about 10 to 15 minutes</strong>. Live TV keeps
working while it runs, but the channel list may flicker at the end. If the rebuild fails it changes nothing.
It can be run at most once every 30 minutes.</p>"""


def read_status():
    try:
        return json.load(open(STATUS))
    except Exception:
        return {}


def running():
    """True while the pipeline holds its lock (or a request is waiting to start)."""
    if os.path.exists(REQUEST):
        return True
    try:
        f = open(LOCK, "w")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
        return False
    except BlockingIOError:
        return True
    except OSError:
        return False


def pretty(ts):
    try:
        return datetime.fromisoformat(ts).strftime("%a %b %-d, %-I:%M %p")
    except Exception:
        return "never"


def status_html():
    st = read_status()
    if running():
        return ("<p><strong>A rebuild is running now</strong> (%s). Check back in a few minutes.</p>"
                % (st.get("step") or "starting"))
    if not st.get("finished"):
        return "<p>No rebuild has been recorded yet.</p>"
    mark = "&#10003;" if st.get("ok") else "&#10007;"
    return "<p>Last rebuild: <strong>%s</strong> %s<br>%s</p>" % (pretty(st["finished"]), mark, st.get("message", ""))


def confirm_html():
    return status_html() + WHY + (
        '<form method="post" action=""><button type="submit" style="font-size:1rem;padding:.6em 1.2em;">'
        "Rebuild the guide now</button></form>")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, title, body):
        data = PAGE.format(title=title, body=body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, "Rebuild the guide?", confirm_html())

    def do_POST(self):
        who = self.headers.get("Tailscale-User-Login", "unknown")
        if running():
            print(f"refresh refused (already running) for {who}", flush=True)
            self._send(409, "Already running", "<p>A rebuild is already running. " + status_html() + "</p>")
            return
        st = read_status()
        try:
            started = datetime.fromisoformat(st["started"]).timestamp()
        except Exception:
            started = 0
        wait = COOLDOWN - (time.time() - started)
        if wait > 0:
            print(f"refresh refused (cooldown) for {who}", flush=True)
            self._send(429, "Too soon", "<p>The guide was rebuilt a short while ago. Please wait about "
                       f"{int(wait // 60) + 1} minutes before asking again.</p>" + status_html())
            return
        print(f"refresh requested by {who}", flush=True)
        with open(REQUEST, "w") as f:
            f.write("%s %s\n" % (datetime.now().isoformat(timespec="seconds"), who))
        self._send(202, "Rebuilding&hellip;",
                   "<p>Started. It takes about 10 to 15 minutes. You don't need to keep this page open: "
                   "reload it later to see the result, or just check the guide in Jellyfin.</p>")

    def log_message(self, fmt, *args):
        pass  # requests are printed explicitly above


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
