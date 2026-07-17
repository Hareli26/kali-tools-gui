#!/usr/bin/env python3
"""
🍯 sql_pot — low-interaction MySQL honeypot (port 3306).

Speaks just enough of the MySQL wire protocol to make an attacker believe they
reached a real database: it sends a genuine-looking handshake, ACCEPTS ANY
credentials (so the attacker reveals what they'd do once "in"), and answers a
handful of recon queries with fake data. Every login and query is appended to
JSONL — the same format web_pot uses, so the existing collector and sensor pick
it up with zero changes.

Same rules as web_pot, because this is internet-exposed by design:
  * Never executes anything. There is no SQL engine — queries are matched
    against a tiny canned-response table; everything else gets a generic OK.
  * No real data. Every database, table, user and value served is invented.
  * No classification here; the production sensor does that, so a compromise of
    this box cannot poison the analyser.
  * Bounded: query length, per-connection command count, event size and the log
    are all capped, so a flood cannot exhaust the host.

Accepting every login is the deliberate choice. A honeypot that REJECTS logins
learns only usernames; one that ACCEPTS them learns the attacker's post-access
playbook — the INTO OUTFILE webshell drop, the UDF remote-code-exec, the
mysql.user dump — which is the intel actually worth having.

Usage:
    python3 sql_pot.py
    HP_SQL_PORT=3306 HP_SQL_EVENTS=/var/log/honeypot/sql.jsonl python3 sql_pot.py

Authorised deception on infrastructure you own. Do not point this at anyone else.
"""

import binascii
import json
import os
import socket
import socketserver
import struct
import sys
import threading
import time

# ------------------------------------------------------------------ config ---
PORT = int(os.environ.get("HP_SQL_PORT", "3306"))
BIND = os.environ.get("HP_SQL_BIND", "0.0.0.0")
EVENTS = os.environ.get("HP_SQL_EVENTS") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "sql_events.jsonl")
# An Ubuntu-flavoured version string — the pot host is Ubuntu 24.04, so this
# reads as a real box rather than a canned default.
SERVER_VERSION = os.environ.get("HP_SQL_VERSION", "8.0.36-0ubuntu0.24.04.1")

MAX_QUERY = 8192
MAX_CMDS = 200                          # commands per connection before we hang up
MAX_FIELD = 2048
MAX_EVENTS_BYTES = 64 * 1024 * 1024
_LOG_LOCK = threading.Lock()
_CONN_LOCK = threading.Lock()
_conn_seq = 0

# ------------------------------------------------ MySQL capability flags ------
CLIENT_LONG_PASSWORD     = 0x00000001
CLIENT_LONG_FLAG         = 0x00000004
CLIENT_CONNECT_WITH_DB   = 0x00000008
CLIENT_PROTOCOL_41       = 0x00000200
CLIENT_SSL               = 0x00000800
CLIENT_TRANSACTIONS      = 0x00002000
CLIENT_SECURE_CONNECTION = 0x00008000
CLIENT_PLUGIN_AUTH       = 0x00080000
CLIENT_PLUGIN_AUTH_LENENC = 0x00200000

# We deliberately do NOT advertise CLIENT_SSL (no TLS to offer) or
# CLIENT_DEPRECATE_EOF (so we always use classic EOF packets, which is simpler
# and correct regardless of the client).
SERVER_CAPS = (CLIENT_LONG_PASSWORD | CLIENT_LONG_FLAG | CLIENT_CONNECT_WITH_DB |
               CLIENT_PROTOCOL_41 | CLIENT_TRANSACTIONS | CLIENT_SECURE_CONNECTION |
               CLIENT_PLUGIN_AUTH)

# Pre-built stock packets (payloads, before framing).
OK_PKT = b"\x00\x00\x00\x02\x00\x00\x00"          # OK: 0 rows, autocommit
EOF_PKT = b"\xfe\x00\x00\x02\x00"                  # EOF: 0 warnings, autocommit


# --------------------------------------------------------- protocol helpers ---
def _lenc_int(n):
    if n < 0xfb:
        return bytes([n])
    if n <= 0xffff:
        return b"\xfc" + struct.pack("<H", n)
    if n <= 0xffffff:
        return b"\xfd" + struct.pack("<I", n)[:3]
    return b"\xfe" + struct.pack("<Q", n)


def _lenc_str(s):
    b = s.encode("utf-8", "replace") if isinstance(s, str) else s
    return _lenc_int(len(b)) + b


def _read_lenc(buf, off):
    first = buf[off]
    off += 1
    if first < 0xfb:
        return first, off
    if first == 0xfc:
        return int.from_bytes(buf[off:off + 2], "little"), off + 2
    if first == 0xfd:
        return int.from_bytes(buf[off:off + 3], "little"), off + 3
    if first == 0xfe:
        return int.from_bytes(buf[off:off + 8], "little"), off + 8
    return 0, off


def _frame(payload, seq):
    return struct.pack("<I", len(payload))[:3] + bytes([seq & 0xff]) + payload


def _err(code, msg, state="HY000"):
    return b"\xff" + struct.pack("<H", code) + b"#" + state.encode() + msg.encode()


def _make_salt():
    # 20 printable, NUL-free bytes — some clients treat the salt as a C string.
    return bytes((b % 93) + 33 for b in os.urandom(20))


def _next_conn_id():
    global _conn_seq
    with _CONN_LOCK:
        _conn_seq = (_conn_seq + 1) % 0x7fffffff
        return _conn_seq + 1000


def _handshake(conn_id, salt):
    p = b"\x0a"                                    # protocol version 10
    p += SERVER_VERSION.encode() + b"\x00"
    p += struct.pack("<I", conn_id)
    p += salt[:8] + b"\x00"                        # auth-plugin-data-1 + filler
    p += struct.pack("<H", SERVER_CAPS & 0xffff)   # capability flags (low)
    p += bytes([0x21])                             # charset utf8_general_ci
    p += struct.pack("<H", 0x0002)                 # status: autocommit
    p += struct.pack("<H", (SERVER_CAPS >> 16) & 0xffff)   # capability (high)
    p += bytes([21])                               # auth-plugin-data length
    p += b"\x00" * 10                              # reserved
    p += salt[8:20] + b"\x00"                      # auth-plugin-data-2 + NUL
    p += b"mysql_native_password\x00"
    return p


def _column_def(name):
    p = _lenc_str("def")          # catalog
    p += _lenc_str("")            # schema
    p += _lenc_str("")            # table
    p += _lenc_str("")            # org_table
    p += _lenc_str(name)          # name
    p += _lenc_str("")            # org_name
    p += _lenc_int(0x0c)          # length of the fixed-length block
    p += struct.pack("<H", 0x21)  # charset utf8_general_ci
    p += struct.pack("<I", 256)   # column length
    p += bytes([0xfd])            # type MYSQL_TYPE_VAR_STRING
    p += struct.pack("<H", 0)     # flags
    p += bytes([0x00])            # decimals
    p += b"\x00\x00"              # filler
    return p


def _result_set(columns, rows):
    """Build the packet list for a classic (non-DEPRECATE_EOF) result set."""
    pkts = [_lenc_int(len(columns))]
    pkts += [_column_def(c) for c in columns]
    pkts.append(EOF_PKT)
    for row in rows:
        rp = b""
        for val in row:
            rp += b"\xfb" if val is None else _lenc_str(str(val))
        pkts.append(rp)
    pkts.append(EOF_PKT)
    return pkts


# --------------------------------------------------------- canned responses ---
# Everything here is invented. There is no database behind any of it.
FAKE_DATABASES = ["information_schema", "mysql", "performance_schema", "sys", "portal_prod"]
FAKE_TABLES = ["users", "orders", "sessions", "api_keys", "config"]


def _respond(query):
    """Map a query to a packet list. Recon queries get plausible fake results;
    anything else gets a bare OK so the client keeps talking (and keeps
    revealing technique). We never parse SQL — just look for familiar shapes."""
    q = query.strip().rstrip(";").lower()

    if "@@version_comment" in q:
        return _result_set(["@@version_comment"], [["MySQL Community Server - GPL"]])
    if "@@version" in q or q == "select version()" or "version()" in q:
        return _result_set(["version()"], [[SERVER_VERSION]])
    if "@@datadir" in q:
        return _result_set(["@@datadir"], [["/var/lib/mysql/"]])
    if "@@hostname" in q:
        return _result_set(["@@hostname"], [["db-prod-01"]])
    if "user()" in q or "current_user" in q:
        return _result_set(["user()"], [["root@localhost"]])
    if "database()" in q or q == "select database":
        return _result_set(["database()"], [[None]])
    if q.startswith("show databases"):
        return _result_set(["Database"], [[d] for d in FAKE_DATABASES])
    if q.startswith("show tables"):
        return _result_set(["Tables_in_portal_prod"], [[t] for t in FAKE_TABLES])
    if q.startswith("select 1"):
        return _result_set(["1"], [["1"]])

    # Unknown SELECT/SHOW -> empty result set (keeps SELECT clients happy).
    if q.startswith(("select", "show", "desc", "explain", "with")):
        return _result_set(["info"], [])
    # Everything else (SET, USE, INSERT, CREATE, ...) -> OK.
    return [OK_PKT]


# ------------------------------------------------------------ event logging ---
def _clip(s, n=MAX_FIELD):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n] + "…[truncated]"


def _log_event(ev):
    try:
        with _LOG_LOCK:
            if os.path.exists(EVENTS) and os.path.getsize(EVENTS) > MAX_EVENTS_BYTES:
                os.replace(EVENTS, EVENTS + ".1")
            with open(EVENTS, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass


# --------------------------------------------------------------- the handler --
class MySQLHandler(socketserver.BaseRequestHandler):

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.request.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _recv_pkt(self):
        hdr = self._recv_exact(4)
        if not hdr:
            return None, 0
        ln = hdr[0] | (hdr[1] << 8) | (hdr[2] << 16)
        seq = hdr[3]
        if ln == 0:
            return b"", seq
        if ln > MAX_QUERY + 64:                    # oversized — read & discard cap
            ln = MAX_QUERY + 64
        payload = self._recv_exact(ln)
        return (payload if payload is not None else None), seq

    def _send(self, payloads, start_seq):
        buf = b""
        seq = start_seq
        for p in payloads:
            buf += _frame(p, seq)
            seq = (seq + 1) & 0xff
        self.request.sendall(buf)

    def _capture(self, kind, path, blob, extra=None):
        ev = {
            "ts": time.time(),
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pot": "sql",
            "src_ip": _clip(self.client_address[0], 64),   # raw socket peer — no XFF to spoof
            "method": kind,
            "path": _clip(path, 512),
            "proto": "mysql",
            "headers": extra or {},
            "body": "",
            "ua": "",
            "blob": _clip(blob, MAX_QUERY),
        }
        _log_event(ev)

    def handle(self):
        sock = self.request
        sock.settimeout(20)
        peer = self.client_address[0]
        try:
            salt = _make_salt()
            sock.sendall(_frame(_handshake(_next_conn_id(), salt), 0))

            payload, seq = self._recv_pkt()
            if not payload or len(payload) < 4:
                return
            caps = struct.unpack("<I", payload[0:4])[0]

            # A client demanding TLS (or sending only the short SSL-request
            # packet) can't be served without a certificate. Record the attempt
            # and drop — trying to reach a DB over TLS is itself a signal.
            if (caps & CLIENT_SSL) or len(payload) < 33:
                self._capture("SSL-LOGIN", "",
                              "MYSQL LOGIN ssl/tls handshake attempt", peer)
                try:
                    self._send([_err(1043, "Bad handshake", "08S01")], seq + 1)
                except Exception:
                    pass
                return

            user, authblob, db = self._parse_login(payload, caps)
            authhex = binascii.hexlify(authblob).decode()[:80]
            self._capture("LOGIN", user,
                          f"MYSQL LOGIN user={user} db={db} auth={authhex}", peer)

            # Accept — we want the post-login behaviour, not just the username.
            self._send([OK_PKT], seq + 1)
            self._command_loop()
        except (socket.timeout, ConnectionError, OSError):
            pass
        except Exception:
            pass

    def _parse_login(self, payload, caps):
        try:
            off = 32                                       # caps(4)+maxpkt(4)+charset(1)+reserved(23)
            end = payload.find(b"\x00", off)
            user = payload[off:end if end != -1 else len(payload)].decode("utf-8", "replace")
            if end == -1:
                return user, b"", ""
            off = end + 1
            auth = b""
            if caps & CLIENT_PLUGIN_AUTH_LENENC:
                alen, off = _read_lenc(payload, off)
                auth = payload[off:off + alen]
                off += alen
            elif caps & CLIENT_SECURE_CONNECTION:
                alen = payload[off]
                off += 1
                auth = payload[off:off + alen]
                off += alen
            else:
                end = payload.find(b"\x00", off)
                auth = payload[off:end if end != -1 else len(payload)]
                off = (end + 1) if end != -1 else len(payload)
            db = ""
            if caps & CLIENT_CONNECT_WITH_DB:
                end = payload.find(b"\x00", off)
                if end != -1:
                    db = payload[off:end].decode("utf-8", "replace")
            return _clip(user, 128), auth, _clip(db, 128)
        except Exception:
            return "?", b"", ""

    def _command_loop(self):
        for _ in range(MAX_CMDS):
            payload, seq = self._recv_pkt()
            if payload is None or len(payload) == 0:
                break
            cmd = payload[0]
            if cmd == 0x01:                            # COM_QUIT
                break
            if cmd == 0x03:                            # COM_QUERY
                q = payload[1:].decode("utf-8", "replace")[:MAX_QUERY]
                self._capture("QUERY", q[:200], f"MYSQL QUERY {q}", self.client_address[0])
                try:
                    self._send(_respond(q), (seq + 1) & 0xff)
                except Exception:
                    break
            elif cmd == 0x02:                          # COM_INIT_DB
                self._capture("USE-DB", payload[1:].decode("utf-8", "replace")[:128],
                              "MYSQL QUERY use " + payload[1:].decode("utf-8", "replace")[:128],
                              self.client_address[0])
                self._send([OK_PKT], (seq + 1) & 0xff)
            elif cmd == 0x0e:                          # COM_PING
                self._send([OK_PKT], (seq + 1) & 0xff)
            else:                                      # anything else -> OK
                self._send([OK_PKT], (seq + 1) & 0xff)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Fail loudly if the event log is unwritable — like web_pot, _log_event
    # swallows errors so a bad client can't crash the pot, which would otherwise
    # let a mistyped path yield a healthy-looking pot that records nothing.
    try:
        os.makedirs(os.path.dirname(os.path.abspath(EVENTS)), exist_ok=True)
        with open(EVENTS, "a", encoding="utf-8"):
            pass
    except Exception as e:
        print(f"FATAL: event log not writable: {EVENTS}\n       {e}", file=sys.stderr)
        return 2

    srv = _Server((BIND, PORT), MySQLHandler)
    print(f"🍯 sql_pot (fake MySQL {SERVER_VERSION}) listening on {BIND}:{PORT}")
    print(f"   events -> {EVENTS}")
    print("   accepts any login; serves fake data only; executes nothing.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
