#!/usr/bin/env python3
"""
🛰️ Sensor agent — the bridge from the honeypots to the Blue Team.

Runs on PRODUCTION (kali.dudaei.com). Polls each registered pot's collector,
classifies every captured request against ATTACK_KB, and accumulates what
attackers actually attempt — so the Blue Team learns from real traffic instead
of only from our own simulated Red Team runs.

    🍯 pot (187.124.189.97)  --pull-->  🛰️ sensor  -->  ATTACK_KB  -->  DB
                                                          |
                                     Sigma/Suricata + hardening advice

Trust model — everything from a pot is UNTRUSTED input:
  * The attacker controls the honeypot's input by definition, so event
    poisoning cannot be prevented, only contained.
  * Events land in `hp_events` / `hp_signatures` — never in `signatures`, the
    Red Team's posture KB. An attacker must not be able to write our beliefs
    about our own systems.
  * NOTHING here triggers a fix. An attacker who realised a remediation loop
    existed could feed a signature that hardens us into a lockout (SSH here is
    root+password, no key). Advice only, applied by a human — same rule as the
    existing fixer.
  * Every field is clipped and every pull is capped, so a flood cannot bury one
    real attack under 10,000 fabricated ones.

Usage:
    python3 sensor.py --once              # one poll of every enabled pot
    python3 sensor.py --loop --interval 60
    python3 sensor.py --add web https://web.dudaei.com:8081 <token>
    python3 sensor.py --list
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "honeypot"))

import db                                  # noqa: E402
import geo                                  # noqa: E402  (🌍 IP -> country, cached)
from honeypot import attack_kb             # noqa: E402

PULL_LIMIT = 500          # events per request
MAX_PULLS = 20            # per pot per run — bounds a catch-up after downtime
HTTP_TIMEOUT = 15
MAX_BLOB = 4096           # what we retain per event for later inspection


def _clip(s, n):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n] + "…"


# src_ip originates from the X-Forwarded-For header, which the ATTACKER fully
# controls — it is not a trustworthy IP, it is attacker text. Left raw it would
# flow into the dashboard and give the attacker a stored-XSS foothold in the
# admin's browser: the honeypot turned into a weapon against its owner. Reduce
# it to IP/hostname characters at ingestion, so nothing else can ever reach the
# DB. Rendering escapes as well — this is the first of two layers.
#
# Letters are allowed in full, not just hex digits: restricting to [a-fA-F]
# silently rewrote legitimate values (`fe80::1%eth0` -> `fe80::1%e0`), and
# corrupting a real address is worse than keeping it. Dropping < > " ' / = ( )
# and whitespace is what defuses the payload; `<img src=x onerror=alert(1)>`
# still collapses to inert text.
_IP_OK = re.compile(r"[^0-9a-zA-Z:.\[\]%_-]")


def _safe_ip(v):
    v = _IP_OK.sub("", _clip(v, 64))
    return v or "?"


def _fetch(pot, since):
    """GET <url>/events?since=..&limit=.. with the pot's bearer token."""
    url = f"{pot['url'].rstrip('/')}/events?since={since}&limit={PULL_LIMIT}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {pot['token']}",
        "User-Agent": "kali-gui-sensor/1.0",
    })
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def poll_pot(pot, verbose=False):
    """Pull, classify and store everything new from one pot.

    Returns {pulled, techniques, error}.
    """
    pid = pot["id"]
    since = pot.get("cursor") or 0
    when = time.strftime("%Y-%m-%d %H:%M:%S")
    total_new, tech_counts, ips = 0, {}, {}

    for _ in range(MAX_PULLS):
        try:
            data = _fetch(pot, since)
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}" + (" — bad token?" if e.code == 401 else "")
            db.hp_set_cursor(pid, since, when, err)
            return {"pulled": total_new, "techniques": tech_counts, "error": err}
        except Exception as e:
            err = _clip(str(e), 180)
            db.hp_set_cursor(pid, since, when, err)
            return {"pulled": total_new, "techniques": tech_counts, "error": err}

        events = data.get("events") or []
        if not events:
            break

        rows = []
        for ev in events:
            blob = ev.get("blob") or ""
            rule = attack_kb.classify(blob)
            tid = rule["id"] if rule else ""
            if tid:
                tech_counts[tid] = tech_counts.get(tid, 0) + 1
            ip = _safe_ip(ev.get("src_ip"))
            if tid:
                ips.setdefault(tid, set()).add(ip)
            rows.append({
                "pot": pid,
                "ts": float(ev.get("ts") or time.time()),
                "when": _clip(ev.get("when"), 32),
                "src_ip": ip,
                "method": _clip(ev.get("method"), 16),
                "path": _clip(ev.get("path"), 512),
                "ua": _clip(ev.get("ua"), 256),
                "technique": tid,
                "severity": rule["severity"] if rule else "",
                "blob": _clip(blob, MAX_BLOB),
            })
        db.hp_add_events(rows)
        geo.enrich({r["src_ip"] for r in rows})     # 🌍 resolve new IPs (cached, best-effort)
        total_new += len(rows)
        since = data.get("next", since + len(events))
        db.hp_set_cursor(pid, since, when, "")
        if len(events) < PULL_LIMIT:
            break

    if tech_counts:
        techs = []
        for tid, n in tech_counts.items():
            r = attack_kb.get_attack(tid)
            if r:
                techs.append({"signature": tid, "name": r["name"],
                              "severity": r["severity"], "count": n,
                              "sources": len(ips.get(tid, ()))})
        new = db.hp_update_signatures(techs, when)
        if verbose and new:
            print(f"   🆕 new techniques observed: {', '.join(new)}")

    return {"pulled": total_new, "techniques": tech_counts, "error": ""}


def poll_all(verbose=True):
    pots = [p for p in db.hp_list_pots() if p.get("enabled")]
    if not pots:
        if verbose:
            print("no pots registered — add one:  python3 sensor.py --add web <url> <token>")
        return {"pots": 0, "pulled": 0}
    total = 0
    for meta in pots:
        pot = db.hp_get_pot(meta["id"])          # re-read: needs the token
        res = poll_pot(pot, verbose)
        total += res["pulled"]
        if verbose:
            if res["error"]:
                print(f"❌ {pot['id']}: {res['error']}")
            else:
                tec = ", ".join(f"{k}×{v}" for k, v in
                                sorted(res["techniques"].items(), key=lambda x: -x[1])[:5])
                print(f"✅ {pot['id']}: +{res['pulled']} events" + (f"  [{tec}]" if tec else ""))
    # 🌍 backfill: enrich attacker IPs that are missing OSINT (also catches IPs
    # captured before enrichment existed). Bounded + cached, so it's cheap.
    try:
        missing = db.hp_ips_missing_geo(200)
        if missing:
            geo.enrich(missing)
            if verbose:
                print(f"🌍 enriched {len(missing)} attacker IP(s)")
    except Exception:
        pass
    return {"pots": len(pots), "pulled": total}


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Honeypot sensor agent")
    ap.add_argument("--once", action="store_true", help="poll every enabled pot once")
    ap.add_argument("--loop", action="store_true", help="poll forever")
    ap.add_argument("--interval", type=int, default=60, help="seconds between polls")
    ap.add_argument("--add", nargs=3, metavar=("ID", "URL", "TOKEN"), help="register a pot")
    ap.add_argument("--remove", metavar="ID", help="remove a pot")
    ap.add_argument("--list", action="store_true", help="list registered pots")
    a = ap.parse_args()

    db.init()

    if a.add:
        pid, url, token = a.add
        db.hp_save_pot(pid, "web", url, token, 1, time.strftime("%Y-%m-%d %H:%M:%S"))
        print(f"registered pot '{pid}' -> {url}")
        return 0
    if a.remove:
        db.hp_delete_pot(a.remove)
        print(f"removed pot '{a.remove}'")
        return 0
    if a.list:
        pots = db.hp_list_pots()
        if not pots:
            print("(no pots registered)")
        for p in pots:
            flag = "on " if p["enabled"] else "off"
            print(f"  [{flag}] {p['id']:<10} {p['url']:<44} cursor={p['cursor']} "
                  f"last={p['last_poll'] or '-'} {p['last_error'] or ''}")
        return 0

    if a.loop:
        print(f"🛰️ sensor polling every {a.interval}s — Ctrl-C to stop")
        while True:
            try:
                poll_all()
            except KeyboardInterrupt:
                print("\nbye")
                return 0
            except Exception as e:
                print(f"poll error: {e}")
            time.sleep(a.interval)

    poll_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
