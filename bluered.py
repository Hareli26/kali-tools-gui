#!/usr/bin/env python3
"""
Purple-team layer for Kali Tools GUI.

Agents:
  🔴 Red Team    — the existing mission executor produces offensive findings.
  🟢 Broker      — correlates/dedupes red findings and routes each to a defense.
  🔵 Blue Team   — maps each finding to concrete defenses, detections, MITRE refs.
  🟣 Orchestrator — runs the flow, updates the learning KB, writes the purple report.

Continuous learning: findings are normalized to signatures and accumulated in
`knowledge.json` (count + first/last seen), so coverage grows across runs.

Rule-based (zero deps). Everything is defensive: the Blue output is mitigation,
hardening and detection guidance — never offensive instructions.
"""

import json
import os
import re
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("KALIGUI_DATA_DIR") or HERE
KB_FILE = os.path.join(DATA_DIR, "knowledge.json")
ACTIVITY_FILE = os.path.join(DATA_DIR, "activity.json")
_KB_LOCK = threading.Lock()
_ACT_LOCK = threading.Lock()

# ------------------------------------------------------ 📰 activity feed -----
def log_activity(entry):
    """Append one activity entry (for the dashboard magazine feed). Keeps last 200."""
    with _ACT_LOCK:
        data = []
        if os.path.isfile(ACTIVITY_FILE):
            try:
                with open(ACTIVITY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = []
        data.append(entry)
        data = data[-200:]
        try:
            with open(ACTIVITY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

def load_activity():
    with _ACT_LOCK:
        if os.path.isfile(ACTIVITY_FILE):
            try:
                with open(ACTIVITY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

# ---------------------------------------------------------- defense knowledge
# Ordered specific -> generic. First matching rule wins.
DEFENSE_KB = [
    {
        "id": "missing-security-header", "name": "כותרת אבטחה חסרה", "severity": "low",
        "patterns": [r"x-frame-options", r"x-content-type-options", r"content-security-policy",
                     r"strict-transport-security", r"clickjacking", r"header is not present",
                     r"header is not set"],
        "threat": "היעדר כותרות אבטחה חושף את המשתמשים ל-Clickjacking, MIME-sniffing והזרקות תוכן.",
        "defenses": [
            "הוסף כותרות: X-Frame-Options: DENY, X-Content-Type-Options: nosniff",
            "הגדר Content-Security-Policy מחמיר",
            "הפעל HSTS: Strict-Transport-Security: max-age=63072000; includeSubDomains",
        ],
        "detections": ["בדיקת כותרות תקופתית (securityheaders.io / סורק פנימי)"],
        "config": "Apache: Header always set X-Frame-Options \"DENY\"\nHeader always set X-Content-Type-Options \"nosniff\"",
        "mitre": "M1050 (Exploit Protection)",
    },
    {
        "id": "directory-indexing", "name": "רשימת תיקיות חשופה (Directory Indexing)", "severity": "medium",
        "patterns": [r"directory indexing", r"index of /", r"indexing found"],
        "threat": "Directory Indexing חושף קבצים ומבנה שרת שעלולים להכיל מידע רגיש.",
        "defenses": ["כבה indexing: Options -Indexes", "הוסף index.html לכל תיקייה", "הגבל גישה לתיקיות רגישות"],
        "detections": ["ניטור בקשות לתיקיות ללא index", "סריקת תוכן תקופתית"],
        "config": "Apache: Options -Indexes",
        "mitre": "T1083 (File and Directory Discovery)",
    },
    {
        "id": "default-file", "name": "קובץ/דף ברירת מחדל חשוף", "severity": "low",
        "patterns": [r"default file found", r"/icons/readme", r"osvdb-\d+", r"apache default"],
        "threat": "קבצי ברירת מחדל חושפים גרסאות ומידע שמסייע לתוקף.",
        "defenses": ["הסר קבצי ברירת מחדל (README, manuals, test pages)", "הסתר גרסת שרת (ServerTokens Prod, ServerSignature Off)"],
        "detections": ["סריקת תוכן לגילוי קבצי ברירת מחדל"],
        "config": "Apache: ServerTokens Prod\nServerSignature Off",
        "mitre": "T1592 (Gather Victim Host Information)",
    },
    {
        "id": "outdated-software", "name": "תוכנה מיושנת", "severity": "high",
        "patterns": [r"outdated", r"appears to be outdated", r"apache/2\.[0-3]\.", r"apache/2\.4\.[0-9]\b",
                     r"openssh [1-7]\.", r"end of life", r"eol"],
        "threat": "גרסאות תוכנה מיושנות מכילות חולשות ידועות (CVE) הניתנות לניצול.",
        "defenses": ["עדכן לגרסה הנתמכת האחרונה", "הפעל עדכוני אבטחה אוטומטיים", "מפה נכסים וגרסאות (asset inventory)"],
        "detections": ["ניטור CVE מול מלאי הגרסאות", "סריקת חולשות תקופתית (nuclei/OpenVAS)"],
        "config": "Debian/Ubuntu: unattended-upgrades",
        "mitre": "T1190 (Exploit Public-Facing Application)",
    },
    {
        "id": "exposed-path", "name": "נתיב/משאב חשוף", "severity": "medium",
        "patterns": [r"\(status:\s*(200|401|403)\)", r"/\.git", r"/admin", r"/backup",
                     r"/server-status", r"/phpmyadmin", r"/\.env"],
        "threat": "נתיבים חשופים (ניהול, גיבויים, .git, .env) עלולים לחשוף קוד, סודות או ממשקי ניהול.",
        "defenses": ["הגבל גישה בהזדהות ו-IP allowlist", "הסר קבצים רגישים מהשרת (.git/.env/backup)",
                     "החזר 404 לנתיבים פנימיים", "הפרד סביבות ניהול מהרשת הציבורית"],
        "detections": ["ניטור בקשות לנתיבים רגישים", "התראה על גישה ל-/admin,/.git,/.env"],
        "config": "Apache: <LocationMatch \"^/(\\.git|\\.env|backup)\"> Require all denied </LocationMatch>",
        "mitre": "T1083 / T1552 (Unsecured Credentials)",
    },
    {
        "id": "ssh-exposed", "name": "שירות SSH חשוף", "severity": "medium",
        "patterns": [r"open\s+ssh", r"/tcp\s+open\s+ssh", r"\bssh\b.*openssh"],
        "threat": "SSH חשוף לאינטרנט מזמין ניסיונות brute-force וגישה לא מורשית.",
        "defenses": ["אכוף אימות מפתחות בלבד (PasswordAuthentication no)", "השבת התחברות root (PermitRootLogin no)",
                     "הגבל ב-firewall לכתובות מורשות", "התקן fail2ban", "הוסף MFA / שנה פורט"],
        "detections": ["ניטור /var/log/auth.log", "התראה על ריבוי כשלי התחברות מאותו מקור"],
        "config": "sshd_config: PasswordAuthentication no\nPermitRootLogin no\nAllowUsers ...",
        "mitre": "T1110 (Brute Force)",
    },
    {
        "id": "smb-exposed", "name": "שירות SMB/NetBIOS חשוף", "severity": "high",
        "patterns": [r"445/tcp\s+open", r"139/tcp\s+open", r"microsoft-ds", r"netbios", r"\bsmb\b"],
        "threat": "SMB חשוף מאפשר אנומרציה, גישה לשיתופים וניצול חולשות (למשל EternalBlue).",
        "defenses": ["השבת SMBv1", "חסום פורטים 139/445 מהאינטרנט", "השבת null sessions",
                     "אכוף SMB signing", "הגבל שיתופים והרשאות"],
        "detections": ["ניטור גישה לשיתופים", "התראה על אנומרציית SMB / כניסות אנונימיות"],
        "config": "Windows: Disable SMBv1; RestrictAnonymous=1",
        "mitre": "T1021.002 (SMB/Windows Admin Shares)",
    },
    {
        "id": "rdp-exposed", "name": "שירות RDP חשוף", "severity": "high",
        "patterns": [r"3389/tcp\s+open", r"ms-wbt-server", r"\brdp\b"],
        "threat": "RDP חשוף הוא וקטור מוביל לכופרות (ransomware) דרך brute-force וחולשות.",
        "defenses": ["אל תחשוף RDP לאינטרנט — השתמש ב-VPN", "אכוף NLA", "הגבל ב-firewall", "MFA + נעילת חשבונות"],
        "detections": ["ניטור התחברויות RDP", "התראה על brute-force / כניסות בשעות חריגות"],
        "config": "GPO: Require NLA; Account lockout policy",
        "mitre": "T1021.001 (Remote Desktop Protocol)",
    },
    {
        "id": "no-tls", "name": "שירות HTTP ללא הצפנה", "severity": "medium",
        "patterns": [r"80/tcp\s+open\s+http\b", r"open\s+http\b(?!s)"],
        "threat": "תעבורת HTTP לא מוצפנת חשופה לצותת (MITM) וגניבת אישורים.",
        "defenses": ["אכוף HTTPS והפנה 80→443", "הפעל HSTS", "השתמש בתעודות תקפות (Let's Encrypt)"],
        "detections": ["ניטור תעבורת HTTP לא מוצפנת", "בדיקת תקינות תעודות"],
        "config": "Apache: Redirect permanent / https://...  + HSTS",
        "mitre": "T1040 (Network Sniffing)",
    },
    {
        "id": "ftp-telnet", "name": "פרוטוקול לא מאובטח (FTP/Telnet)", "severity": "high",
        "patterns": [r"21/tcp\s+open\s+ftp", r"23/tcp\s+open", r"\btelnet\b", r"open\s+ftp\b"],
        "threat": "FTP/Telnet מעבירים אישורים בטקסט גלוי — פגיעים לצותת וגישה לא מורשית.",
        "defenses": ["החלף ל-SFTP/SSH", "כבה Telnet/FTP", "אם חובה — הצפן (FTPS) והגבל גישה"],
        "detections": ["ניטור פורטים 21/23", "התראה על שימוש בפרוטוקולים לא מוצפנים"],
        "config": "כבה vsftpd/telnetd; אפשר SSH בלבד",
        "mitre": "T1040 / T1110",
    },
    {
        "id": "snmp-exposed", "name": "SNMP חשוף", "severity": "medium",
        "patterns": [r"161/udp\s+open", r"\bsnmp\b", r"community string"],
        "threat": "SNMP עם community string ברירת מחדל (public) חושף מידע מערכת נרחב.",
        "defenses": ["שנה community strings", "השתמש ב-SNMPv3 עם הצפנה", "הגבל גישה ב-ACL/firewall"],
        "detections": ["ניטור שאילתות SNMP", "התראה על שימוש ב-community 'public'"],
        "config": "SNMPv3 with auth+priv; disable v1/v2c",
        "mitre": "T1046 (Network Service Discovery)",
    },
    {
        "id": "waf-absent", "name": "היעדר WAF", "severity": "low",
        "patterns": [r"no waf", r"generic detection", r"does not seem to be behind a waf", r"seems to be behind\s*none"],
        "threat": "ללא WAF, האפליקציה חשופה ישירות להזרקות ותקיפות אוטומטיות.",
        "defenses": ["הצב WAF (ModSecurity/Cloudflare)", "הפעל חוקי OWASP CRS", "הגבל rate-limiting"],
        "detections": ["ניטור לוגים של WAF", "התראה על חסימות חוזרות מאותו מקור"],
        "config": "ModSecurity + OWASP Core Rule Set",
        "mitre": "M1037 (Filter Network Traffic)",
    },
    {
        "id": "weak-tls", "name": "תצורת TLS חלשה", "severity": "high",
        "patterns": [r"sslv[23]", r"tls\s*1\.0", r"tls\s*1\.1", r"rc4", r"weak cipher", r"\bnull cipher\b", r"export cipher"],
        "threat": "פרוטוקולים/ציפרים חלשים (SSLv3, TLS1.0, RC4) ניתנים לפיצוח והתקפות MITM.",
        "defenses": ["השבת SSLv3/TLS1.0/1.1 — אפשר TLS1.2+ בלבד", "הסר ציפרים חלשים (RC4/EXPORT/NULL)", "אכוף Forward Secrecy"],
        "detections": ["סריקת SSL תקופתית (sslscan/testssl)", "ניטור התאמת תצורה למדיניות"],
        "config": "SSLProtocol -all +TLSv1.2 +TLSv1.3",
        "mitre": "T1040 (Network Sniffing)",
    },
    {
        "id": "injection", "name": "חולשת הזרקה (SQLi/XSS)", "severity": "critical",
        "patterns": [r"sql injection", r"injectable", r"\bsqli\b", r"\bxss\b", r"cross-site scripting"],
        "threat": "חולשות הזרקה מאפשרות גניבת נתונים, השתלטות והרצת קוד.",
        "defenses": ["השתמש ב-Prepared Statements/ORM", "בצע Input Validation ו-Output Encoding",
                     "החל עקרון least privilege ל-DB", "הפעל WAF עם חוקי OWASP"],
        "detections": ["ניטור שגיאות DB חריגות", "התראות WAF על דפוסי הזרקה"],
        "config": "Parameterized queries; ModSecurity CRS",
        "mitre": "T1190 (Exploit Public-Facing Application)",
    },
    {
        "id": "open-port-generic", "name": "פורט/שירות פתוח", "severity": "low",
        "patterns": [r"\d+/(tcp|udp)\s+open", r"\bopen\b.*(tcp|udp)"],
        "threat": "כל פורט פתוח מרחיב את משטח התקיפה.",
        "defenses": ["סגור פורטים לא נחוצים", "הגבל חשיפה ב-firewall ובסגמנטציה של הרשת",
                     "החל עקרון minimal exposure"],
        "detections": ["סריקת פורטים תקופתית והשוואה ל-baseline", "התראה על פורט חדש שנפתח"],
        "config": "Host firewall default-deny; רק שירותים נדרשים",
        "mitre": "T1046 (Network Service Discovery)",
    },
]

_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
DEFENSE_BY_ID = {r["id"]: r for r in DEFENSE_KB}

def get_defense(signature):
    """Return the full defense rule for a signature id, or None."""
    return DEFENSE_BY_ID.get(signature)

def analyze_finding(text):
    low = text.lower()
    for rule in DEFENSE_KB:
        for pat in rule["patterns"]:
            if re.search(pat, low):
                return rule
    return None

# ---------------------------------------------------------------- 🟢 broker --
def broker(red_findings):
    """Correlate red findings -> defenses. Dedupe by (rule, finding text).
    red_findings: list of {tool, text}. Returns prioritized list of threats."""
    threats = {}
    for rf in red_findings:
        rule = analyze_finding(rf["text"])
        if not rule:
            continue
        key = rule["id"]
        t = threats.get(key)
        if not t:
            t = {
                "signature": rule["id"], "name": rule["name"], "severity": rule["severity"],
                "threat": rule["threat"], "defenses": rule["defenses"], "detections": rule["detections"],
                "config": rule.get("config", ""), "mitre": rule.get("mitre", ""),
                "evidence": [], "tools": set(),
            }
            threats[key] = t
        if rf["text"] not in t["evidence"]:
            t["evidence"].append(rf["text"])
        t["tools"].add(rf["tool"])
    out = list(threats.values())
    for t in out:
        t["tools"] = sorted(t["tools"])
    out.sort(key=lambda t: (_SEV_RANK.get(t["severity"], 9), t["name"]))
    return out

# --------------------------------------------------------- 🧠 learning KB ----
def load_kb():
    with _KB_LOCK:
        if os.path.isfile(KB_FILE):
            try:
                with open(KB_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"runs": 0, "signatures": {}}

def update_kb(threats, when):
    """Accumulate signatures across runs; returns a learning summary."""
    with _KB_LOCK:
        kb = {"runs": 0, "signatures": {}}
        if os.path.isfile(KB_FILE):
            try:
                with open(KB_FILE, "r", encoding="utf-8") as f:
                    kb = json.load(f)
            except Exception:
                pass
        kb["runs"] = kb.get("runs", 0) + 1
        sigs = kb.setdefault("signatures", {})
        new_this_run = []
        for t in threats:
            sig = t["signature"]
            rec = sigs.get(sig)
            if not rec:
                rec = {"name": t["name"], "severity": t["severity"], "count": 0,
                       "first_seen": when, "last_seen": when}
                sigs[sig] = rec
                new_this_run.append(t["name"])
            rec["count"] += 1
            rec["last_seen"] = when
        try:
            with open(KB_FILE, "w", encoding="utf-8") as f:
                json.dump(kb, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        top = sorted(sigs.items(), key=lambda kv: -kv[1]["count"])[:5]
        return {
            "runs": kb["runs"],
            "total_signatures": len(sigs),
            "new_this_run": new_this_run,
            "top": [{"name": v["name"], "count": v["count"], "severity": v["severity"]} for _, v in top],
        }

# ------------------------------------------------------- 🟣 orchestrator -----
_SEV_ICON = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "🟩"}
_SEV_HE = {"critical": "קריטי", "high": "גבוה", "medium": "בינוני", "low": "נמוך"}

def purple_report(intent, target, red_steps, threats, learning, when=""):
    lines = []
    lines.append("# 🟣 דוח Purple Team")
    lines.append("")
    lines.append(f"- **כוונה:** {intent}")
    lines.append(f"- **מטרה:** `{target}`")
    if when:
        lines.append(f"- **זמן:** {when}")
    n_red = sum(len((s.get('verdict') or {}).get('findings', [])) for s in red_steps)
    lines.append(f"- **🔴 ממצאי הצוות האדום:** {n_red}  |  **🔵 איומים לטיפול הצוות הכחול:** {len(threats)}")
    lines.append("")

    # executive summary
    crit = [t for t in threats if t["severity"] in ("critical", "high")]
    lines.append("## סיכום מנהלים")
    if crit:
        lines.append(f"זוהו **{len(crit)}** איומים בחומרה גבוהה/קריטית הדורשים טיפול מיידי:")
        for t in crit:
            lines.append(f"- {_SEV_ICON[t['severity']]} **{t['name']}** ({_SEV_HE[t['severity']]})")
    else:
        lines.append("לא זוהו איומים בחומרה גבוהה. מומלץ ליישם את ההקשחות המפורטות למטה.")
    lines.append("")

    # blue team defenses
    lines.append("## 🔵 תוכנית ההגנה (Blue Team)")
    if not threats:
        lines.append("לא נמצאו ממצאים הניתנים למיפוי להגנה בשלב זה.")
    for i, t in enumerate(threats, 1):
        lines.append(f"### {i}. {_SEV_ICON[t['severity']]} {t['name']} — חומרה: {_SEV_HE[t['severity']]}")
        lines.append(f"**האיום:** {t['threat']}")
        if t.get("mitre"):
            lines.append(f"**MITRE ATT&CK:** {t['mitre']}")
        lines.append("")
        lines.append("**ממצאי הצוות האדום (עדות):**")
        for e in t["evidence"][:4]:
            lines.append(f"- `{e}`")
        lines.append("")
        lines.append("**🛡️ פעולות הגנה מומלצות:**")
        for d in t["defenses"]:
            lines.append(f"- {d}")
        lines.append("")
        lines.append("**👁️ זיהוי וניטור:**")
        for d in t["detections"]:
            lines.append(f"- {d}")
        if t.get("config"):
            lines.append("")
            lines.append("**תצורה לדוגמה:**")
            lines.append(f"```\n{t['config']}\n```")
        lines.append("")

    # learning
    lines.append("## 🧠 למידה מצטברת")
    if learning:
        lines.append(f"- הרצות עד כה: **{learning['runs']}**  |  סוגי ממצאים ידועים: **{learning['total_signatures']}**")
        if learning["new_this_run"]:
            lines.append(f"- **חדשים בהרצה זו:** {', '.join(learning['new_this_run'])}")
        else:
            lines.append("- אין סוגי ממצאים חדשים בהרצה זו (המערכת כבר הכירה את כולם).")
        if learning["top"]:
            lines.append("- הממצאים הנפוצים ביותר בהיסטוריה:")
            for x in learning["top"]:
                lines.append(f"  - {x['name']} — נצפה {x['count']} פעמים")
    lines.append("")
    lines.append("---")
    lines.append("*הופק ע\"י Kali Tools GUI · שכבת Purple Team (Red→Broker→Blue→Orchestrator). לשימוש הגנתי מורשה בלבד.*")
    return "\n".join(lines)
