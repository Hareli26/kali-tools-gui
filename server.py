#!/usr/bin/env python3
"""
Kali Tools GUI - backend
Pure standard library (no pip needed). Runs INSIDE Kali WSL.

Serves the web UI and exposes a small JSON API:
  GET  /api/tools            -> catalog + installed status per tool
  POST /api/run              -> {tool_id, values} -> builds argv, runs, returns job_id
  GET  /api/job/<id>         -> job status + output
  POST /api/job/<id>/stop    -> terminate a running job
  POST /api/install          -> {package, password} -> apt-get install via sudo -S

Command lines are built server-side from tools.json (authoritative) and executed
WITHOUT a shell (argv list) to avoid command injection.
"""

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agents   # noqa: E402  (agent engine: planner / verifier / reporter)
import bluered  # noqa: E402  (purple-team: broker / blue team / learning)
WEB_DIR = os.path.join(HERE, "web")
TOOLS_FILE = os.path.join(HERE, "tools.json")

# Deterministic, safe search path for both detection and execution.
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
RUN_ENV = dict(os.environ)
RUN_ENV["PATH"] = SAFE_PATH + ":" + RUN_ENV.get("PATH", "")

PORT = int(os.environ.get("KALIGUI_PORT", "8777"))
MAX_OUTPUT = 5 * 1024 * 1024  # cap stored output per job (bytes)
STEP_TIMEOUT = int(os.environ.get("KALIGUI_STEP_TIMEOUT", "300"))  # sec per mission step

# ---------------------------------------------------------------- catalog ----
def load_catalog():
    with open(TOOLS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def tool_installed(binary):
    return shutil.which(binary, path=SAFE_PATH) is not None

# ------------------------------------------------------------- job manager ---
JOBS = {}
JOBS_LOCK = threading.Lock()

class Job:
    def __init__(self, argv, label=""):
        self.id = uuid.uuid4().hex[:12]
        self.argv = argv
        self.label = label
        self.output = bytearray()
        self.status = "starting"   # starting | running | done | error | stopped
        self.returncode = None
        self.proc = None
        self.lock = threading.Lock()
        self.stdin_data = None      # optional bytes to feed (sudo password)

    def start(self):
        try:
            self.proc = subprocess.Popen(
                self.argv,
                stdin=subprocess.PIPE if self.stdin_data is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=RUN_ENV,
                cwd="/tmp",
                start_new_session=True,  # own process group -> clean kill
            )
        except FileNotFoundError:
            self.status = "error"
            self._append(("[שגיאה] הכלי לא נמצא: %s\n" % self.argv[0]).encode())
            return
        except Exception as e:  # noqa
            self.status = "error"
            self._append(("[שגיאה] %s\n" % e).encode())
            return
        self.status = "running"
        if self.stdin_data is not None:
            try:
                self.proc.stdin.write(self.stdin_data)
                self.proc.stdin.close()
            except Exception:
                pass
        threading.Thread(target=self._pump, daemon=True).start()

    def _append(self, data: bytes):
        with self.lock:
            if len(self.output) < MAX_OUTPUT:
                self.output.extend(data)
                if len(self.output) >= MAX_OUTPUT:
                    self.output.extend("\n[... הפלט נחתך: הגעת למגבלת הגודל ...]\n".encode("utf-8"))

    def _pump(self):
        try:
            for chunk in iter(lambda: self.proc.stdout.read(1024), b""):
                self._append(chunk)
        except Exception:
            pass
        self.returncode = self.proc.wait()
        if self.status != "stopped":
            self.status = "done" if self.returncode == 0 else "error"

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.status = "stopped"
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                time.sleep(0.3)
                if self.proc.poll() is None:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass

    def snapshot(self):
        with self.lock:
            text = self.output.decode("utf-8", "replace")
        return {
            "id": self.id,
            "status": self.status,
            "returncode": self.returncode,
            "argv": self.argv,
            "command": " ".join(shlex.quote(a) for a in self.argv),
            "output": text,
        }

# -------------------------------------------------------- command builder ----
def build_argv(tool, values):
    """Build an argv list from a tool spec + user values. Raises ValueError."""
    argv = [tool["binary"]]
    positional = None
    for opt in tool.get("options", []):
        oid = opt["id"]
        flag = opt.get("flag", "")
        otype = opt.get("type", "text")
        raw = values.get(oid, None)

        if otype == "bool":
            if raw is True or raw == "true" or raw == "on":
                if flag:
                    argv.append(flag)
            continue

        val = "" if raw is None else str(raw).strip()
        if val == "":
            if opt.get("required"):
                raise ValueError("שדה חובה חסר: %s" % opt.get("label", oid))
            continue
        if "\x00" in val:
            raise ValueError("ערך לא חוקי")

        if flag == "":
            if opt.get("primary"):
                positional = val
            else:
                argv.append(val)          # value-as-token (e.g. nmap -sS, dig MX)
        elif opt.get("eq"):
            argv.append("%s=%s" % (flag, val))
        else:
            argv.append(flag)
            argv.append(val)

    # required positional-primary check (only for flag-less primaries;
    # primaries that carry a flag are validated by the empty-value check above)
    for opt in tool.get("options", []):
        if opt.get("primary") and opt.get("flag", "") == "" and opt.get("required") and positional is None:
            raise ValueError("שדה חובה חסר: %s" % opt.get("label", opt["id"]))

    extra = values.get("_extra", "")
    if extra and str(extra).strip():
        argv.extend(shlex.split(str(extra)))

    if positional is not None:
        argv.append(positional)
    return argv

def find_tool(tool_id, catalog=None):
    cat = catalog or load_catalog()
    return next((t for t in cat["tools"] if t["id"] == tool_id), None)

def enrich_step(step, catalog=None):
    """Add tool_name / command / installed to a planner step (for display)."""
    tool = find_tool(step["tool_id"], catalog)
    step = dict(step)
    if not tool:
        step.update(tool_name=step["tool_id"], command="", installed=False)
        return step
    step["tool_name"] = tool["name"]
    step["installed"] = tool_installed(tool["binary"])
    try:
        argv = build_argv(tool, step.get("values", {}))
        step["command"] = " ".join(shlex.quote(a) for a in argv)
    except ValueError:
        step["command"] = tool["binary"] + " ..."
    return step

# -------------------------------------------------------- mission manager ----
MISSIONS = {}
MISSIONS_LOCK = threading.Lock()

class Mission:
    """Executor + Verifier + Reporter orchestration over a plan of steps."""
    def __init__(self, intent, target, steps, do_log=True):
        self.id = uuid.uuid4().hex[:12]
        self.intent = intent
        self.target = target
        self.do_log = do_log
        self.steps = []
        for s in steps:
            self.steps.append({
                "tool_id": s["tool_id"], "tool_name": s.get("tool_name", s["tool_id"]),
                "why": s.get("why", ""), "values": s.get("values", {}),
                "command": s.get("command", ""), "status": "pending",
                "verdict": None, "output": "", "returncode": None,
            })
        self.status = "running"
        self.current = -1
        self.report = None
        self._stop = False
        self._curjob = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        cat = load_catalog()
        for i, s in enumerate(self.steps):
            if self._stop:
                break
            self.current = i
            s["status"] = "running"
            tool = find_tool(s["tool_id"], cat)
            if not tool or not tool_installed(tool["binary"]):
                s["status"] = "skipped"
                s["verdict"] = {"verdict": "fail", "label": "לא מותקן",
                                "note": "הכלי אינו מותקן.", "findings": []}
                continue
            try:
                argv = build_argv(tool, s["values"])
            except ValueError as e:
                s["status"] = "error"
                s["verdict"] = {"verdict": "fail", "label": "שגיאת פרמטרים",
                                "note": str(e), "findings": []}
                continue
            job = Job(argv, label=tool["name"])
            with JOBS_LOCK:
                JOBS[job.id] = job
            self._curjob = job
            s["command"] = job.snapshot()["command"]
            job.start()
            started = time.monotonic()
            timed_out = False
            while job.status in ("starting", "running"):
                if self._stop:
                    job.stop()
                    break
                if time.monotonic() - started > STEP_TIMEOUT:
                    timed_out = True
                    job.stop()
                    break
                time.sleep(0.4)
            snap = job.snapshot()
            s["output"] = snap["output"]
            s["returncode"] = snap["returncode"]
            s["status"] = "done"
            if timed_out:
                vd = agents.verify(s["tool_id"], snap)
                s["verdict"] = {"verdict": "warn", "label": "חריגת זמן",
                                "note": "השלב נעצר לאחר %d שניות. ניתן להריץ אותו ידנית עם פרמטרים ממוקדים יותר." % STEP_TIMEOUT,
                                "findings": vd.get("findings", [])}
            else:
                s["verdict"] = agents.verify(s["tool_id"], snap)
            self._curjob = None

        self.status = "stopped" if self._stop else "done"
        when = datetime.now().strftime("%Y-%m-%d %H:%M")
        payload = {"intent": self.intent, "target": self.target, "steps": self.steps}
        self.report = agents.llm_report(payload, when) or agents.report(payload, when)
        if self.do_log:
            findings = sum(len((s.get("verdict") or {}).get("findings", [])) for s in self.steps)
            bluered.log_activity({
                "ts": time.time(), "when": when, "type": "mission",
                "intent": self.intent, "target": self.target,
                "steps": len(self.steps), "findings": findings, "status": self.status,
            })

    def stop(self):
        self._stop = True
        if self._curjob:
            self._curjob.stop()

    def snapshot(self):
        return {
            "id": self.id, "intent": self.intent, "target": self.target,
            "status": self.status, "current": self.current, "report": self.report,
            "steps": [{
                "tool_id": s["tool_id"], "tool_name": s["tool_name"], "why": s["why"],
                "command": s["command"], "status": s["status"], "verdict": s["verdict"],
                "output": (s["output"][-4000:] if s["output"] else ""),
            } for s in self.steps],
        }

# -------------------------------------------------- purple-team orchestrator -
PURPLE = {}
PURPLE_LOCK = threading.Lock()

class PurpleMission:
    """🟣 Orchestrator: runs the Red mission, then Broker + Blue Team + learning."""
    def __init__(self, intent, target, steps):
        self.id = uuid.uuid4().hex[:12]
        self.intent = intent
        self.target = target
        self.mission = Mission(intent, target, steps, do_log=False)
        self.phase = "red"          # red | blue | done
        self.status = "running"
        self.threats = []
        self.learning = None
        self.report = None
        self._stop = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        # 🔴 Red phase — reuse the mission executor + verifier
        self.mission.start()
        while self.mission.status == "running":
            if self._stop:
                self.mission.stop()
            time.sleep(0.5)

        # 🟢 Broker — collect & correlate red findings
        self.phase = "blue"
        red = []
        for s in self.mission.steps:
            vd = s.get("verdict") or {}
            for f in vd.get("findings", []):
                red.append({"tool": s["tool_name"], "text": f})
        self.threats = bluered.broker(red)

        # 🧠 Learning + 🟣 report
        when = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.learning = bluered.update_kb(self.threats, when)
        self.report = bluered.purple_report(self.intent, self.target,
                                            self.mission.steps, self.threats, self.learning, when)
        self.phase = "done"
        self.status = "stopped" if self._stop else "done"
        red_findings = sum(len((s.get("verdict") or {}).get("findings", []))
                           for s in self.mission.steps)
        top_sev = self.threats[0]["severity"] if self.threats else None
        bluered.log_activity({
            "ts": time.time(), "when": when, "type": "purple",
            "intent": self.intent, "target": self.target,
            "red_findings": red_findings, "threats": len(self.threats),
            "severity": top_sev,
            "threat_sigs": [t["signature"] for t in self.threats],
            "new_learned": (self.learning or {}).get("new_this_run", []),
            "status": self.status,
        })

    def stop(self):
        self._stop = True
        self.mission.stop()

    def snapshot(self):
        return {
            "id": self.id, "intent": self.intent, "target": self.target,
            "phase": self.phase, "status": self.status,
            "red": self.mission.snapshot(),
            "threats": self.threats,
            "learning": self.learning,
            "report": self.report,
        }

# ---------------------------------------------------------------- handler ----
class Handler(BaseHTTPRequestHandler):
    server_version = "KaliGUI/1.0"

    def log_message(self, fmt, *args):
        pass  # quiet

    # -- helpers --
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        # prevent traversal
        safe = os.path.normpath(path).lstrip("/\\")
        full = os.path.join(WEB_DIR, safe)
        if not os.path.abspath(full).startswith(os.path.abspath(WEB_DIR)) or not os.path.isfile(full):
            self.send_error(404, "Not found")
            return
        ctypes = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
                  ".svg": "image/svg+xml", ".ico": "image/x-icon"}
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctypes.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- routing --
    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p == "/api/tools":
            return self._api_tools()
        if p == "/api/env":
            return self._api_env()
        if p == "/api/knowledge":
            return self._send_json(bluered.load_kb())
        if p == "/api/dashboard":
            return self._api_dashboard()
        if p.startswith("/api/threat/"):
            return self._api_threat(p.rsplit("/", 1)[-1])
        if p.startswith("/api/purple/"):
            return self._api_purple_get(p.rsplit("/", 1)[-1])
        if p.startswith("/api/mission/"):
            return self._api_mission_get(p.rsplit("/", 1)[-1])
        if p.startswith("/api/job/"):
            return self._api_job(p.rsplit("/", 1)[-1])
        return self._serve_static(p)

    def do_POST(self):
        p = self.path.split("?", 1)[0]
        if p == "/api/run":
            return self._api_run()
        if p == "/api/install":
            return self._api_install()
        if p == "/api/plan":
            return self._api_plan()
        if p == "/api/mission":
            return self._api_mission_start()
        if p == "/api/purple":
            return self._api_purple_start()
        if p.startswith("/api/purple/") and p.endswith("/stop"):
            pid = p[len("/api/purple/"):-len("/stop")]
            return self._api_purple_stop(pid)
        if p.startswith("/api/mission/") and p.endswith("/stop"):
            mid = p[len("/api/mission/"):-len("/stop")]
            return self._api_mission_stop(mid)
        if p.startswith("/api/job/") and p.endswith("/stop"):
            jid = p[len("/api/job/"):-len("/stop")]
            return self._api_stop(jid)
        self.send_error(404, "Not found")

    # -- env / agents --
    def _api_env(self):
        return self._send_json({
            "is_root": (hasattr(os, "geteuid") and os.geteuid() == 0),
            "llm": bool(os.environ.get("OLLAMA_URL") and os.environ.get("OLLAMA_MODEL")),
        })

    def _api_dashboard(self):
        # --- live agent status derived from running missions/purple runs ---
        with PURPLE_LOCK:
            purples = list(PURPLE.values())
        with MISSIONS_LOCK:
            missions = list(MISSIONS.values())
        run_purple = next((p for p in purples if p.status == "running"), None)
        run_mission = next((m for m in missions if m.status == "running"), None)

        kb = bluered.load_kb()
        sigs = kb.get("signatures", {})

        def A(icon, name, role, status, detail):
            return {"icon": icon, "name": name, "role": role, "status": status, "detail": detail}

        if run_purple:
            rp = run_purple
            cur = rp.mission.snapshot()
            cur_tool = ""
            if 0 <= cur.get("current", -1) < len(cur["steps"]):
                cur_tool = cur["steps"][cur["current"]]["tool_name"]
            if rp.phase == "red":
                agents_state = [
                    A("🔴", "צוות אדום", "תקיפה וגילוי פרצות", "active", f"מריץ {cur_tool} על {rp.target}"),
                    A("🟢", "מתווך", "תיווך ממצאים לצוות הכחול", "idle", "ממתין לסיום התקיפה"),
                    A("🔵", "צוות כחול", "הגנה, חסימה וניטור", "idle", "ממתין"),
                    A("🧠", "סוכן למידה", "צבירת ידע בין הרצות", "idle", f"{len(sigs)} סוגי ממצאים ידועים"),
                    A("🟣", "מתזמר", "ניצוח, תזמון ודיווח", "active", f"מנצח משימה על {rp.target}"),
                ]
            else:
                agents_state = [
                    A("🔴", "צוות אדום", "תקיפה וגילוי פרצות", "done", "סיים איסוף ממצאים"),
                    A("🟢", "מתווך", "תיווך ממצאים לצוות הכחול", "active", "ממפה ממצאים להגנות"),
                    A("🔵", "צוות כחול", "הגנה, חסימה וניטור", "active", "מייצר תוכנית הגנה"),
                    A("🧠", "סוכן למידה", "צבירת ידע בין הרצות", "active", "מעדכן בסיס ידע"),
                    A("🟣", "מתזמר", "ניצוח, תזמון ודיווח", "active", "מרכיב דוח"),
                ]
        elif run_mission:
            agents_state = [
                A("🔴", "צוות אדום", "תקיפה וגילוי פרצות", "active", f"מריץ משימה על {run_mission.target}"),
                A("🟢", "מתווך", "תיווך ממצאים לצוות הכחול", "idle", "לא פעיל במצב זה"),
                A("🔵", "צוות כחול", "הגנה, חסימה וניטור", "idle", "לא פעיל במצב זה"),
                A("🧠", "סוכן למידה", "צבירת ידע בין הרצות", "idle", f"{len(sigs)} סוגי ממצאים ידועים"),
                A("🟣", "מתזמר", "ניצוח, תזמון ודיווח", "active", "מנצח משימה"),
            ]
        else:
            agents_state = [
                A("🔴", "צוות אדום", "תקיפה וגילוי פרצות", "idle", "ממתין למשימה"),
                A("🟢", "מתווך", "תיווך ממצאים לצוות הכחול", "idle", "ממתין"),
                A("🔵", "צוות כחול", "הגנה, חסימה וניטור", "idle", "ממתין"),
                A("🧠", "סוכן למידה", "צבירת ידע בין הרצות", "idle", f"{len(sigs)} סוגי ממצאים ידועים"),
                A("🟣", "מתזמר", "ניצוח, תזמון ודיווח", "idle", "ממתין"),
            ]

        # --- intelligence stats from the learning KB ---
        sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for s in sigs.values():
            sev_counts[s.get("severity", "low")] = sev_counts.get(s.get("severity", "low"), 0) + 1
        top = sorted(sigs.items(), key=lambda kv: -kv[1]["count"])[:6]
        top_list = [{"signature": kid, "name": v["name"], "count": v["count"],
                     "severity": v["severity"], "last_seen": v.get("last_seen", "")}
                    for kid, v in top]

        activity = list(reversed(bluered.load_activity()))[:25]

        cat = load_catalog()
        installed = sum(1 for t in cat["tools"] if tool_installed(t["binary"]))

        return self._send_json({
            "agents": agents_state,
            "live": bool(run_purple or run_mission),
            "knowledge": {
                "runs": kb.get("runs", 0),
                "total_signatures": len(sigs),
                "severity": sev_counts,
                "top": top_list,
            },
            "activity": activity,
            "tools": {"installed": installed, "total": len(cat["tools"])},
        })

    def _api_threat(self, sig):
        from urllib.parse import unquote
        sig = unquote(sig)
        rule = bluered.get_defense(sig)
        if not rule:
            return self._send_json({"error": "איום לא ידוע"}, 404)
        kb = bluered.load_kb()
        rec = kb.get("signatures", {}).get(sig, {})
        # occurrences: purple runs where this signature appeared
        occ = []
        for a in reversed(bluered.load_activity()):
            if a.get("type") == "purple" and sig in (a.get("threat_sigs") or []):
                occ.append({"when": a.get("when", ""), "ts": a.get("ts"),
                            "target": a.get("target", ""), "intent": a.get("intent", "")})
        return self._send_json({
            "signature": sig,
            "name": rule["name"], "severity": rule["severity"], "threat": rule["threat"],
            "defenses": rule["defenses"], "detections": rule["detections"],
            "config": rule.get("config", ""), "mitre": rule.get("mitre", ""),
            "count": rec.get("count", 0), "first_seen": rec.get("first_seen", ""),
            "last_seen": rec.get("last_seen", ""),
            "occurrences": occ,
        })

    def _api_plan(self):
        data = self._read_json()
        intent = (data.get("intent") or "").strip()
        target = (data.get("target") or "").strip()
        if not intent or not target:
            return self._send_json({"error": "יש להזין כוונה ומטרה"}, 400)
        result = agents.plan(intent, target)
        cat = load_catalog()
        result["steps"] = [enrich_step(s, cat) for s in result["steps"]]
        return self._send_json(result)

    def _api_mission_start(self):
        data = self._read_json()
        intent = (data.get("intent") or "").strip()
        target = (data.get("target") or "").strip()
        steps = data.get("steps") or []
        if not steps:
            return self._send_json({"error": "אין שלבים להרצה"}, 400)
        cat = load_catalog()
        steps = [enrich_step(s, cat) for s in steps]
        mission = Mission(intent, target, steps)
        with MISSIONS_LOCK:
            MISSIONS[mission.id] = mission
        mission.start()
        return self._send_json({"mission_id": mission.id})

    def _api_mission_get(self, mid):
        with MISSIONS_LOCK:
            m = MISSIONS.get(mid)
        if not m:
            return self._send_json({"error": "משימה לא נמצאה"}, 404)
        return self._send_json(m.snapshot())

    def _api_mission_stop(self, mid):
        with MISSIONS_LOCK:
            m = MISSIONS.get(mid)
        if not m:
            return self._send_json({"error": "משימה לא נמצאה"}, 404)
        m.stop()
        return self._send_json({"ok": True})

    # -- purple team --
    def _api_purple_start(self):
        data = self._read_json()
        intent = (data.get("intent") or "").strip()
        target = (data.get("target") or "").strip()
        steps = data.get("steps") or []
        if not steps:
            return self._send_json({"error": "אין שלבים להרצה"}, 400)
        cat = load_catalog()
        steps = [enrich_step(s, cat) for s in steps]
        pm = PurpleMission(intent, target, steps)
        with PURPLE_LOCK:
            PURPLE[pm.id] = pm
        pm.start()
        return self._send_json({"purple_id": pm.id})

    def _api_purple_get(self, pid):
        with PURPLE_LOCK:
            pm = PURPLE.get(pid)
        if not pm:
            return self._send_json({"error": "משימת Purple לא נמצאה"}, 404)
        return self._send_json(pm.snapshot())

    def _api_purple_stop(self, pid):
        with PURPLE_LOCK:
            pm = PURPLE.get(pid)
        if not pm:
            return self._send_json({"error": "משימת Purple לא נמצאה"}, 404)
        pm.stop()
        return self._send_json({"ok": True})

    # -- endpoints --
    def _api_tools(self):
        cat = load_catalog()
        for t in cat["tools"]:
            t["installed"] = tool_installed(t["binary"])
        return self._send_json(cat)

    def _api_run(self):
        data = self._read_json()
        tool_id = data.get("tool_id")
        values = data.get("values", {}) or {}
        cat = load_catalog()
        tool = next((t for t in cat["tools"] if t["id"] == tool_id), None)
        if not tool:
            return self._send_json({"error": "כלי לא ידוע"}, 400)
        if not tool_installed(tool["binary"]):
            return self._send_json({"error": "הכלי אינו מותקן: %s" % tool["binary"],
                                    "not_installed": True, "package": tool.get("package")}, 409)
        try:
            argv = build_argv(tool, values)
        except ValueError as e:
            return self._send_json({"error": str(e)}, 400)
        job = Job(argv, label=tool["name"])
        with JOBS_LOCK:
            JOBS[job.id] = job
        job.start()
        return self._send_json({"job_id": job.id, "command": job.snapshot()["command"]})

    def _api_job(self, jid):
        with JOBS_LOCK:
            job = JOBS.get(jid)
        if not job:
            return self._send_json({"error": "job לא נמצא"}, 404)
        return self._send_json(job.snapshot())

    def _api_stop(self, jid):
        with JOBS_LOCK:
            job = JOBS.get(jid)
        if not job:
            return self._send_json({"error": "job לא נמצא"}, 404)
        job.stop()
        return self._send_json(job.snapshot())

    def _api_install(self):
        data = self._read_json()
        pkg = (data.get("package") or "").strip()
        password = data.get("password", "")
        # allow only simple package names
        if not pkg or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.+" for c in pkg):
            return self._send_json({"error": "שם חבילה לא חוקי"}, 400)
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        if is_root:
            argv = ["apt-get", "install", "-y", pkg]
            job = Job(argv, label="התקנה: %s" % pkg)
        else:
            argv = ["sudo", "-S", "-p", "", "apt-get", "install", "-y", pkg]
            job = Job(argv, label="התקנה: %s" % pkg)
            job.stdin_data = ((password or "") + "\n").encode()
        env2 = dict(RUN_ENV)
        env2["DEBIAN_FRONTEND"] = "noninteractive"
        with JOBS_LOCK:
            JOBS[job.id] = job
        # temporarily swap env for this job via closure
        orig = globals()["RUN_ENV"]
        try:
            globals()["RUN_ENV"] = env2
            job.start()
        finally:
            globals()["RUN_ENV"] = orig
        return self._send_json({"job_id": job.id})

def main():
    if not os.path.isdir(WEB_DIR):
        raise SystemExit("web/ directory missing next to server.py")
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("Kali Tools GUI running:  http://localhost:%d" % PORT)
    print("Serving from: %s" % HERE)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nמכבה...")

if __name__ == "__main__":
    main()
