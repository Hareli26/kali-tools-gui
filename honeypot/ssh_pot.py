#!/usr/bin/env python3
"""
🍯 ssh_pot — credential-harvesting SSH honeypot (port 22).

SSH is the internet's most brute-forced service, and the credentials the bots
try are the single most valuable thing to learn — a live dictionary of what
attackers actually use. This pot captures every username+password pair and
ALWAYS rejects it.

Why this one needs a dependency (paramiko) when the others don't:
  After the handshake, SSH encrypts everything with AES — and Python's standard
  library has no symmetric cipher at all. Capturing a username or password is
  therefore impossible in pure stdlib; you must terminate the encryption, which
  needs a crypto library. paramiko is that library. It runs ONLY here, on the
  sacrificial host. Production (sensor, attack_kb, server) stays stdlib-only.

Low-interaction and safe, by design:
  * NO shell, NO session, NO command execution. Every channel request is
    rejected; every auth attempt is logged and returns AUTH_FAILED. There is
    nothing to "get into" — we only harvest the credentials being tried.
  * The host key is generated once and persisted, so the fingerprint is stable
    (a key that changes every restart looks like a honeypot).
  * Bounded: per-connection attempt cap, negotiation timeout, log rotation.

Events are written in the same JSONL shape as the other pots, so the existing
collector and sensor pick them up unchanged.

Usage:
    HP_SSH_PORT=22 HP_SSH_EVENTS=/var/log/honeypot/ssh.jsonl python3 ssh_pot.py

Authorised deception on infrastructure you own. Do not point this at anyone else.
"""

import json
import os
import socket
import sys
import threading
import time

try:
    import paramiko
except ImportError:
    sys.stderr.write(
        "FATAL: paramiko is required for the SSH honeypot.\n"
        "       python3 -m venv .venv && .venv/bin/pip install paramiko\n"
        "       (the SSH pot is the one component that can't be pure stdlib — "
        "SSH encrypts with AES, which stdlib lacks.)\n")
    raise SystemExit(2)

# ------------------------------------------------------------------ config ---
PORT = int(os.environ.get("HP_SSH_PORT", "22"))
BIND = os.environ.get("HP_SSH_BIND", "0.0.0.0")
EVENTS = os.environ.get("HP_SSH_EVENTS") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ssh_events.jsonl")
KEYFILE = os.environ.get("HP_SSH_HOSTKEY") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ssh_host_rsa_key")
# Ubuntu-flavoured banner — the pot host is Ubuntu 24.04, so this reads real.
BANNER = os.environ.get("HP_SSH_BANNER", "SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.5")

MAX_ATTEMPTS = 20            # logged auth attempts per connection
MAX_FIELD = 512
NEG_TIMEOUT = 25            # seconds for the SSH negotiation
MAX_EVENTS_BYTES = 64 * 1024 * 1024
_LOG_LOCK = threading.Lock()


def _clip(s, n=MAX_FIELD):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n] + "…"


def _log_event(ev):
    try:
        with _LOG_LOCK:
            if os.path.exists(EVENTS) and os.path.getsize(EVENTS) > MAX_EVENTS_BYTES:
                os.replace(EVENTS, EVENTS + ".1")
            with open(EVENTS, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _capture(src_ip, kind, user, secret, client):
    """Record one auth attempt. `secret` is the password (or key fingerprint).
    blob is what the production classifier regexes over."""
    ev = {
        "ts": time.time(),
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pot": "ssh",
        "src_ip": _clip(src_ip, 64),          # raw socket peer — no header to spoof
        "method": kind,                        # LOGIN (password) | PUBKEY
        "path": _clip(user, 128),
        "proto": "ssh",
        "headers": {},
        "body": _clip(secret, 256),
        "ua": _clip(client, 256),              # SSH client version = tool fingerprint
        "blob": _clip(f"SSH LOGIN user={user} pass={secret} client={client}", 1024),
    }
    _log_event(ev)


class _HoneyServer(paramiko.ServerInterface):
    """Logs every auth attempt and refuses all of them. No shell is ever given."""

    def __init__(self, src_ip, transport):
        self.src_ip = src_ip
        self.transport = transport
        self.attempts = 0

    def _client(self):
        return getattr(self.transport, "remote_version", "") or ""

    def get_allowed_auths(self, username):
        # Advertise both so bots reveal passwords AND key attempts.
        return "password,publickey"

    def check_auth_password(self, username, password):
        self.attempts += 1
        _capture(self.src_ip, "LOGIN", username, password, self._client())
        if self.attempts >= MAX_ATTEMPTS:
            return paramiko.AUTH_FAILED
        return paramiko.AUTH_FAILED           # never accept — pure harvesting

    def check_auth_publickey(self, username, key):
        self.attempts += 1
        try:
            fp = key.get_fingerprint().hex()
        except Exception:
            fp = "?"
        _capture(self.src_ip, "PUBKEY", username, "key:" + fp, self._client())
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        # No sessions, ever. There is nothing behind this door.
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def get_banner(self):
        return ("", "")


def _load_host_key():
    if os.path.exists(KEYFILE):
        try:
            return paramiko.RSAKey(filename=KEYFILE)
        except Exception:
            pass
    key = paramiko.RSAKey.generate(2048)
    try:
        key.write_private_key_file(KEYFILE)
        os.chmod(KEYFILE, 0o600)
    except Exception:
        pass
    return key


def _handle(client_sock, addr, host_key):
    src_ip = addr[0]
    t = None
    try:
        # Hand paramiko a plain blocking socket — a socket-level timeout here
        # breaks the banner exchange (the client sees a connection reset before
        # it ever reads "SSH-2.0-..."). paramiko applies its own timeout.
        t = paramiko.Transport(client_sock)
        t.local_version = BANNER
        # Negotiation timeouts are set as attributes — start_server() takes no
        # `timeout` kwarg (passing one raises TypeError, which silently aborts
        # the whole exchange and the banner never gets sent).
        t.banner_timeout = NEG_TIMEOUT
        t.handshake_timeout = NEG_TIMEOUT
        t.auth_timeout = NEG_TIMEOUT
        t.add_server_key(host_key)
        server = _HoneyServer(src_ip, t)
        # start_server negotiates and then lets the client authenticate; the auth
        # callbacks (which log) fire in the transport's own thread. We wait for
        # the client to exhaust its attempts (auth always fails) rather than
        # closing early, which would reset a mid-brute-force connection.
        try:
            t.start_server(server=server)
            chan = t.accept(NEG_TIMEOUT)      # never opens (auth fails) — just waits
            if chan is not None:
                chan.close()
        except Exception as e:
            if os.environ.get("HP_SSH_DEBUG"):
                print(f"negotiation with {src_ip}: {type(e).__name__}: {e}", file=sys.stderr)
        # If the transport thread is still alive, give it a moment to finish.
        try:
            t.join(NEG_TIMEOUT)
        except Exception:
            pass
    except Exception as e:
        if os.environ.get("HP_SSH_DEBUG"):
            print(f"handle error from {src_ip}: {type(e).__name__}: {e}", file=sys.stderr)
    finally:
        try:
            if t is not None:
                t.close()
        except Exception:
            pass
        try:
            client_sock.close()
        except Exception:
            pass


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Fail loud at boot if the log is unwritable — _log_event swallows errors so
    # a bad client can't crash the pot, which would otherwise let a mistyped path
    # yield a healthy-looking pot that records nothing.
    try:
        os.makedirs(os.path.dirname(os.path.abspath(EVENTS)), exist_ok=True)
        with open(EVENTS, "a", encoding="utf-8"):
            pass
    except Exception as e:
        print(f"FATAL: event log not writable: {EVENTS}\n       {e}", file=sys.stderr)
        return 2

    host_key = _load_host_key()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((BIND, PORT))
    except PermissionError:
        print(f"FATAL: cannot bind {BIND}:{PORT} — port <1024 needs privilege.\n"
              f"       Use systemd AmbientCapabilities=CAP_NET_BIND_SERVICE, or a "
              f"high port for testing (HP_SSH_PORT=2222).", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"FATAL: cannot bind {BIND}:{PORT} — {e}\n"
              f"       Is a real sshd still on this port? Move it first (see README).",
              file=sys.stderr)
        return 2
    srv.listen(100)

    print(f"🍯 ssh_pot ({BANNER}) listening on {BIND}:{PORT}")
    print(f"   events -> {EVENTS}")
    print(f"   host key -> {KEYFILE}")
    print("   captures credentials; rejects every login; no shell, ever.")

    try:
        while True:
            try:
                client_sock, addr = srv.accept()
            except OSError:
                break
            # No settimeout here — paramiko needs a blocking socket for the
            # banner exchange and applies its own negotiation timeout.
            threading.Thread(target=_handle, args=(client_sock, addr, host_key),
                             daemon=True).start()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        try:
            srv.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
