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
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import db  # noqa: E402  (SQLite data store)

# ------------------------------------------------------ 📰 activity feed -----
def log_activity(entry):
    """Record one activity entry (for the dashboard magazine feed) in the DB."""
    db.add_activity(entry)

def load_activity():
    return db.list_activity()

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

# --------------------------------------------------- 🔧 remediation (fixer) ---
# Maps a threat signature to an automated fix APPLIED TO THE LOCAL HOST.
# risk: safe (additive, no lockout) | caution (reversible, may affect access)
#       | manual (no safe auto-fix — guidance only).
# Only 'safe'/'caution' carry commands; everything backs up configs first and
# requires explicit confirmation + audit before running.
REMEDIATIONS = {
    "ssh-exposed": {
        "title": "התקנת fail2ban נגד brute-force על SSH",
        "risk": "safe",
        "backup": [],
        "commands": [
            "export DEBIAN_FRONTEND=noninteractive",
            "apt-get update -qq",
            "apt-get install -y fail2ban",
            "systemctl enable --now fail2ban",
            "systemctl status fail2ban --no-pager | head -5",
        ],
        "note": "הגנה תוספתית בלבד — חוסמת תוקפים, לא אותך. אינה נוגעת ב-sshd_config.",
    },
    "outdated-software": {
        "title": "הפעלת עדכוני אבטחה אוטומטיים",
        "risk": "safe",
        "backup": [],
        "commands": [
            "export DEBIAN_FRONTEND=noninteractive",
            "apt-get update -qq",
            "apt-get install -y unattended-upgrades",
            "dpkg-reconfigure -f noninteractive unattended-upgrades || true",
            "systemctl enable --now unattended-upgrades || true",
            "echo installed unattended-upgrades",
        ],
        "note": "מתקין ומפעיל עדכוני אבטחה אוטומטיים. בטוח והפיך.",
    },
    "snmp-exposed": {
        "title": "עצירת שירות SNMP (אם רץ מקומית)",
        "risk": "caution",
        "backup": [],
        "commands": [
            "systemctl disable --now snmpd 2>/dev/null && echo 'snmpd stopped' || echo 'snmpd not present'",
        ],
        "note": "מכבה snmpd מקומי אם קיים. אם אתה משתמש ב-SNMP לניטור — דלג.",
    },
    "ftp-telnet": {
        "title": "עצירת שירותי FTP/Telnet לא מוצפנים",
        "risk": "caution",
        "backup": [],
        "commands": [
            "systemctl disable --now vsftpd 2>/dev/null && echo 'vsftpd stopped' || echo 'no vsftpd'",
            "systemctl disable --now telnet.socket inetd 2>/dev/null && echo 'telnet stopped' || echo 'no telnet'",
        ],
        "note": "מכבה vsftpd/telnet מקומיים אם קיימים.",
    },
    # web/tls/header fixes depend on the specific web server config; guidance only
    "no-tls": {"title": "אכיפת HTTPS", "risk": "manual", "backup": [], "commands": [],
               "note": "תלוי בשרת הווב. ב-Caddy הפניית 80→443 אוטומטית; ב-nginx/apache — ראה 'תצורה לדוגמה'."},
    "missing-security-header": {"title": "הוספת כותרות אבטחה", "risk": "manual", "backup": [], "commands": [],
               "note": "יש להוסיף לתצורת שרת הווב (ראה snippet ב'תצורה לדוגמה')."},
    "weak-tls": {"title": "הקשחת TLS", "risk": "manual", "backup": [], "commands": [],
               "note": "עדכן את תצורת ה-TLS של שרת הווב לפרוטוקולים 1.2+ בלבד."},
    "injection": {"title": "הגנה מהזרקות", "risk": "manual", "backup": [], "commands": [],
               "note": "דורש שינוי קוד (prepared statements) + WAF — לא ניתן לתיקון אוטומטי בטוח."},
}


def get_remediation(signature):
    """Return the automated remediation plan for a signature, or None."""
    return REMEDIATIONS.get(signature)

# ----------------------------------------------- 🔎 detection rules (Blue) ----
# Ready-to-deploy detection content for each threat: Sigma (SIEM/log analytics)
# and/or Suricata (network IDS). Defensive only — these DETECT the activity, so
# the Blue Team can alert on it. Not every threat has both (some are posture/
# absence, not a discrete event).
DETECTION_RULES = {
    "ssh-exposed": {
        "sigma": ("title: SSH Brute-Force (Multiple Auth Failures)\n"
                  "logsource:\n  product: linux\n  service: auth\n"
                  "detection:\n  sel:\n    message|contains: 'Failed password'\n"
                  "  timeframe: 5m\n  condition: sel | count() by src_ip > 10\n"
                  "level: high"),
        "suricata": ('alert tcp any any -> $HOME_NET 22 (msg:"SSH brute-force attempt"; '
                     'flow:to_server; threshold:type both,track by_src,count 10,seconds 60; '
                     'classtype:attempted-recon; sid:1000001; rev:1;)'),
    },
    "smb-exposed": {
        "sigma": ("title: Anonymous SMB Logon\n"
                  "logsource:\n  product: windows\n  service: security\n"
                  "detection:\n  sel:\n    EventID: 4624\n    LogonType: 3\n"
                  "    TargetUserName: 'ANONYMOUS LOGON'\n  condition: sel\nlevel: medium"),
        "suricata": ('alert tcp $EXTERNAL_NET any -> $HOME_NET 445 (msg:"SMB exposed to external network"; '
                     'flow:to_server; classtype:policy-violation; sid:1000002; rev:1;)'),
    },
    "rdp-exposed": {
        "sigma": ("title: RDP Brute-Force (Failed Logons)\n"
                  "logsource:\n  product: windows\n  service: security\n"
                  "detection:\n  sel:\n    EventID: 4625\n    LogonType: 10\n"
                  "  timeframe: 5m\n  condition: sel | count() by IpAddress > 10\nlevel: high"),
        "suricata": ('alert tcp $EXTERNAL_NET any -> $HOME_NET 3389 (msg:"RDP exposed to external network"; '
                     'flow:to_server; classtype:policy-violation; sid:1000003; rev:1;)'),
    },
    "no-tls": {
        "suricata": ('alert tcp $HOME_NET 80 -> $EXTERNAL_NET any (msg:"Cleartext HTTP service exposed"; '
                     'flow:from_server,established; classtype:policy-violation; sid:1000004; rev:1;)'),
    },
    "ftp-telnet": {
        "suricata": ('alert tcp any any -> $HOME_NET [21,23] (msg:"Cleartext FTP/Telnet protocol in use"; '
                     'flow:to_server; classtype:policy-violation; sid:1000005; rev:1;)'),
    },
    "snmp-exposed": {
        "suricata": ('alert udp $EXTERNAL_NET any -> $HOME_NET 161 (msg:"SNMP default community string (public)"; '
                     'content:"|04 06|public"; classtype:attempted-recon; sid:1000006; rev:1;)'),
    },
    "exposed-path": {
        "sigma": ("title: Access to Sensitive Web Path\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    c-uri|contains:\n      - '/.git'\n      - '/.env'\n"
                  "      - '/admin'\n      - '/backup'\n      - '/server-status'\n  condition: sel\nlevel: medium"),
        "suricata": ('alert http $EXTERNAL_NET any -> $HOME_NET any (msg:"Access to sensitive path (.git/.env/admin)"; '
                     'flow:to_server; http.uri; pcre:"/(\\.git|\\.env|\\/admin|\\/backup)/i"; '
                     'classtype:web-application-attack; sid:1000007; rev:1;)'),
    },
    "injection": {
        "sigma": ("title: Web SQLi/XSS Pattern in Request\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    c-uri|re: '(?i)(union\\s+select|or\\s+1=1|<script>|\\.\\./)'\n"
                  "  condition: sel\nlevel: high"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"Possible SQL injection / XSS in URI"; '
                     'flow:to_server; http.uri; pcre:"/(union.+select|or\\s+1=1|<script>)/i"; '
                     'classtype:web-application-attack; sid:1000008; rev:1;)'),
    },
    "weak-tls": {
        "suricata": ('alert tls any any -> $HOME_NET any (msg:"Weak SSL/TLS version negotiated (SSLv3/TLS1.0)"; '
                     'ssl_version:sslv3,tls1.0; classtype:protocol-command-decode; sid:1000009; rev:1;)'),
    },
    "directory-indexing": {
        "suricata": ('alert http $HOME_NET any -> $EXTERNAL_NET any (msg:"Directory indexing page served"; '
                     'flow:from_server; http.response_body; content:"Index of /"; nocase; '
                     'classtype:web-application-attack; sid:1000010; rev:1;)'),
    },
    "default-file": {
        "sigma": ("title: Access to Default/Sample Files\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    c-uri|contains:\n      - '/icons/README'\n"
                  "      - '/manual/'\n      - '/phpinfo'\n  condition: sel\nlevel: low"),
    },
}


def get_detections(signature):
    """Return {sigma?, suricata?} detection rules for a signature (may be empty)."""
    return DETECTION_RULES.get(signature, {})

# ------------------------------------------ 🍯 threat-informed prioritising ---
def active_threats():
    """Posture signature -> the honeypot evidence that it is under live attack.

    Severity alone ranks findings by how bad they COULD be. This adds whether
    anyone is actually trying it, which is the difference between a theoretical
    risk and one being exercised against us this week. Fails soft: with no
    honeypots the report is exactly what it always was.
    """
    try:
        rows = db.hp_correlate()
    except Exception:
        return {}
    out = {}
    for c in rows:
        cur = out.get(c["weakness"])
        if not cur or c["attack_count"] > cur["count"]:
            out[c["weakness"]] = {"name": c["attack_name"], "count": c["attack_count"],
                                  "severity": c["attack_severity"]}
    return out

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
            dr = DETECTION_RULES.get(rule["id"], {})
            t = {
                "signature": rule["id"], "name": rule["name"], "severity": rule["severity"],
                "threat": rule["threat"], "defenses": rule["defenses"], "detections": rule["detections"],
                "config": rule.get("config", ""), "mitre": rule.get("mitre", ""),
                "sigma": dr.get("sigma", ""), "suricata": dr.get("suricata", ""),
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
    return db.load_kb()

def update_kb(threats, when):
    """Accumulate signatures across runs (in the DB); returns a learning summary."""
    return db.update_kb(threats, when)

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

    # 🍯 which of these findings are attackers actually exercising right now
    live = active_threats()
    under_attack = [t for t in threats if t["signature"] in live]

    # executive summary
    crit = [t for t in threats if t["severity"] in ("critical", "high")]
    lines.append("## סיכום מנהלים")
    if under_attack:
        lines.append("### 🔥 תעדוף מיידי — חולשות שתוקפים מנסים לנצל *עכשיו*")
        lines.append("הממצאים הבאים אינם תיאורטיים: המלכודות שלנו קלטו ניסיונות ניצול פעילים "
                     "מולם. טפל בהם ראשונים.")
        for t in sorted(under_attack, key=lambda x: -live[x["signature"]]["count"]):
            a = live[t["signature"]]
            lines.append(f"- {_SEV_ICON[t['severity']]} **{t['name']}** — "
                         f"נצפו **{a['count']}** ניסיונות מסוג *{a['name']}* נגד המלכודות")
        lines.append("")
    if crit:
        lines.append(f"זוהו **{len(crit)}** איומים בחומרה גבוהה/קריטית הדורשים טיפול מיידי:")
        for t in crit:
            lines.append(f"- {_SEV_ICON[t['severity']]} **{t['name']}** ({_SEV_HE[t['severity']]})")
    elif not under_attack:
        lines.append("לא זוהו איומים בחומרה גבוהה. מומלץ ליישם את ההקשחות המפורטות למטה.")
    lines.append("")

    # blue team defenses
    lines.append("## 🔵 תוכנית ההגנה (Blue Team)")
    if not threats:
        lines.append("לא נמצאו ממצאים הניתנים למיפוי להגנה בשלב זה.")
    for i, t in enumerate(threats, 1):
        lines.append(f"### {i}. {_SEV_ICON[t['severity']]} {t['name']} — חומרה: {_SEV_HE[t['severity']]}")
        if t["signature"] in live:
            a = live[t["signature"]]
            lines.append(f"> 🔥 **תחת תקיפה פעילה.** המלכודות שלנו קלטו **{a['count']}** "
                         f"ניסיונות *{a['name']}* — זו אינה חולשה תיאורטית.")
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
        if t.get("sigma") or t.get("suricata"):
            lines.append("")
            lines.append("**🔎 חוקי זיהוי מוכנים לפריסה:**")
            if t.get("sigma"):
                lines.append("*Sigma (SIEM / ניתוח לוגים):*")
                lines.append(f"```yaml\n{t['sigma']}\n```")
            if t.get("suricata"):
                lines.append("*Suricata (IDS ברמת הרשת):*")
                lines.append(f"```\n{t['suricata']}\n```")
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

    # 🍯 the second knowledge base: not what we scanned, but what the world tried
    try:
        hp = db.hp_stats()
    except Exception:
        hp = None
    # Gate on either: hp_events is capped at 20k rows, so on a busy pot the raw
    # events get trimmed while the accumulated signatures — the actual learning —
    # live on. Keying the section off events alone would hide the knowledge
    # precisely on the systems that gathered the most of it.
    if hp and (hp.get("events") or hp.get("signatures")):
        lines.append("")
        lines.append("### 🍯 מודיעין ממלכודות הדבש")
        if hp.get("events"):
            lines.append(f"- נקלטו **{hp['events']}** תקיפות אמיתיות מ-**{hp['attackers']}** "
                         f"כתובות שונות ({hp['events_24h']} ב-24 השעות האחרונות).")
        if hp.get("signatures"):
            lines.append("- הטכניקות שתוקפים מנסים בפועל:")
            for s in hp["signatures"][:5]:
                lines.append(f"  - {_SEV_ICON.get(s['severity'], '⬜')} {s['name']} — "
                             f"{s['count']}×")
        lines.append("- *הידע הזה מוזן חזרה לתכנון: הצוות האדום בודק את מה שתוקפים "
                     "באמת מנסים, לא רק צ'קליסט קבוע.*")
    lines.append("")
    lines.append("---")
    lines.append("*הופק ע\"י Kali Tools GUI · שכבת Purple Team (Red→Broker→Blue→Orchestrator). לשימוש הגנתי מורשה בלבד.*")
    return "\n".join(lines)
