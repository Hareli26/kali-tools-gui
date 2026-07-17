#!/usr/bin/env python3
"""
🌍 IP geolocation for honeypot analytics — production side, stdlib only.

Turns attacker IPs into a country so the dashboard can answer "where are the
attacks coming from" and "what does each region favour". Uses ip-api.com's free
batch endpoint (no key, ~15 batch req/min) via urllib, and caches every result
in the DB so each IP is resolved once and reused across all its events.

Degrades gracefully by design: a private/reserved IP, no network, or a
rate-limit just yields an empty country — the feature keeps working with less
data, ingestion never blocks, and failures are NOT cached so they retry later.

Only attacker IPs (already public and already logged) are sent to ip-api.com.
To go fully offline, swap `_batch()` for a local GeoIP database; nothing else
changes.
"""

import ipaddress
import json
import urllib.request

import db

BATCH_URL = "http://ip-api.com/batch"
BATCH_MAX = 100                 # ip-api allows up to 100 IPs per batch
MAX_LOOKUPS_PER_RUN = 300       # bound external calls even in an IP flood
TIMEOUT = 8


def _is_public(ip):
    try:
        a = ipaddress.ip_address(ip)
        return a.is_global and not a.is_private
    except ValueError:
        return False


def _batch(ips):
    """Resolve a chunk of IPs via ip-api. Returns {ip: (cc, country)}; {} on any
    failure (so callers don't cache a miss)."""
    body = json.dumps([{"query": ip, "fields": "countryCode,country,query"}
                       for ip in ips]).encode("utf-8")
    req = urllib.request.Request(BATCH_URL, data=body,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "kali-gui-geo/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return {}
    out = {}
    if isinstance(data, list):
        for item in data:
            q = item.get("query")
            if q and item.get("status") != "fail":
                out[q] = (item.get("countryCode") or "", item.get("country") or "")
    return out


def enrich(ips):
    """Resolve a set of IPs to countries, using and filling the DB cache.
    Returns {ip: (cc, country)}. Never raises — geo is best-effort."""
    out, todo, seen = {}, [], set()
    try:
        for ip in ips:
            if not ip or ip in seen:
                continue
            seen.add(ip)
            cached = db.hp_geo_get(ip)
            if cached is not None:
                out[ip] = cached
            elif not _is_public(ip):
                db.hp_geo_set(ip, "", "Local")     # 127.x / 10.x / ::1 / ...
                out[ip] = ("", "Local")
            else:
                todo.append(ip)

        todo = todo[:MAX_LOOKUPS_PER_RUN]
        for i in range(0, len(todo), BATCH_MAX):
            chunk = todo[i:i + BATCH_MAX]
            res = _batch(chunk)
            for ip in chunk:
                if ip in res:
                    db.hp_geo_set(ip, res[ip][0], res[ip][1])
                    out[ip] = res[ip]
                else:
                    out[ip] = ("", "")             # unknown now — retry next run, not cached
    except Exception:
        pass
    return out


if __name__ == "__main__":
    import sys
    for ip, (cc, country) in enrich(sys.argv[1:] or ["8.8.8.8", "1.1.1.1", "127.0.0.1"]).items():
        print(f"  {ip:<18} {cc:<3} {country}")
