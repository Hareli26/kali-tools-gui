#!/usr/bin/env python3
"""
🍯 collector — the read-only pull endpoint for honeypot events.

Runs on the SACRIFICIAL host alongside web_pot.py, on a separate port, and does
exactly one thing: hand captured events to production when asked with the right
token. Production polls it; it never calls out.

Why a separate process from web_pot.py:
  The bait and the management channel must not share a process — the same
  principle that keeps classification off this box. web_pot is touched by
  attackers by design; the collector is not. Separating them means they can be
  bound, firewalled and restarted independently, and a wedged bait process
  cannot take the management channel down with it.

Threat model — read carefully, it explains why this is safe:
  * The token protects the event stream from THIRD PARTIES, not from the
    attacker who owns this box. If this host is compromised, the attacker can
    read the token — and it buys them nothing: it only grants read access to
    events they generated themselves.
  * This box holds NO credential to production. Compromising it gives no path
    to kali.dudaei.com. That is the whole point of pulling rather than pushing.
  * Event poisoning is unavoidable and expected — the attacker controls the
    honeypot's input by definition. Production treats everything from here as
    untrusted: separate signature table, never auto-remediated.

Serves:
    GET /events?since=<offset>&limit=<n>   -> {events, next, total}
    GET /health                            -> {ok, events, pot_alive}

Usage:
    HP_TOKEN=<long-random> python3 collector.py
    HP_TOKEN=<...> HP_COL_PORT=8081 HP_COL_BIND=0.0.0.0 python3 collector.py

Generate a token:
    python3 -c "import secrets; print(secrets.token_urlsafe(32))"

Firewall this port to production's IP only. Authorised infrastructure you own.
"""

import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("HP_COL_PORT", "8081"))
BIND = os.environ.get("HP_COL_BIND", "0.0.0.0")
TOKEN = os.environ.get("HP_TOKEN", "")
EVENTS = os.environ.get("HP_EVENTS") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "events.jsonl")

MAX_LIMIT = 2000          # cap per pull, so one request can't drag the whole log


class Collector(BaseHTTPRequestHandler):
    server_version = "collector"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def _authed(self):
        got = self.headers.get("Authorization", "")
        if got.startswith("Bearer "):
            got = got[7:]
        # constant-time: never leak the token through response timing
        return bool(TOKEN) and hmac.compare_digest(got, TOKEN)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path == "/health":
            # Unauthenticated on purpose: liveness only, reveals nothing about
            # what was captured. Production shows this in the pots list.
            n, alive = 0, False
            try:
                st = os.stat(EVENTS)
                alive = (time.time() - st.st_mtime) < 3600
                with open(EVENTS, "rb") as f:
                    n = sum(1 for _ in f)
            except Exception:
                pass
            return self._json(200, {"ok": True, "events": n, "pot_alive": alive})

        if not self._authed():
            return self._json(401, {"error": "unauthorized"})

        if u.path != "/events":
            return self._json(404, {"error": "not found"})

        # `since` is a LINE offset, not a timestamp: the log is append-only, so
        # a line count is a stable cursor and needs no parsing to resume.
        try:
            since = max(0, int(q.get("since", ["0"])[0]))
            limit = min(MAX_LIMIT, max(1, int(q.get("limit", ["500"])[0])))
        except ValueError:
            return self._json(400, {"error": "bad since/limit"})

        out, idx = [], 0
        try:
            with open(EVENTS, encoding="utf-8") as f:
                for idx, line in enumerate(f):
                    if idx < since:
                        continue
                    if len(out) >= limit:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass          # a torn line (mid-write) — skip, don't die
        except FileNotFoundError:
            return self._json(200, {"events": [], "next": 0, "total": 0})
        except Exception as e:
            return self._json(500, {"error": str(e)[:200]})

        return self._json(200, {"events": out, "next": since + len(out),
                                "total": idx + 1})


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if not TOKEN:
        print("FATAL: HP_TOKEN is not set — refusing to serve events unauthenticated.\n"
              "       generate one:  python3 -c \"import secrets; "
              "print(secrets.token_urlsafe(32))\"", file=sys.stderr)
        return 2
    if len(TOKEN) < 20:
        print(f"FATAL: HP_TOKEN is too short ({len(TOKEN)} chars) — use 32+ random chars.",
              file=sys.stderr)
        return 2

    srv = ThreadingHTTPServer((BIND, PORT), Collector)
    srv.daemon_threads = True
    print(f"📡 collector listening on {BIND}:{PORT}")
    print(f"   events <- {EVENTS}")
    print("   firewall this port to the production IP only.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
