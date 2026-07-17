#!/usr/bin/env python3
"""
SQLite data store for Kali Tools GUI.

Replaces the flat JSON files (knowledge.json / activity.json / audit.log /
reports/) with a single structured database — still zero external deps
(sqlite3 is in the Python standard library).

On first run it auto-imports any existing JSON data so nothing is lost.

Tables:
  signatures  — learning knowledge base (one row per finding signature)
  meta        — key/value (e.g. total run count)
  activity    — run history (missions & purple runs)
  audit       — security audit trail (who did what)
  reports     — persisted Markdown reports
"""
import json
import os
import sqlite3
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("KALIGUI_DATA_DIR") or HERE
DB_FILE = os.path.join(DATA_DIR, "kaligui.db")
_LOCK = threading.RLock()


def _conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_FILE, timeout=15)
    c.row_factory = sqlite3.Row
    # rollback journal (default) — portable across ext4/DrvFs; access is lock-serialized
    return c


def init():
    with _LOCK, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS signatures(
            sig TEXT PRIMARY KEY, name TEXT, severity TEXT, count INTEGER DEFAULT 0,
            first_seen TEXT, last_seen TEXT
        );
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS activity(
            rowid_ INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT, ts REAL, whenstr TEXT, type TEXT, intent TEXT, target TEXT,
            user TEXT, status TEXT, data TEXT
        );
        CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, user TEXT, action TEXT, detail TEXT
        );
        CREATE TABLE IF NOT EXISTS reports(
            id TEXT PRIMARY KEY, kind TEXT, intent TEXT, target TEXT,
            ts REAL, whenstr TEXT, report TEXT
        );
        CREATE TABLE IF NOT EXISTS playbooks(
            id TEXT PRIMARY KEY, data TEXT
        );
        CREATE TABLE IF NOT EXISTS roles(
            email TEXT PRIMARY KEY, role TEXT
        );
        -- 🍯 Deception layer. Deliberately SEPARATE from `signatures`:
        -- `signatures` records posture ("this target HAS a weakness", from our
        -- Red Team). These record behaviour ("someone ATTEMPTED this", from the
        -- honeypots) and are attacker-controlled by definition — mixing them
        -- would corrupt the posture stats and let an attacker write our KB.
        CREATE TABLE IF NOT EXISTS hp_pots(
            id TEXT PRIMARY KEY, kind TEXT, url TEXT, token TEXT,
            cursor INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1,
            last_poll TEXT, last_error TEXT, added TEXT
        );
        CREATE TABLE IF NOT EXISTS hp_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pot TEXT, ts REAL, whenstr TEXT, src_ip TEXT, method TEXT,
            path TEXT, ua TEXT, technique TEXT, severity TEXT, blob TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_hp_ev_ts  ON hp_events(ts DESC);
        CREATE INDEX IF NOT EXISTS idx_hp_ev_ip  ON hp_events(src_ip);
        CREATE INDEX IF NOT EXISTS idx_hp_ev_tec ON hp_events(technique);
        CREATE TABLE IF NOT EXISTS hp_signatures(
            sig TEXT PRIMARY KEY, name TEXT, severity TEXT, count INTEGER DEFAULT 0,
            sources INTEGER DEFAULT 0, first_seen TEXT, last_seen TEXT
        );
        """)
    _migrate_from_json()


# ------------------------------------------------------------- learning KB ---
def load_kb():
    with _LOCK, _conn() as c:
        runs = c.execute("SELECT v FROM meta WHERE k='runs'").fetchone()
        runs = int(runs["v"]) if runs else 0
        sigs = {}
        for r in c.execute("SELECT * FROM signatures"):
            sigs[r["sig"]] = {"name": r["name"], "severity": r["severity"],
                              "count": r["count"], "first_seen": r["first_seen"],
                              "last_seen": r["last_seen"]}
        return {"runs": runs, "signatures": sigs}


def update_kb(threats, when):
    with _LOCK, _conn() as c:
        row = c.execute("SELECT v FROM meta WHERE k='runs'").fetchone()
        runs = (int(row["v"]) if row else 0) + 1
        c.execute("INSERT INTO meta(k,v) VALUES('runs',?) "
                  "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (str(runs),))
        new_this_run = []
        for t in threats:
            sig = t["signature"]
            ex = c.execute("SELECT count FROM signatures WHERE sig=?", (sig,)).fetchone()
            if ex:
                c.execute("UPDATE signatures SET count=count+1, last_seen=? WHERE sig=?", (when, sig))
            else:
                c.execute("INSERT INTO signatures(sig,name,severity,count,first_seen,last_seen) "
                          "VALUES(?,?,?,1,?,?)", (sig, t["name"], t["severity"], when, when))
                new_this_run.append(t["name"])
        top = [dict(r) for r in c.execute(
            "SELECT name,count,severity FROM signatures ORDER BY count DESC LIMIT 5")]
        total = c.execute("SELECT COUNT(*) n FROM signatures").fetchone()["n"]
    return {"runs": runs, "total_signatures": total,
            "new_this_run": new_this_run, "top": top}


# ------------------------------------------------------------ activity feed --
def add_activity(entry):
    with _LOCK, _conn() as c:
        c.execute("INSERT INTO activity(id,ts,whenstr,type,intent,target,user,status,data) "
                  "VALUES(?,?,?,?,?,?,?,?,?)",
                  (entry.get("id"), entry.get("ts"), entry.get("when"), entry.get("type"),
                   entry.get("intent"), entry.get("target"), entry.get("user"),
                   entry.get("status"), json.dumps(entry, ensure_ascii=False)))
        # keep last 500
        c.execute("DELETE FROM activity WHERE rowid_ NOT IN "
                  "(SELECT rowid_ FROM activity ORDER BY rowid_ DESC LIMIT 500)")


def list_activity():
    """Oldest -> newest (matches the old JSON list order)."""
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT data FROM activity ORDER BY rowid_ ASC").fetchall()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["data"]))
        except Exception:
            pass
    return out


# --------------------------------------------------------------- audit trail -
def add_audit(ts, user, action, detail):
    with _LOCK, _conn() as c:
        c.execute("INSERT INTO audit(ts,user,action,detail) VALUES(?,?,?,?)",
                  (ts, user, action, detail))


def list_audit(limit=500):
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT ts,user,action,detail FROM audit "
                         "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ reports --
def save_report(rid, kind, intent, target, report, ts=None, whenstr=""):
    with _LOCK, _conn() as c:
        c.execute("INSERT INTO reports(id,kind,intent,target,ts,whenstr,report) "
                  "VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET report=excluded.report",
                  (rid, kind, intent, target, ts or time.time(), whenstr, report))


def get_report(rid):
    with _LOCK, _conn() as c:
        r = c.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
    if not r:
        return None
    return {"meta": {"id": r["id"], "kind": r["kind"], "intent": r["intent"],
                     "target": r["target"], "ts": r["ts"], "when": r["whenstr"]},
            "report": r["report"]}


def list_reports(limit=200):
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT id,kind,intent,target,ts,whenstr FROM reports "
                         "ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r["id"], "kind": r["kind"], "intent": r["intent"],
             "target": r["target"], "ts": r["ts"], "when": r["whenstr"]} for r in rows]


def all_reports_full(limit=500):
    """Full reports (meta + body) for export (e.g. to Obsidian)."""
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT * FROM reports ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [{"meta": {"id": r["id"], "kind": r["kind"], "intent": r["intent"],
                      "target": r["target"], "ts": r["ts"], "when": r["whenstr"]},
             "report": r["report"]} for r in rows]


# -------------------------------------------------- custom playbooks (agent) --
def list_playbooks():
    """User-defined data playbooks (list of dicts)."""
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT data FROM playbooks ORDER BY id").fetchall()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["data"]))
        except Exception:
            pass
    return out


def save_playbook(pb):
    with _LOCK, _conn() as c:
        c.execute("INSERT INTO playbooks(id,data) VALUES(?,?) "
                  "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                  (pb["id"], json.dumps(pb, ensure_ascii=False)))


def delete_playbook(pid):
    with _LOCK, _conn() as c:
        c.execute("DELETE FROM playbooks WHERE id=?", (pid,))


# -------------------------------------------------------- roles (RBAC) --------
def get_role(email):
    with _LOCK, _conn() as c:
        r = c.execute("SELECT role FROM roles WHERE email=?", (email,)).fetchone()
    return r["role"] if r else None


def set_role(email, role):
    with _LOCK, _conn() as c:
        c.execute("INSERT INTO roles(email,role) VALUES(?,?) "
                  "ON CONFLICT(email) DO UPDATE SET role=excluded.role", (email, role))


def list_roles():
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT email,role FROM roles").fetchall()
    return {r["email"]: r["role"] for r in rows}


def delete_role(email):
    with _LOCK, _conn() as c:
        c.execute("DELETE FROM roles WHERE email=?", (email,))


# ------------------------------------------------- 🍯 deception layer ---------
def hp_list_pots():
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT id,kind,url,cursor,enabled,last_poll,last_error,added "
                         "FROM hp_pots ORDER BY added").fetchall()
    return [dict(r) for r in rows]          # note: token deliberately not selected


def hp_get_pot(pid):
    with _LOCK, _conn() as c:
        r = c.execute("SELECT * FROM hp_pots WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


def hp_save_pot(pid, kind, url, token, enabled=1, added=""):
    """Upsert a pot. An empty token keeps the stored one (so the UI can edit a
    pot without the secret ever being sent back to the browser)."""
    with _LOCK, _conn() as c:
        if token:
            c.execute("INSERT INTO hp_pots(id,kind,url,token,enabled,added) VALUES(?,?,?,?,?,?) "
                      "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, url=excluded.url, "
                      "token=excluded.token, enabled=excluded.enabled",
                      (pid, kind, url, token, enabled, added))
        else:
            c.execute("INSERT INTO hp_pots(id,kind,url,token,enabled,added) VALUES(?,?,?,'',?,?) "
                      "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, url=excluded.url, "
                      "enabled=excluded.enabled", (pid, kind, url, enabled, added))


def hp_delete_pot(pid):
    with _LOCK, _conn() as c:
        c.execute("DELETE FROM hp_pots WHERE id=?", (pid,))


def hp_set_cursor(pid, cursor, last_poll, last_error=""):
    with _LOCK, _conn() as c:
        c.execute("UPDATE hp_pots SET cursor=?, last_poll=?, last_error=? WHERE id=?",
                  (cursor, last_poll, last_error, pid))


def hp_add_events(rows):
    """Bulk-insert classified events. rows: list of dicts. Returns count added."""
    if not rows:
        return 0
    with _LOCK, _conn() as c:
        c.executemany(
            "INSERT INTO hp_events(pot,ts,whenstr,src_ip,method,path,ua,technique,severity,blob) "
            "VALUES(:pot,:ts,:when,:src_ip,:method,:path,:ua,:technique,:severity,:blob)", rows)
        # cap the table — a honeypot under a flood must not fill the disk
        c.execute("DELETE FROM hp_events WHERE id NOT IN "
                  "(SELECT id FROM hp_events ORDER BY id DESC LIMIT 20000)")
    return len(rows)


def hp_list_events(limit=200, technique=None, src_ip=None):
    q = ("SELECT pot,ts,whenstr,src_ip,method,path,ua,technique,severity,blob "
         "FROM hp_events WHERE 1=1")
    args = []
    if technique:
        q += " AND technique=?"
        args.append(technique)
    if src_ip:
        q += " AND src_ip=?"
        args.append(src_ip)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(min(1000, max(1, limit)))
    with _LOCK, _conn() as c:
        return [dict(r) for r in c.execute(q, args)]


def hp_update_signatures(techniques, when):
    """Accumulate observed-attack signatures. Mirrors update_kb, but writes the
    honeypot table — these are attacker-controlled and must never be mixed into
    the Red Team's posture KB."""
    new = []
    with _LOCK, _conn() as c:
        for t in techniques:
            sig = t["signature"]
            ex = c.execute("SELECT count FROM hp_signatures WHERE sig=?", (sig,)).fetchone()
            if ex:
                c.execute("UPDATE hp_signatures SET count=count+?, last_seen=? WHERE sig=?",
                          (t.get("count", 1), when, sig))
            else:
                c.execute("INSERT INTO hp_signatures(sig,name,severity,count,sources,"
                          "first_seen,last_seen) VALUES(?,?,?,?,?,?,?)",
                          (sig, t["name"], t["severity"], t.get("count", 1),
                           t.get("sources", 1), when, when))
                new.append(t["name"])
    return new


def hp_stats():
    with _LOCK, _conn() as c:
        total = c.execute("SELECT COUNT(*) n FROM hp_events").fetchone()["n"]
        attackers = c.execute("SELECT COUNT(DISTINCT src_ip) n FROM hp_events").fetchone()["n"]
        day = c.execute("SELECT COUNT(*) n FROM hp_events WHERE ts > ?",
                        (time.time() - 86400,)).fetchone()["n"]
        top_tec = [dict(r) for r in c.execute(
            "SELECT technique, severity, COUNT(*) n FROM hp_events "
            "WHERE technique IS NOT NULL AND technique!='' "
            "GROUP BY technique ORDER BY n DESC LIMIT 10")]
        top_ip = [dict(r) for r in c.execute(
            "SELECT src_ip, COUNT(*) n, MAX(whenstr) last FROM hp_events "
            "GROUP BY src_ip ORDER BY n DESC LIMIT 10")]
        sigs = [dict(r) for r in c.execute(
            "SELECT sig,name,severity,count,first_seen,last_seen FROM hp_signatures "
            "ORDER BY count DESC")]
    return {"events": total, "attackers": attackers, "events_24h": day,
            "top_techniques": top_tec, "top_attackers": top_ip, "signatures": sigs}


def hp_correlate():
    """🔥 Cross the two knowledge bases — the reason the honeypot tier exists.

    `signatures`    = what OUR scans say is weak here          (posture)
    `hp_signatures` = what attackers are ACTUALLY attempting   (behaviour)

    A technique under active attempt against a weakness we already know we have
    is not "another finding in a list" — it is a threat-informed priority. The
    mapping is by shared ATT&CK-style intent, not by id, since the two KBs are
    keyed differently by design.
    """
    # attack technique -> the posture signatures it would exploit
    LINK = {
        "sqli-attempt":    ["injection", "waf-absent"],
        "xss-attempt":     ["injection", "waf-absent", "missing-security-header"],
        "rce-attempt":     ["outdated-software", "waf-absent"],
        "log4shell":       ["outdated-software"],
        "shellshock":      ["outdated-software"],
        "path-traversal":  ["exposed-path", "waf-absent"],
        "secret-hunt":     ["exposed-path", "directory-indexing"],
        "cred-attack":     ["ssh-exposed", "rdp-exposed", "no-tls"],
        "cms-probe":       ["exposed-path", "default-file", "outdated-software"],
        "scanner-recon":   ["open-port-generic", "waf-absent"],
        "webshell-upload": ["exposed-path", "outdated-software"],
        "ssrf-metadata":   ["waf-absent"],
        "xxe-attempt":     ["injection", "outdated-software"],
        # SQL honeypot (3306): a reachable DB is an open port; abuse of it also
        # implies the software may be outdated / injectable.
        "sql-login":       ["open-port-generic"],
        "sql-file-access": ["open-port-generic", "injection"],
        "sql-udf-rce":     ["open-port-generic", "outdated-software"],
        "sql-enum":        ["open-port-generic"],
        # SSH honeypot (22): brute-force maps straight onto an exposed SSH.
        "ssh-bruteforce":  ["ssh-exposed", "open-port-generic"],
    }
    with _LOCK, _conn() as c:
        posture = {r["sig"]: dict(r) for r in c.execute(
            "SELECT sig,name,severity,count FROM signatures")}
        attacks = {r["sig"]: dict(r) for r in c.execute(
            "SELECT sig,name,severity,count FROM hp_signatures")}
    out = []
    for atk_sig, atk in attacks.items():
        for weak_sig in LINK.get(atk_sig, []):
            w = posture.get(weak_sig)
            if not w:
                continue
            out.append({
                "attack": atk_sig, "attack_name": atk["name"],
                "attack_count": atk["count"], "attack_severity": atk["severity"],
                "weakness": weak_sig, "weakness_name": w["name"],
                "weakness_severity": w["severity"],
            })
    # loudest confirmed threat first
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    out.sort(key=lambda x: (rank.get(x["attack_severity"], 9), -x["attack_count"]))
    return out


def stats():
    with _LOCK, _conn() as c:
        return {
            "signatures": c.execute("SELECT COUNT(*) n FROM signatures").fetchone()["n"],
            "activity": c.execute("SELECT COUNT(*) n FROM activity").fetchone()["n"],
            "audit": c.execute("SELECT COUNT(*) n FROM audit").fetchone()["n"],
            "reports": c.execute("SELECT COUNT(*) n FROM reports").fetchone()["n"],
            "db_file": DB_FILE,
        }


# ----------------------------------------------- one-time import from JSON ---
def _migrate_from_json():
    kj = os.path.join(DATA_DIR, "knowledge.json")
    aj = os.path.join(DATA_DIR, "activity.json")
    al = os.path.join(DATA_DIR, "audit.log")
    rd = os.path.join(DATA_DIR, "reports")
    with _LOCK, _conn() as c:
        if c.execute("SELECT COUNT(*) n FROM signatures").fetchone()["n"] == 0 and os.path.isfile(kj):
            try:
                kb = json.load(open(kj, encoding="utf-8"))
                for sig, v in kb.get("signatures", {}).items():
                    c.execute("INSERT OR IGNORE INTO signatures(sig,name,severity,count,first_seen,last_seen) "
                              "VALUES(?,?,?,?,?,?)", (sig, v.get("name"), v.get("severity"),
                              v.get("count", 0), v.get("first_seen"), v.get("last_seen")))
                c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('runs',?)", (str(kb.get("runs", 0)),))
            except Exception:
                pass
        if c.execute("SELECT COUNT(*) n FROM activity").fetchone()["n"] == 0 and os.path.isfile(aj):
            try:
                for e in json.load(open(aj, encoding="utf-8")):
                    c.execute("INSERT INTO activity(id,ts,whenstr,type,intent,target,user,status,data) "
                              "VALUES(?,?,?,?,?,?,?,?,?)",
                              (e.get("id"), e.get("ts"), e.get("when"), e.get("type"),
                               e.get("intent"), e.get("target"), e.get("user"), e.get("status"),
                               json.dumps(e, ensure_ascii=False)))
            except Exception:
                pass
        if c.execute("SELECT COUNT(*) n FROM audit").fetchone()["n"] == 0 and os.path.isfile(al):
            try:
                for ln in open(al, encoding="utf-8"):
                    p = ln.rstrip("\n").split("\t")
                    if len(p) >= 3:
                        c.execute("INSERT INTO audit(ts,user,action,detail) VALUES(?,?,?,?)",
                                  (p[0], p[1].replace("user=", "", 1),
                                   p[2].replace("action=", "", 1), p[3] if len(p) > 3 else ""))
            except Exception:
                pass
        if c.execute("SELECT COUNT(*) n FROM reports").fetchone()["n"] == 0 and os.path.isdir(rd):
            for fn in os.listdir(rd):
                if not fn.endswith(".json"):
                    continue
                try:
                    d = json.load(open(os.path.join(rd, fn), encoding="utf-8"))
                    m = d.get("meta", {})
                    c.execute("INSERT OR IGNORE INTO reports(id,kind,intent,target,ts,whenstr,report) "
                              "VALUES(?,?,?,?,?,?,?)", (m.get("id", fn[:-5]), m.get("kind"),
                              m.get("intent"), m.get("target"), m.get("ts"), m.get("when"), d.get("report")))
                except Exception:
                    pass
