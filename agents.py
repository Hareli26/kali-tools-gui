#!/usr/bin/env python3
"""
Agent engine for Kali Tools GUI.

Four cooperating agents:
  Planner  — turns a natural-language intent + target into an ordered plan of tool steps.
  Executor — (in server.py) runs each step as a job.
  Verifier — inspects a finished step's output/return-code and gives a verdict + findings.
  Reporter — compiles a Markdown report from all verified steps.

Default engine is rule-based (playbooks) — zero dependencies, works offline.
Optional LLM enhancement via Ollama if OLLAMA_URL is reachable and a model is set.
"""

import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402  (SQLite store — holds user-defined data playbooks)

# ---------------------------------------------------------------- targets ----
def target_variants(t):
    t = (t or "").strip()
    is_url = t.startswith("http://") or t.startswith("https://")
    if is_url:
        host = t.split("://", 1)[1].split("/", 1)[0]
        url = t
    else:
        host = t
        url = "http://" + t if t else ""
    host_noport = host.split(":")[0] if host else ""
    is_ip = bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}", host_noport))
    return {
        "raw": t, "url": url, "host": host_noport, "domain": host_noport,
        "hostport443": host_noport + ":443" if host_noport else "",
        "is_ip": is_ip, "is_url": is_url,
    }

def _step(tool_id, why, values, suggestion=""):
    return {"tool_id": tool_id, "why": why, "values": values, "suggestion": suggestion}

# ---- data-driven (user-defined) playbooks: SAFE placeholder substitution ----
# A custom playbook is pure data (no code). Step values may contain placeholders
# {target} {host} {url} {domain} {raw} that are substituted from the target — no
# code is ever executed, so editing playbooks from the UI is safe.
_PLACEHOLDERS = ("target", "host", "url", "domain", "raw", "hostport443")

def _subst(values, v):
    out = {}
    for k, val in (values or {}).items():
        if isinstance(val, str):
            for ph in _PLACEHOLDERS:
                src = v.get("raw" if ph == "target" else ph, "")
                val = val.replace("{%s}" % ph, str(src))
        out[k] = val
    return out

def _build_from_data(pb, v):
    steps = []
    for s in (pb.get("steps") or []):
        if not s.get("tool_id"):
            continue
        steps.append(_step(s["tool_id"], s.get("why", ""),
                           _subst(s.get("values", {}), v), s.get("suggestion", "")))
    return steps

def load_custom_playbooks():
    try:
        return [pb for pb in db.list_playbooks() if pb.get("id") and pb.get("keywords") is not None]
    except Exception:
        return []

# --------------------------------------------------------------- playbooks ---
# Each playbook: id, name, keywords (he+en), build(variants) -> [steps]
PLAYBOOKS = [
    {
        "id": "dns_recon", "name": "בדיקת DNS",
        "keywords": ["dns", "domain", "דומיין", "רשומ", "nameserver", "name server",
                     "mx", "zone", "אזור", "רשומות"],
        "build": lambda v: [
            _step("dig", "רשומות A – כתובות IP של הדומיין", {"type": "A", "short": True, "target": v["domain"]}),
            _step("dig", "רשומות MX – שרתי דואר", {"type": "MX", "short": True, "target": v["domain"]}),
            _step("dig", "רשומות NS – שרתי שמות", {"type": "NS", "short": True, "target": v["domain"]}),
            _step("dig", "רשומות TXT – SPF/אימותים", {"type": "TXT", "short": True, "target": v["domain"]}),
            _step("dnsenum", "אנומרציה מלאה + ניסיון Zone Transfer", {"target": v["domain"]},
                  "חפש Zone Transfer מוצלח או תת-דומיינים חשופים"),
            _step("dnsrecon", "בדיקת DNS סטנדרטית", {"domain": v["domain"], "type": "std"}),
        ],
    },
    {
        "id": "subdomains", "name": "גילוי תת-דומיינים",
        "keywords": ["subdomain", "תת דומיין", "תת-דומיין", "subdomains", "תת דומיינים", "asset"],
        "build": lambda v: [
            _step("subfinder", "גילוי תת-דומיינים פסיבי ומהיר", {"domain": v["domain"], "silent": True}),
            _step("sublist3r", "תת-דומיינים ממנועי חיפוש", {"domain": v["domain"]}),
            _step("assetfinder", "נכסים ותת-דומיינים קשורים", {"target": v["domain"], "subsonly": True}),
        ],
    },
    {
        "id": "port_scan", "name": "סריקת פורטים",
        "keywords": ["port", "פורט", "scan", "סריק", "nmap", "service", "שירות", "open port"],
        "build": lambda v: [
            _step("nmap", "סריקה מהירה: 1000 הפורטים הנפוצים + גרסאות שירות",
                  {"topports": "1000", "sv": True, "timing": "-T4", "target": v["host"]},
                  "שים לב לפורטים open ולגרסאות ישנות של שירותים"),
            _step("nmap", "סריקת ברירת-מחדל של סקריפטים (-sC) לזיהוי חולשות בסיסי",
                  {"sc": True, "sv": True, "timing": "-T4", "target": v["host"]}),
            _step("netcat", "אימות מהיר של פורטים נפוצים + חטיפת באנרים (חלופה ל-nmap)",
                  {"zscan": True, "verbose": True, "nodns": True, "wait": "2",
                   "host": v["host"], "port": "20-1024"},
                  "השווה לתוצאות nmap; באנרים חושפים גרסאות שירות"),
        ],
    },
    {
        "id": "web_scan", "name": "סריקת אתר ווב",
        "keywords": ["web", "אתר", "website", "http", "אפליקצי", "web app", "webapp", "site"],
        "build": lambda v: [
            _step("whatweb", "טביעת אצבע – טכנולוגיות, שרת, CMS", {"aggr": "3", "target": v["url"]}),
            _step("wafw00f", "זיהוי Web Application Firewall", {"target": v["url"]}),
            _step("nikto", "סריקת חולשות בשרת הווב (ממוקד + מוגבל בזמן)",
                  {"host": v["url"], "tuning": "123b", "maxtime": "150s"},
                  "כוונון 123b = קבצים מעניינים, תצורה שגויה, חשיפת מידע, זיהוי תוכנה"),
            _step("nuclei", "סריקת חולשות מבוססת תבניות", {"url": v["url"], "severity": "critical,high,medium"}),
            _step("gobuster", "גילוי תיקיות וקבצים נסתרים",
                  {"mode": "dir", "url": v["url"], "wordlist": "/usr/share/wordlists/dirb/common.txt"}),
        ],
    },
    {
        "id": "pentest", "name": "בדיקת חדירות מקיפה",
        "keywords": ["pentest", "חדיר", "penetration", "בדיקת חדירות", "מקיף", "vulnerab",
                     "חולש", "full", "audit", "מבדק", "התקפ", "attack surface"],
        "build": lambda v: [
            _step("nmap", "מיפוי פורטים ושירותים – הבסיס לכל בדיקה",
                  {"topports": "1000", "sv": True, "timing": "-T4", "target": v["host"]}),
            _step("nmap", "סריקת סקריפטים לזיהוי חולשות ידועות",
                  {"sc": True, "sv": True, "timing": "-T4", "target": v["host"]}),
            _step("whatweb", "טכנולוגיות ווב (אם יש שירות HTTP)", {"aggr": "3", "target": v["url"]}),
            _step("nikto", "חולשות בשרת ווב (ממוקד + מוגבל בזמן)",
                  {"host": v["url"], "tuning": "123b", "maxtime": "120s"}),
            _step("nuclei", "סריקת חולשות מבוססת תבניות", {"url": v["url"], "severity": "critical,high"}),
        ],
    },
    {
        "id": "smb_enum", "name": "אנומרציית SMB / Windows",
        "keywords": ["smb", "שיתופ", "share", "windows", "netbios", "samba", "active directory",
                     "ad ", "domain controller", "dc "],
        "build": lambda v: [
            _step("nbtscan", "סריקת NetBIOS – שמות מחשבים", {"target": v["host"]}),
            _step("enum4linux-ng", "אנומרציה מקיפה – משתמשים, שיתופים, קבוצות", {"all": True, "target": v["host"]}),
            _step("smbclient", "רשימת שיתופים (null session)", {"list": "//" + v["host"], "noauth": True}),
            _step("crackmapexec", "בדיקת SMB ואנומרציה", {"proto": "smb", "target": v["host"]}),
        ],
    },
    {
        "id": "ssl_check", "name": "בדיקת SSL / TLS",
        "keywords": ["ssl", "tls", "certificate", "תעוד", "https", "cipher", "צופן", "הצפנה"],
        "build": lambda v: [
            _step("sslscan", "פרוטוקולים, ציפרים וחולשות TLS", {"target": v["hostport443"]},
                  "חפש פרוטוקולים ישנים (SSLv3/TLS1.0) וציפרים חלשים"),
            _step("sslyze", "ניתוח מעמיק של תצורת TLS", {"target": v["hostport443"]}),
        ],
    },
    {
        "id": "sql_injection", "name": "בדיקת SQL Injection",
        "keywords": ["sql", "sqli", "injection", "הזרק", "database", "מסד נתונים", "sqlmap"],
        "build": lambda v: [
            _step("sqlmap", "זיהוי וניצול הזרקות SQL", {"url": v["url"], "batch": True, "dbs": True},
                  "ודא שה-URL כולל פרמטר, למשל ?id=1"),
        ],
    },
    {
        "id": "cms", "name": "בדיקת CMS (WordPress)",
        "keywords": ["wordpress", "wp ", "wp-", "cms", "joomla", "drupal"],
        "build": lambda v: [
            _step("whatweb", "זיהוי סוג וגרסת ה-CMS", {"aggr": "3", "target": v["url"]}),
            _step("wpscan", "סריקת WordPress – תוספים, משתמשים וחולשות",
                  {"url": v["url"], "enumerate": "vp", "random_ua": True}),
        ],
    },
    {
        "id": "active_directory", "name": "Active Directory / דומיין",
        "keywords": ["active directory", "kerberos", "ldap", "domain controller",
                     "דומיין", "dc ", "בקר תחום", "kerberoast", "ntlm", " ad "],
        "build": lambda v: [
            _step("nmap", "פורטים אופייניים ל-AD (Kerberos/LDAP/SMB/RDP)",
                  {"ports": "88,135,139,389,445,464,636,3268,3389", "sv": True, "timing": "-T4", "target": v["host"]}),
            _step("enum4linux-ng", "אנומרציית משתמשים/קבוצות/שיתופים", {"all": True, "target": v["host"]}),
            _step("crackmapexec", "בדיקת SMB ואנומרציה", {"proto": "smb", "target": v["host"], "users": True}),
            _step("crackmapexec", "אנומרציית LDAP", {"proto": "ldap", "target": v["host"]}),
            _step("rpcclient", "אנומרציית משתמשי דומיין (null session)",
                  {"cmd": "enumdomusers", "nopass": True, "target": v["host"]}),
        ],
    },
    {
        "id": "api_test", "name": "בדיקת API",
        "keywords": ["api", "rest", "endpoint", "swagger", "graphql", "json api", "ממשק"],
        "build": lambda v: [
            _step("httpx", "בדיקת ה-endpoint – סטטוס, טכנולוגיות, כותרות",
                  {"url": v["url"], "title": True, "sc": True, "td": True, "server": True}),
            _step("gospider", "מיפוי נתיבים ו-endpoints", {"site": v["url"], "depth": "2", "other": True}),
            _step("arjun", "גילוי פרמטרים נסתרים", {"url": v["url"]}),
            _step("nuclei", "תבניות חשיפות ו-CVE ל-API", {"url": v["url"], "tags": "exposure,cve,misconfig"}),
        ],
    },
    {
        "id": "net_sweep", "name": "מיפוי רשת מקומית",
        "keywords": ["network sweep", "live host", "מיפוי רשת", "מכשירים", "discover host",
                     "רשת מקומית", "lan", "סריקת רשת", "מי מחובר", "gateway", "arp"],
        "build": lambda v: [
            _step("nmap", "Ping sweep – אילו מארחים חיים", {"scan": "-sn", "target": v["host"]}),
            _step("arp-scan", "גילוי מכשירים + זיהוי יצרן (ARP)", {"target": v["host"]}),
            _step("fping", "אימות מארחים חיים", {"alive": True, "gen": True, "quiet": True, "target": v["host"]}),
            _step("netdiscover", "גילוי פסיבי/אקטיבי ב-ARP", {"range": v["host"], "passive": False}),
        ],
    },
    {
        "id": "osint", "name": "איסוף מודיעין (OSINT)",
        "keywords": ["osint", "מודיעין", "email", "אימייל", "harvest", "information gathering",
                     "איסוף מידע", "מידע", "reconnaissance", "recon"],
        "build": lambda v: [
            _step("whois", "רישום דומיין – בעלות ותאריכים", {"target": v["domain"]}),
            _step("theharvester", "אימיילים ותת-דומיינים ממקורות ציבוריים", {"domain": v["domain"], "source": "bing"}),
            _step("dmitry", "איסוף מידע מצטבר", {"target": v["domain"], "whois": True, "subs": True, "emails": True}),
            _step("shodan", "מודיעין Shodan על היעד — פורטים פתוחים, שירותים וחשיפה לאינטרנט",
                  {"cmd": "host" if v["is_ip"] else "domain", "query": v["host"]},
                  "דורש מפתח API מוגדר (shodan init). חפש פורטים/שירותים חשופים ו-CVEs ידועים"),
        ],
    },
    {
        "id": "exploit_search", "name": "חיפוש אקספלויטים (Exploit-DB)",
        "keywords": ["exploit", "אקספלויט", "exploitdb", "exploit-db", "searchsploit",
                     "cve", "poc", "פרצה ידועה", "known vuln", "אקספלויטים"],
        "build": lambda v: [
            _step("searchsploit", "חיפוש במאגר Exploit-DB לפי המוצר/הגרסה/CVE שסופקו",
                  {"term": v["raw"]},
                  "צלב מול גרסאות שזוהו ב-nmap -sV / whatweb כדי לאמת רלוונטיות"),
        ],
    },
    {
        "id": "forensics", "name": "פורנזיקה וסטגנוגרפיה",
        "keywords": ["forensic", "פורנז", "steg", "סטגנ", "stego", "metadata", "מטא-דאטה",
                     "מטאדאטה", "exif", "image", "תמונה", "hidden", "מוסתר", "carve", "קובץ חשוד"],
        "build": lambda v: [
            _step("exiftool", "חילוץ מטא-דאטה מהקובץ — מצלמה, GPS, תוכנה, תאריכים",
                  {"all": True, "groups": True, "file": v["raw"]},
                  "חפש קואורדינטות GPS, שם מחבר, גרסת תוכנה או חוסר התאמה בתאריכים"),
            _step("binwalk", "זיהוי וחילוץ קבצים מוטמעים בתוך הקובץ",
                  {"extract": True, "file": v["raw"]},
                  "חפש ארכיונים/תמונות/מפתחות מוטמעים (firmware, תמונות משורשרות)"),
            _step("steghide", "ניסיון חילוץ מידע מוסתר (steganography)",
                  {"cmd": "extract", "sf": v["raw"]},
                  "אם נדרשת סיסמה נסה ריקה או נפוצה; בדוק אם חולץ קובץ"),
        ],
    },
]

GENERAL = {
    "id": "general", "name": "בדיקה כללית",
    "build": lambda v: [
        _step("ping", "בדיקת זמינות המטרה", {"count": "4", "target": v["host"]}),
        _step("nmap", "סריקת פורטים בסיסית + גרסאות",
              {"topports": "1000", "sv": True, "timing": "-T4", "target": v["host"]}),
        _step("whatweb", "זיהוי טכנולוגיות ווב (אם רלוונטי)", {"aggr": "1", "target": v["url"]}),
    ],
}

ROOT_TOOLS = {"masscan", "netdiscover", "arp-scan", "tcpdump", "tshark", "hping3", "nping", "responder"}

# ---------------------------------------------------------------- planner ----
def plan(intent, target):
    v = target_variants(target)
    il = (intent or "").lower()
    all_pbs = list(PLAYBOOKS) + load_custom_playbooks()
    scored = []
    for pb in all_pbs:
        score = sum(1 for k in (pb.get("keywords") or []) if k and k.lower() in il)
        if score:
            scored.append((score, pb))
    if scored:
        scored.sort(key=lambda x: -x[0])
        top = scored[0][0]
        chosen = [pb for s, pb in scored if s == top]
        # if the user asked broadly (pentest) it already chains a lot; otherwise
        # allow a secondary distinct playbook that also scored to broaden coverage
        if len(chosen) == 1 and len(scored) > 1 and chosen[0]["id"] != "pentest":
            second = scored[1][1]
            if second["id"] not in ("pentest",):
                chosen.append(second)
    else:
        chosen = [GENERAL]

    steps = []
    seen = set()
    for pb in chosen:
        built = pb["build"](v) if callable(pb.get("build")) else _build_from_data(pb, v)
        for st in built:
            key = (st["tool_id"], json.dumps(st.get("values", {}), sort_keys=True, ensure_ascii=False))
            if key in seen:
                continue
            seen.add(key)
            st = dict(st)
            st["playbook"] = pb["name"]
            st["needs_root"] = st["tool_id"] in ROOT_TOOLS
            steps.append(st)

    return {
        "engine": "rules",
        "intent": intent,
        "target": target,
        "playbooks": [pb["name"] for pb in chosen],
        "steps": steps,
    }

BUILTIN_IDS = {pb["id"] for pb in PLAYBOOKS} | {"general"}

def describe_playbooks():
    """Serializable view of every playbook for the in-app editor: built-in ones
    (read-only, steps derived from a sample target) + user-defined ones (editable)."""
    sample = target_variants("example.com")
    out = []
    for pb in PLAYBOOKS:
        try:
            steps = [{"tool_id": s["tool_id"], "why": s.get("why", "")} for s in pb["build"](sample)]
        except Exception:
            steps = []
        out.append({"id": pb["id"], "name": pb["name"], "builtin": True,
                    "keywords": pb.get("keywords", []), "steps": steps})
    for pb in load_custom_playbooks():
        out.append({"id": pb["id"], "name": pb.get("name", pb["id"]), "builtin": False,
                    "keywords": pb.get("keywords", []), "steps": pb.get("steps", [])})
    return out

# --------------------------------------------------------------- verifier ----
_ERR_ROOT = ("requires root", "you requested a scan type which requires root",
             "permission denied", "operation not permitted", "must be run as root",
             "you need to be root", "are you root")
_ERR_MISSING = ("command not found", "no such file or directory")
_ERR_DNS = ("could not resolve", "couldn't resolve", "name or service not known",
            "unknown host", "could not find")
_ERR_CONN = ("connection refused", "no route to host", "failed to connect",
             "0 hosts up", "host seems down", "network is unreachable", "timed out")

_FIND_PATTERNS = [
    re.compile(r"\bopen\b.*(tcp|udp)", re.I),
    re.compile(r"\d+/(tcp|udp)\s+open", re.I),
    re.compile(r"VULNERABLE", re.I),
    re.compile(r"CVE-\d{4}-\d+", re.I),
    re.compile(r"OSVDB-\d+", re.I),
    re.compile(r"^\s*\[\+\]", re.I),          # generic [+]
    re.compile(r"^\s*\+\s+\S", re.I),          # nikto "+ ..." findings
    re.compile(r"\[(critical|high|medium)\]", re.I),
    re.compile(r"Status:\s*(200|301|302|401|403)", re.I),
    re.compile(r"\(Status:\s*\d+\)", re.I),   # gobuster "(Status: 200)"
]

# noise lines (banners/headers) to ignore even if they match a pattern
_SKIP_LINES = ("target ip", "target hostname", "target port", "start time",
               "end time", "- nikto v", "host(s) tested", "requests:", "ssl info",
               "root:", "server:", "retrieved x-powered")

def verify(tool_id, snap):
    out = snap.get("output", "") or ""
    low = out.lower()
    rc = snap.get("returncode")
    status = snap.get("status")

    if status == "stopped":
        return {"verdict": "stopped", "label": "נעצר", "note": "השלב נעצר ידנית.", "findings": []}

    def has(subs):
        return any(s in low for s in subs)

    if has(_ERR_ROOT):
        return {"verdict": "fail", "label": "דרוש root",
                "note": "הכלי דורש הרשאות root. הפעל את השרת עם משתמש root (ראה README).", "findings": []}
    if has(_ERR_MISSING) and status == "error":
        return {"verdict": "fail", "label": "כלי חסר",
                "note": "נראה שהכלי או קובץ נדרש חסרים.", "findings": []}
    if has(_ERR_DNS):
        return {"verdict": "warn", "label": "רזולוציה נכשלה",
                "note": "לא ניתן לפתור את שם המטרה (בעיית DNS/מטרה שגויה).", "findings": []}
    if has(_ERR_CONN):
        return {"verdict": "warn", "label": "מטרה לא זמינה",
                "note": "לא ניתן להתחבר למטרה (down / חסום / פורט סגור).", "findings": []}

    findings = []
    for line in out.splitlines():
        l = line.strip()
        if not l or len(l) > 200:
            continue
        ll = l.lower()
        if any(sk in ll for sk in _SKIP_LINES):
            continue
        for pat in _FIND_PATTERNS:
            if pat.search(l):
                findings.append(l)
                break
        if len(findings) >= 15:
            break
    # dedupe preserving order
    seen = set(); uniq = []
    for f in findings:
        if f not in seen:
            seen.add(f); uniq.append(f)
    findings = uniq

    if status == "error" or (rc not in (0, None)):
        if findings:
            return {"verdict": "warn", "label": "הושלם עם שגיאות", "note": "הכלי סיים עם קוד שגיאה אך הופקו ממצאים.", "findings": findings}
        return {"verdict": "warn", "label": "הושלם עם שגיאות", "note": "הכלי סיים עם קוד יציאה שאינו 0.", "findings": findings}
    if findings:
        return {"verdict": "ok_findings", "label": "ממצאים", "note": "השלב הושלם ונמצאו פריטים לתשומת לב.", "findings": findings}
    return {"verdict": "ok", "label": "תקין", "note": "השלב הושלם ללא ממצאים בולטים.", "findings": []}

# --------------------------------------------------------------- reporter ----
_VERDICT_ICON = {"ok": "✅", "ok_findings": "🔎", "warn": "⚠️", "fail": "❌", "stopped": "⏹️"}

def report(mission, when=""):
    intent = mission.get("intent", "")
    target = mission.get("target", "")
    steps = mission.get("steps", [])

    total = len(steps)
    ok = sum(1 for s in steps if s.get("verdict", {}).get("verdict") in ("ok", "ok_findings"))
    findings_steps = [s for s in steps if s.get("verdict", {}).get("findings")]
    warns = sum(1 for s in steps if s.get("verdict", {}).get("verdict") == "warn")
    fails = sum(1 for s in steps if s.get("verdict", {}).get("verdict") == "fail")

    lines = []
    lines.append("# 🛡️ דוח בדיקת אבטחה")
    lines.append("")
    lines.append(f"- **כוונה:** {intent}")
    lines.append(f"- **מטרה:** `{target}`")
    if when:
        lines.append(f"- **זמן:** {when}")
    lines.append(f"- **שלבים שבוצעו:** {total}  |  ✅ תקין: {ok}  |  ⚠️ אזהרות: {warns}  |  ❌ נכשלו: {fails}")
    lines.append("")

    # executive summary
    lines.append("## סיכום מנהלים")
    if findings_steps:
        lines.append(f"נמצאו ממצאים לתשומת לב ב-{len(findings_steps)} שלבים:")
        for s in findings_steps:
            top = s["verdict"]["findings"][:3]
            lines.append(f"- **{s['tool_name']}** – {s['why']}")
            for f in top:
                lines.append(f"  - `{f}`")
    else:
        lines.append("לא נמצאו ממצאים בולטים בשלבים שבוצעו.")
    lines.append("")

    # detailed steps
    lines.append("## פירוט שלבים")
    for i, s in enumerate(steps, 1):
        vd = s.get("verdict", {})
        icon = _VERDICT_ICON.get(vd.get("verdict"), "•")
        lines.append(f"### {i}. {icon} {s['tool_name']} — {vd.get('label','')}")
        lines.append(f"*{s['why']}*")
        lines.append("")
        lines.append(f"```\n{s['command']}\n```")
        lines.append(f"{vd.get('note','')}")
        if vd.get("findings"):
            lines.append("")
            lines.append("**ממצאים:**")
            for f in vd["findings"][:10]:
                lines.append(f"- `{f}`")
        lines.append("")

    lines.append("---")
    lines.append("*הופק ע\"י Kali Tools GUI – שכבת הסוכנים. הרץ כלים אך ורק על מטרות מאושרות.*")
    return "\n".join(lines)

# ------------------------------------------------------------- optional LLM --
def llm_report(mission, when=""):
    """If an Ollama model is configured & reachable, produce a nicer prose summary.
    Returns None on any failure so the caller falls back to the rule-based report."""
    url = os.environ.get("OLLAMA_URL")
    model = os.environ.get("OLLAMA_MODEL")
    if not url or not model:
        return None
    try:
        steps_txt = "\n".join(
            f"- {s['tool_name']} ({s.get('verdict',{}).get('label','')}): "
            f"{'; '.join(s.get('verdict',{}).get('findings',[])[:5]) or 'ללא ממצאים'}"
            for s in mission.get("steps", [])
        )
        prompt = (
            "אתה אנליסט אבטחת סייבר. כתוב דוח קצר ומקצועי בעברית (Markdown) "
            f"על בדיקה שבוצעה.\nכוונה: {mission.get('intent')}\nמטרה: {mission.get('target')}\n"
            f"תוצאות השלבים:\n{steps_txt}\n\nהדוח יכלול: סיכום מנהלים, ממצאים עיקריים, והמלצות."
        )
        body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
        req = urllib.request.Request(url.rstrip("/") + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
        text = data.get("response", "").strip()
        return text or None
    except Exception:
        return None
