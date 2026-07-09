#!/usr/bin/env python3
"""
MCP server for Kali Tools GUI.

Exposes the running Kali Tools GUI (its REST API) as MCP tools so an MCP client
(Claude Desktop, Claude Code, etc.) can drive the pentest console in natural
language: list/run tools, plan checks, run missions and Purple-Team runs, and
read reports, dashboard and the learning knowledge base.

It is a thin client over the HTTP API — point it at a local instance
(http://127.0.0.1:8777) or an SSH-tunnelled remote one.

Requires:  pip install mcp        (see mcp/requirements.txt)
Config:    KALIGUI_URL   (default http://127.0.0.1:8777)
           KALIGUI_TOKEN (optional, if the app is started with a token)
"""
import json
import os
import re
import time
import urllib.request

from mcp.server.fastmcp import FastMCP

BASE = os.environ.get("KALIGUI_URL", "http://127.0.0.1:8777").rstrip("/")
TOKEN = os.environ.get("KALIGUI_TOKEN", "")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

mcp = FastMCP("kali-tools-gui")


def _api(method, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if TOKEN:
        req.add_header("X-KaliGUI-Token", TOKEN)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _clean(s):
    return _ANSI.sub("", s or "")


@mcp.tool()
def list_tools(category: str = "") -> str:
    """List available Kali tools (name, binary, category, installed status).
    Optionally filter by category id (recon, dns, netscan, web, smb, passwords,
    ssl, exploit, forensics, wireless, util)."""
    cat = _api("GET", "/api/tools")
    out = []
    for t in cat["tools"]:
        if category and t.get("category") != category:
            continue
        mark = "✓" if t.get("installed") else "✗ (missing)"
        out.append(f"{mark} {t['name']} [{t['binary']}] · {t['category']} — {t['desc']}")
    return "\n".join(out) or "no tools match"


@mcp.tool()
def tool_options(tool_id: str) -> str:
    """Show the form fields/options for a specific tool id, so you know what
    'values' to pass to run_tool."""
    cat = _api("GET", "/api/tools")
    t = next((x for x in cat["tools"] if x["id"] == tool_id), None)
    if not t:
        return f"unknown tool id: {tool_id}"
    lines = [f"{t['name']} ({t['binary']}):"]
    for o in t.get("options", []):
        req = " (required)" if o.get("required") else ""
        lines.append(f"  - {o['id']}: {o.get('label','')} [{o.get('type','text')}]{req}")
    lines.append("Example: run_tool(tool_id='%s', values={...})" % tool_id)
    return "\n".join(lines)


@mcp.tool()
def run_tool(tool_id: str, values: dict) -> str:
    """Run a single Kali tool and return its output. `values` maps option ids to
    values, e.g. run_tool('nmap', {'target':'127.0.0.1','sv':true,'topports':'100'}).
    Only run against targets you are authorized to test."""
    r = _api("POST", "/api/run", {"tool_id": tool_id, "values": values})
    if r.get("error"):
        return "Error: " + r["error"]
    jid = r["job_id"]
    j = {}
    for _ in range(150):  # up to ~5 min
        time.sleep(2)
        j = _api("GET", "/api/job/" + jid)
        if j["status"] not in ("running", "starting"):
            break
    return f"$ {r.get('command','')}\nstatus: {j.get('status')}\n\n{_clean(j.get('output',''))[:8000]}"


@mcp.tool()
def plan(intent: str, target: str) -> str:
    """Turn a natural-language intent + target into a plan of tool steps (the
    Planner agent). Does not run anything. e.g. plan('web pentest','example.com')."""
    p = _api("POST", "/api/plan", {"intent": intent, "target": target})
    if p.get("error"):
        return "Error: " + p["error"]
    lines = [f"playbooks: {', '.join(p.get('playbooks', []))}", "steps:"]
    for i, s in enumerate(p.get("steps", []), 1):
        lines.append(f"  {i}. {s['tool_name']}: {s.get('command','')}  — {s.get('why','')}")
    return "\n".join(lines)


def _run_flow(kind, intent, target):
    p = _api("POST", "/api/plan", {"intent": intent, "target": target})
    if p.get("error"):
        return "Error planning: " + p["error"]
    body = {"intent": intent, "target": target, "steps": p["steps"]}
    ep = "/api/purple" if kind == "purple" else "/api/mission"
    idkey = "purple_id" if kind == "purple" else "mission_id"
    r = _api("POST", ep, body)
    if r.get("error"):
        return "Error starting: " + r["error"]
    rid = r[idkey]
    snap = {}
    for _ in range(300):  # up to ~15 min
        time.sleep(3)
        snap = _api("GET", f"{ep}/{rid}")
        if snap.get("status") != "running":
            break
    return snap


@mcp.tool()
def run_mission(intent: str, target: str) -> str:
    """Plan and run a full mission (Executor + Verifier + Reporter) and return the
    Markdown report. e.g. run_mission('port scan','scanme.nmap.org'). Long-running.
    Authorized targets only."""
    snap = _run_flow("mission", intent, target)
    if isinstance(snap, str):
        return snap
    return snap.get("report") or "(no report)"


@mcp.tool()
def run_purple(intent: str, target: str) -> str:
    """Plan and run a Purple-Team assessment: Red finds issues, Blue maps each to
    defenses/detections/MITRE, and a full Purple report is returned. Long-running.
    Authorized targets only."""
    snap = _run_flow("purple", intent, target)
    if isinstance(snap, str):
        return snap
    threats = snap.get("threats", [])
    head = "THREATS: " + ", ".join(f"{t['name']}({t['severity']})" for t in threats)
    return head + "\n\n" + (snap.get("report") or "(no report)")


@mcp.tool()
def get_fix(signature: str) -> str:
    """Show the automated remediation plan for a threat signature (from a purple
    report), including the exact commands and risk level — WITHOUT applying it.
    Use this first, show it to the human, and only call apply_fix after they approve."""
    fx = _api("GET", "/api/fix/" + signature)
    if not fx.get("available"):
        return f"No automated fix for '{signature}'. {fx.get('note','')}"
    return (f"FIX: {fx['title']}\nrisk: {fx['risk']}\nnote: {fx.get('note','')}\n"
            f"commands:\n  " + "\n  ".join(fx.get("commands", [])))


@mcp.tool()
def apply_fix(signature: str, confirm: bool = False) -> str:
    """APPLY the automated remediation for a threat signature ON THE HOST. This
    changes the system (installs/enables services), with automatic config backup.
    REQUIRES confirm=True — only pass it after the human has explicitly approved
    the plan shown by get_fix. Refuses without confirmation."""
    if not confirm:
        return "Refused: apply_fix requires confirm=True after the human approves the get_fix plan."
    r = _api("POST", "/api/fix", {"signature": signature, "confirm": True})
    if r.get("error"):
        return "Error: " + r["error"]
    jid = r["job_id"]
    j = {}
    for _ in range(120):
        time.sleep(2)
        j = _api("GET", "/api/job/" + jid)
        if j["status"] not in ("running", "starting"):
            break
    return f"Applied '{r.get('title','')}' — status {j.get('status')}:\n\n{_clean(j.get('output',''))[:6000]}"


@mcp.tool()
def export_obsidian() -> str:
    """Export all stored reports + the learning knowledge base to an Obsidian vault
    (Markdown notes with frontmatter, threat notes, and a Map-of-Content index).
    Returns the vault path on the server."""
    r = _api("POST", "/api/obsidian/export")
    if r.get("error"):
        return "Error: " + r["error"]
    return f"Exported to Obsidian vault: {r.get('vault')} ({r.get('reports')} reports, {r.get('threats')} threats)"


@mcp.tool()
def dashboard() -> str:
    """Live status: agents, tool coverage, learned-signature stats and recent activity."""
    d = _api("GET", "/api/dashboard")
    k = d["knowledge"]
    out = [f"tools installed: {d['tools']['installed']}/{d['tools']['total']}",
           f"runs: {k['runs']} · known findings: {k['total_signatures']}",
           "severity: " + ", ".join(f"{s}={n}" for s, n in k["severity"].items()),
           "top threats: " + ", ".join(f"{t['name']} x{t['count']}" for t in k["top"]),
           "recent activity:"]
    for a in d["activity"][:8]:
        out.append(f"  - {a.get('when')} {a.get('type')} · {a.get('intent')} · {a.get('target')}")
    return "\n".join(out)


@mcp.tool()
def knowledge() -> str:
    """The accumulated learning knowledge base (finding signatures seen across runs)."""
    kb = _api("GET", "/api/knowledge")
    sigs = kb.get("signatures", {})
    out = [f"runs: {kb.get('runs',0)} · signatures: {len(sigs)}"]
    for sid, v in sorted(sigs.items(), key=lambda kv: -kv[1]["count"]):
        out.append(f"  - {v['name']} ({v['severity']}) x{v['count']}  first={v.get('first_seen')} last={v.get('last_seen')}")
    return "\n".join(out)


if __name__ == "__main__":
    mcp.run()
