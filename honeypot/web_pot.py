#!/usr/bin/env python3
"""
🍯 web_pot — low-interaction web honeypot.

Runs on the SACRIFICIAL host (never on the production box). Serves a plausible
fake company site laced with bait, and appends every request to a JSONL event
log. The production Kali GUI *pulls* that log and does the thinking.

Design rules — deliberately dumb, because this process is internet-exposed:
  * NEVER executes anything. No shell, no eval, no subprocess, no file writes
    outside the append-only event log. Every response is a canned string.
  * NO real database. The "SQL" endpoint returns hard-coded fake rows and
    hard-coded fake error text. There is no engine to inject into.
  * NO classification. Raw capture only; ATTACK_KB analysis happens on the
    production box, so a compromise here cannot poison the analyser.
  * NO secrets. Every credential served as bait is fake and worthless.
  * Bounded. Request bodies, headers and the event log are all capped, so a
    flood cannot exhaust disk or RAM.

Everything a visitor sees is theatre. There is no real data behind any of it.

Usage:
    python3 web_pot.py                       # 0.0.0.0:8080, events -> ./events.jsonl
    HP_PORT=80 HP_EVENTS=/var/log/pot.jsonl python3 web_pot.py

Authorised deception on infrastructure you own. Do not point this at anyone else.
"""

import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote_plus, urlparse

# ------------------------------------------------------------------ config ---
PORT = int(os.environ.get("HP_PORT", "8080"))
BIND = os.environ.get("HP_BIND", "0.0.0.0")
EVENTS = os.environ.get("HP_EVENTS") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "events.jsonl")
SITE = os.environ.get("HP_SITE", "Dudaei Logistics Ltd")

MAX_BODY = 64 * 1024          # bytes read from any request body
MAX_FIELD = 2048              # per captured header/field
MAX_EVENTS_BYTES = 64 * 1024 * 1024   # rotate the log past this
_LOCK = threading.Lock()

# ------------------------------------------------------------ event logging --
def log_event(ev):
    """Append one event as JSON to the log. Best-effort: never raise upward."""
    try:
        with _LOCK:
            if os.path.exists(EVENTS) and os.path.getsize(EVENTS) > MAX_EVENTS_BYTES:
                os.replace(EVENTS, EVENTS + ".1")     # single-generation rotate
            with open(EVENTS, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass   # a honeypot that crashes on a bad write is a honeypot that's down


def _clip(s, n=MAX_FIELD):
    s = str(s)
    return s if len(s) <= n else s[:n] + "…[truncated]"


# ------------------------------------------------------------- fake content --
# All names/emails/keys below are invented. Nothing here is real.
FAKE_USERS = [
    {"id": 1, "user": "a.cohen",  "email": "a.cohen@dudaei-logistics.test",  "role": "admin",   "dept": "IT"},
    {"id": 2, "user": "m.levi",   "email": "m.levi@dudaei-logistics.test",   "role": "manager", "dept": "Ops"},
    {"id": 3, "user": "r.mizrahi", "email": "r.mizrahi@dudaei-logistics.test", "role": "user",  "dept": "Sales"},
    {"id": 4, "user": "s.katz",   "email": "s.katz@dudaei-logistics.test",   "role": "user",    "dept": "Finance"},
]

FAKE_ENV = """APP_NAME=dudaei-portal
APP_ENV=production
APP_DEBUG=false
APP_KEY=base64:R0FLRV9LRVlfTk9UX1JFQUxfSE9ORVlQT1RfQkFJVA==
DB_CONNECTION=mysql
DB_HOST=10.0.4.17
DB_PORT=3306
DB_DATABASE=portal_prod
DB_USERNAME=portal_rw
DB_PASSWORD=Wint3r2024!Portal
MAIL_HOST=smtp.dudaei-logistics.test
AWS_ACCESS_KEY_ID=AKIAFAKE0NOTREAL0BAIT
AWS_SECRET_ACCESS_KEY=fAkE0nOtReAl0hOnEyPoT0bAiT0kEy0000000000
"""

FAKE_GIT_CONFIG = """[core]
\trepositoryformatversion = 0
\tfilemode = true
[remote "origin"]
\turl = https://git.dudaei-logistics.test/portal/web.git
\tfetch = +refs/heads/*:refs/remotes/origin/*
[branch "main"]
\tremote = origin
\tmerge = refs/heads/main
[user]
\tname = deploy-bot
\temail = deploy@dudaei-logistics.test
"""

FAKE_SQL_DUMP = """-- MySQL dump 10.13  Distrib 8.0.35
-- Host: 10.0.4.17    Database: portal_prod
-- ------------------------------------------------------
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user` varchar(64) NOT NULL,
  `email` varchar(128) DEFAULT NULL,
  `pass_hash` varchar(255) NOT NULL,
  `role` varchar(32) DEFAULT 'user',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT INTO `users` VALUES
 (1,'a.cohen','a.cohen@dudaei-logistics.test','$2y$10$FAKEfakeFAKEfakeHONEYPOTbait0000000000000000000000','admin'),
 (2,'m.levi','m.levi@dudaei-logistics.test','$2y$10$FAKEfakeFAKEfakeHONEYPOTbait1111111111111111111111','manager');
-- Dump completed
"""

# A canned MySQL error. There is no SQL engine here — this is a lure that makes
# the endpoint look injectable, so the attacker reveals their technique.
FAKE_SQL_ERROR = ("You have an error in your SQL syntax; check the manual that "
                  "corresponds to your MySQL server version for the right syntax "
                  "to use near '{frag}' at line 1")

ROBOTS = """User-agent: *
Disallow: /admin/
Disallow: /backup/
Disallow: /db-backup.sql
Disallow: /internal/
Disallow: /.git/
Disallow: /api/v1/users
Crawl-delay: 10
"""

_PAGE_CSS = """*{box-sizing:border-box}body{margin:0;font-family:system-ui,Segoe UI,Arial,sans-serif;
color:#1f2933;background:#f7f9fb}header{background:#12305c;color:#fff;padding:16px 32px;display:flex;
justify-content:space-between;align-items:center}header b{font-size:19px;letter-spacing:.3px}
nav a{color:#cfe0f5;margin-left:18px;text-decoration:none;font-size:14px}
.wrap{max-width:1000px;margin:0 auto;padding:40px 32px}h1{font-size:34px;margin:0 0 12px}
.sub{color:#5b6b7c;font-size:16px;line-height:1.6;max-width:620px}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:36px}
.card{background:#fff;border:1px solid #dde5ee;border-radius:10px;padding:20px}
.card h3{margin:0 0 8px;font-size:16px}.card p{margin:0;color:#647383;font-size:13px;line-height:1.6}
footer{border-top:1px solid #dde5ee;margin-top:48px;padding:20px 32px;color:#8494a4;font-size:12px;text-align:center}
form{background:#fff;border:1px solid #dde5ee;border-radius:10px;padding:26px;max-width:360px;margin-top:24px}
label{display:block;font-size:13px;margin:12px 0 5px;color:#48566a}
input{width:100%;padding:9px 11px;border:1px solid #cbd6e2;border-radius:6px;font-size:14px}
button{margin-top:18px;width:100%;padding:10px;background:#12305c;color:#fff;border:0;border-radius:6px;
font-size:14px;cursor:pointer}.err{background:#fdecea;border:1px solid #f5c2bd;color:#a3231a;
padding:9px 11px;border-radius:6px;font-size:13px;margin-bottom:14px}"""


def _shell(title, body):
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>{title} — {SITE}</title><style>{_PAGE_CSS}</style></head><body>
<header><b>{SITE}</b><nav><a href="/">Home</a><a href="/services">Services</a>
<a href="/about">About</a><a href="/login">Staff Login</a></nav></header>
<div class="wrap">{body}</div>
<footer>© 2024 {SITE} · Portal v2.4.1 · <a href="/login">Employee Portal</a></footer>
</body></html>"""


HOME = _shell("Home", """<h1>Freight, forwarding &amp; warehousing</h1>
<p class="sub">Moving 40,000 containers a year through Haifa and Ashdod. Real-time
tracking, customs clearance and bonded storage for importers across the region.</p>
<div class="cards">
<div class="card"><h3>Ocean freight</h3><p>FCL and LCL consolidation with weekly
sailings to 60 ports.</p></div>
<div class="card"><h3>Customs brokerage</h3><p>Licensed brokers handling clearance
and duty optimisation.</p></div>
<div class="card"><h3>Warehousing</h3><p>18,000 m² of bonded and ambient storage
with WMS integration.</p></div></div>
<p class="sub" style="margin-top:34px">Staff:
<a href="/login">sign in to the employee portal</a> to view shipments.</p>""")

LOGIN_PAGE = _shell("Staff Login", """<h1>Employee Portal</h1>
<p class="sub">Authorised personnel only. Access is logged.</p>
<form method="POST" action="/login">
<label>Username</label><input name="username" autocomplete="off">
<label>Password</label><input name="password" type="password" autocomplete="off">
<button type="submit">Sign in</button></form>""")

LOGIN_FAIL = _shell("Staff Login", """<h1>Employee Portal</h1>
<p class="sub">Authorised personnel only. Access is logged.</p>
<form method="POST" action="/login">
<div class="err">Invalid username or password.</div>
<label>Username</label><input name="username" autocomplete="off">
<label>Password</label><input name="password" type="password" autocomplete="off">
<button type="submit">Sign in</button></form>""")

NOT_FOUND = _shell("404", "<h1>404</h1><p class='sub'>Page not found.</p>")


# --------------------------------------------------------------- the handler -
class Pot(BaseHTTPRequestHandler):
    server_version = "Apache/2.4.41"        # bait: looks old enough to be juicy
    sys_version = " (Ubuntu)"
    protocol_version = "HTTP/1.1"

    # -- plumbing ------------------------------------------------------------
    def log_message(self, fmt, *args):
        pass    # stdout stays quiet; the JSONL log is the record

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode("utf-8", "replace") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Powered-By", "PHP/7.4.3")   # bait
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def _client_ip(self):
        # Behind Caddy/nginx the real IP arrives in a forwarding header.
        for h in ("X-Forwarded-For", "X-Real-IP"):
            v = self.headers.get(h)
            if v:
                return v.split(",")[0].strip()
        return self.client_address[0]

    def _capture(self, body=b""):
        """Record the request verbatim. This is the honeypot's entire product."""
        try:
            text = body.decode("utf-8", "replace")
        except Exception:
            text = repr(body)
        ev = {
            "ts": time.time(),
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pot": "web",
            "src_ip": _clip(self._client_ip(), 64),
            "method": _clip(self.command, 16),
            "path": _clip(self.path),
            "proto": _clip(self.request_version, 16),
            "headers": {_clip(k, 64): _clip(v) for k, v in list(self.headers.items())[:40]},
            "body": _clip(text, MAX_BODY),
            "ua": _clip(self.headers.get("User-Agent", ""), 512),
        }
        # `blob` is what the production classifier regexes over — the whole
        # request as one string, so a payload is caught in URI, header or body.
        hdr = "\n".join(f"{k}: {v}" for k, v in ev["headers"].items())
        ev["blob"] = _clip(f"{ev['method']} {ev['path']} {ev['proto']}\n{hdr}\n\n{ev['body']}",
                           MAX_BODY)
        log_event(ev)
        return ev

    def _read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return b""
        return self.rfile.read(min(n, MAX_BODY)) if n > 0 else b""

    # -- verbs ---------------------------------------------------------------
    def do_GET(self):
        self._capture()
        self._route(self.path, b"")

    def do_POST(self):
        body = self._read_body()
        self._capture(body)
        self._route(self.path, body)

    def do_HEAD(self):
        self._capture()
        self._send(200, "")

    def do_PUT(self):
        self._capture(self._read_body())
        self._send(403, _shell("403", "<h1>403</h1><p class='sub'>Forbidden.</p>"))

    do_DELETE = do_PUT
    do_PATCH = do_POST
    do_OPTIONS = do_HEAD

    # -- routing (all responses are canned strings) --------------------------
    def _route(self, raw_path, body):
        p = urlparse(raw_path)
        path = p.path.rstrip("/").lower() or "/"
        qs = p.query or ""

        if path == "/":
            return self._send(200, HOME)
        if path == "/robots.txt":
            return self._send(200, ROBOTS, "text/plain; charset=utf-8")

        # --- bait: secrets left lying around -------------------------------
        if path == "/.env":
            return self._send(200, FAKE_ENV, "text/plain; charset=utf-8")
        if path.startswith("/.git/config"):
            return self._send(200, FAKE_GIT_CONFIG, "text/plain; charset=utf-8")
        if path.startswith("/.git/head"):
            return self._send(200, "ref: refs/heads/main\n", "text/plain; charset=utf-8")
        if path in ("/backup/db-backup.sql", "/db-backup.sql", "/dump.sql", "/backup.sql"):
            return self._send(200, FAKE_SQL_DUMP, "text/plain; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="db-backup.sql"'})

        # --- bait: the SQL-flavoured API -----------------------------------
        if path in ("/api/v1/users", "/api/users"):
            return self._fake_sql_api(qs)

        # --- bait: login (captures whatever creds they try) -----------------
        if path in ("/login", "/admin", "/admin/login", "/wp-login.php",
                    "/administrator", "/user/login"):
            if self.command == "POST":
                time.sleep(0.4)              # feel like a real auth round-trip
                return self._send(401, LOGIN_FAIL)
            return self._send(200, LOGIN_PAGE)

        # --- bait: admin-ish surfaces --------------------------------------
        if path in ("/phpmyadmin", "/pma", "/adminer.php"):
            return self._send(200, _shell("phpMyAdmin", """<h1>phpMyAdmin</h1>
<p class="sub">Database administration.</p><form method="POST" action="/phpmyadmin">
<label>Username</label><input name="pma_username" autocomplete="off">
<label>Password</label><input name="pma_password" type="password" autocomplete="off">
<button type="submit">Go</button></form>"""))
        if path == "/server-status":
            return self._send(200, "<h1>Apache Server Status for {}</h1>"
                                   "<p>Server Version: Apache/2.4.41 (Ubuntu)</p>"
                                   "<p>Total accesses: 184213 - Total Traffic: 4.1 GB</p>"
                                   .format(SITE))
        if path in ("/services", "/about", "/internal"):
            return self._send(200, _shell(path.strip("/").title(),
                              f"<h1>{path.strip('/').title()}</h1>"
                              "<p class='sub'>Content available to signed-in staff. "
                              "<a href='/login'>Sign in</a>.</p>"))

        return self._send(404, NOT_FOUND)

    def _fake_sql_api(self, qs):
        """Looks injectable. Isn't. There is no SQL engine behind this at all.

        On an injection-shaped `id`, return a canned MySQL error so the attacker
        believes it worked and escalates — revealing more of their technique to
        the log. Anything else gets fixed fake rows.
        """
        m = re.search(r"(?:^|&)id=([^&]*)", qs)
        # Decode before echoing: a real MySQL error quotes the decoded value, so
        # leaving %20 in the message would give the honeypot away.
        rid = unquote_plus(m.group(1)) if m else ""
        if rid and re.search(r"['\"]|union|select|sleep|benchmark|--|;|or\s+1|information_schema",
                             rid, re.I):
            frag = rid[:48]
            return self._send(500, json.dumps(
                {"error": "Database error", "code": 1064,
                 "message": FAKE_SQL_ERROR.format(frag=frag),
                 "query": f"SELECT * FROM users WHERE id = '{frag}'"},
                ensure_ascii=False), "application/json; charset=utf-8")
        if rid.isdigit():
            row = next((u for u in FAKE_USERS if u["id"] == int(rid)), None)
            return self._send(200 if row else 404,
                              json.dumps(row or {"error": "not found"}, ensure_ascii=False),
                              "application/json; charset=utf-8")
        return self._send(200, json.dumps({"users": FAKE_USERS}, ensure_ascii=False),
                          "application/json; charset=utf-8")


def main():
    # Never let the banner kill the pot: consoles without a UTF-8 locale
    # (e.g. Windows cp1252) raise on the emoji otherwise.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # Fail loudly at boot if we cannot write events. log_event() deliberately
    # swallows errors so a bad request can never crash the pot — but that also
    # means an unwritable path would silently discard every capture, leaving a
    # honeypot that looks healthy and records nothing. Check once, up front.
    try:
        d = os.path.dirname(os.path.abspath(EVENTS))
        os.makedirs(d, exist_ok=True)
        with open(EVENTS, "a", encoding="utf-8"):
            pass
    except Exception as e:
        print(f"FATAL: event log not writable: {EVENTS}\n       {e}", file=sys.stderr)
        return 2

    srv = ThreadingHTTPServer((BIND, PORT), Pot)
    srv.daemon_threads = True
    print(f"🍯 web_pot listening on {BIND}:{PORT}")
    print(f"   events -> {EVENTS}")
    print(f"   site   -> {SITE} (all content is fake)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
