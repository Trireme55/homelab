#!/usr/bin/env python3
"""Tiny single-purpose "reset UK-exit" endpoint for the landing page.

Listens on 127.0.0.1 only; exposed to the tailnet (only) via `tailscale serve --set-path /reset-uk`.
GET shows a confirm page, POST restarts the UK exit node (a fresh Nord London server = new IP).
Runs exactly one fixed action - no user input ever reaches a command. Rate-limited, single-flight.
Gluetun is restarted first, then tailscale-exit-uk, because Tailscale shares Gluetun's network namespace
and would otherwise be left attached to a dead one.
"""
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8095
COOLDOWN = 120  # seconds between resets
GLUETUN = "gluetun-exit-uk"
TAILSCALE = "tailscale-exit-uk"

lock = threading.Lock()
last_reset = 0.0

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Reset UK-exit</title>
<link rel="stylesheet" href="/style.css">
</head>
<body>
<div class="wrap">
  <header>
    <h1>Reset UK-exit</h1>
    <p class="subtitle">Get a different London server</p>
  </header>
  <section>
    <div class="grid" style="grid-template-columns: 1fr;">
      <div class="card">
        <div class="card-header"><h3>{title}</h3></div>
        {body}
      </div>
    </div>
  </section>
  <p class="subtitle"><a href="/tailscale/">&larr; Back to the setup guide</a></p>
  <footer>tailnet only</footer>
</div>
</body>
</html>
"""

CONFIRM = """<p>This restarts the <strong>UK-exit</strong> node so it connects to a different NordVPN server in London,
which gives it a new IP address. Try it if a site refuses to load.</p>
<p>Anyone using UK-exit will lose their internet for about a minute. Afterwards, turn the exit node off and on
again in the Tailscale app if it doesn't reconnect by itself.</p>
<form method="post" action=""><button type="submit" style="font-size:1rem;padding:.6em 1.2em;">Reset UK-exit</button></form>"""


def restart():
    subprocess.run(["docker", "restart", GLUETUN], check=False, timeout=120)
    for _ in range(45):  # wait up to ~90s for Gluetun's healthcheck
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", GLUETUN],
            capture_output=True, text=True,
        ).stdout.strip()
        if out == "healthy":
            break
        time.sleep(2)
    subprocess.run(["docker", "restart", TAILSCALE], check=False, timeout=60)
    print("reset finished", flush=True)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, title, body):
        data = PAGE.format(title=title, body=body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, "Are you sure?", CONFIRM)

    def do_POST(self):
        global last_reset
        who = self.headers.get("Tailscale-User-Login", "unknown")
        with lock:
            wait = COOLDOWN - (time.time() - last_reset)
            if wait > 0:
                print(f"reset refused (cooldown) for {who}", flush=True)
                self._send(429, "Too soon",
                           f"<p>UK-exit was reset a moment ago. Please wait about {int(wait)} seconds before trying again.</p>")
                return
            last_reset = time.time()
        print(f"reset requested by {who}", flush=True)
        threading.Thread(target=restart, daemon=True).start()
        self._send(202, "Resetting&hellip;",
                   "<p>UK-exit is restarting and will pick a new London server. Give it about a minute, "
                   "then turn the exit node off and on again in the Tailscale app.</p>")

    def log_message(self, fmt, *args):
        pass  # request lines are printed explicitly above


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
