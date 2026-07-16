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
