# Kali Tools GUI 🐉

ממשק גרפי (web) לכלי ה‑Kali Linux שרצים תחת WSL2 על Windows.

**מצבי עבודה ומסכים:**
- **🧰 כלים** — בחירת כלי → טופס יכולות + תצוגת פקודה חיה → הרצה → מסך תוצאות נפרד.
- **🤖 עוזר AI** — תאר במילים שלך מה לבדוק, ושכבת סוכנים תתכנן, תריץ, תאמת ותפיק דוח.
- **📊 מרכז בקרה** — מצב הסוכנים החי, מודיעין נצבר, יומן פעילות, ותצוגת "מוח סוכן".
- **📓 Obsidian** — גרף קשרים אינטראקטיבי בין דוחות לאיומים (בתוך המערכת).
- **👥 משתמשים** — (אדמין) ניהול חשבונות Google מורשים לכניסה.

**🛰️ סרגל ריצה גלובלי:** כל עוד משימה פעילה, סרגל תחתון מראה בכל מסך מה הסוכן עושה כרגע
(הכלי הנוכחי + התקדמות) עם חזרה בלחיצה. המשימות רצות בשרת ואינן נעצרות בניווט.

## למה זה עובד בכל מצב
Kali WSL בהתקנת ברירת מחדל היא **מינימלית** — רוב הכלים לא מותקנים.
המערכת **מזהה אוטומטית** אילו כלים מותקנים:
- כלי מותקן → ניתן להריץ מיד.
- כלי חסר → כרטיס מסומן "לא מותקן" + כפתור התקנה (דרך `apt` עם סיסמת sudo מקומית).
הרשימה מתעדכנת ככל שמתקינים עוד כלים. ההצלחה נקבעת לפי **האם הכלי המבוקש אכן הותקן**
(`dpkg-query`) ולא לפי קוד היציאה של `apt` — כך ששדרוג נלווה שנכשל אינו מדווח כשל שווא.

## ארכיטקטורה
- **Backend** — `server.py`: Python בספרייה הסטנדרטית בלבד (ללא pip). רץ **בתוך** Kali WSL.
  בונה את הפקודה כמערך `argv` מתוך `tools.json` (מקור אמת), **ללא shell** — הגנה מהזרקת פקודות.
  מודל *jobs* להרצות ארוכות עם פלט מוזרם וכפתור עצירה.
- **Frontend** — `web/`: SPA ב‑vanilla JS (ללא build), RTL, ערכת נושא כהה. 3 מסכים:
  1. `index.html` #screen-picker — בחירת כלי (חיפוש + קטגוריות + כרטיסים).
  2. #screen-form — טופס דינמי לפי הגדרת הכלי + תצוגת פקודה חיה.
  3. #screen-results — פלט חי, סטטוס, עצירה, העתקה, הורדה, הרצה חוזרת.
- **קטלוג** — `tools.json`: 70 כלים ב‑11 קטגוריות (Recon, DNS, Network, Web, SMB,
  Passwords, SSL/TLS, Exploitation, Forensics, Wireless, Utilities). קל להרחבה (ראה למטה).
  הפלט מנוקה מקודי ANSI אוטומטית.
- **שכבת סוכנים** — `agents.py`: מנוע playbooks מבוסס-חוקים (אפס תלויות). ארבעה סוכנים:
  - **Planner** — כוונה בשפה חופשית + מטרה → תוכנית שלבים (בחירת כלים + פקודות מוכנות + הצעות).
  - **Executor** — מריץ כל שלב ברצף (משתמש בתשתית ה‑jobs).
  - **Verifier** — מנתח פלט + קוד יציאה → verdict (תקין / ממצאים / אזהרה / נכשל) + חילוץ ממצאים.
  - **Reporter** — מרכיב דוח Markdown מלא.
  - וו LLM אופציונלי: אם מוגדרים `OLLAMA_URL` + `OLLAMA_MODEL` הדוח משתדרג לניסוח AI.
- **מסכי AI** — #screen-ai-prompt → #screen-ai-plan → #screen-ai-mission → #screen-ai-report.
- **שכבת Purple Team** — `bluered.py`: מערך סוכנים הגנתי מעל הצוות האדום.
  - **🔴 צוות אדום** — מנוע המשימות מריץ כלים התקפיים ומפיק ממצאים.
  - **🟢 מתווך (Broker)** — ממפה כל ממצא אדום לכלל הגנה, מאחד ומדרג לפי חומרה.
  - **🔵 צוות כחול** — לכל איום: פעולות הגנה, זיהוי/ניטור, שיוך MITRE ATT&CK ותצורה לדוגמה.
  - **🧠 למידה מתמשכת** — `knowledge.json` צובר חתימות ממצאים בין הרצות (מונה + first/last seen).
  - **🟣 מתזמר (Orchestrator)** — מריץ את הזרימה ומפיק דוח Purple מלא.
  - הרצה: כפתור "🟣 Purple Team" במסך התוכנית. נקודות קצה: `/api/purple`, `/api/knowledge`.
- **🔧 סוכן מתקן (Remediation)** — `bluered.py`: מיישם בפועל את הגנות הצוות הכחול (למשל fail2ban,
  עדכוני אבטחה) — **תמיד לאחר אישור מפורש**, עם גיבוי קונפיגים ורישום ביומן. תיקונים מסוכנים
  (SSH/firewall) הם הנחיה בלבד ואינם רצים אוטומטית. נקודות קצה: `/api/fix/<sig>`, `/api/fix`.
- **🗄️ אחסון** — `db.py`: SQLite (חתימות, פעילות, ביקורת, דוחות) עם הגירה אוטומטית מקבצי JSON ישנים.
- **📓 ייצוא Obsidian** — `obsidian.py`: כספת Markdown (frontmatter + wikilinks + MOC) המתעדכנת
  אוטומטית אחרי כל בדיקה; תצוגת גרף מובנית דרך `/api/vault/graph`.
- **🤖 שרת MCP** — `mcp/`: חושף את המערכת ככלים ש‑Claude/כל לקוח MCP יכול להפעיל בשיחה.
- **☁️ פריסה בענן** — `deploy/install-vps.sh`: Caddy (HTTPS) → oauth2-proxy (Google + allowlist)
  → האפליקציה (127.0.0.1). ניהול משתמשים מהממשק (`/api/users`, אדמין בלבד) ולוג ביקורת מלא.

## הרשאות (root)
השרת מורץ כ‑**root** בתוך WSL כדי שכל הכלים יעבדו (nmap -sS, tcpdump, masscan ...)
וגם התקנת חבילות ללא סיסמה.

## הרצה — ייצור (מומלץ)
התקנה חד‑פעמית כשירות systemd שמופעל אוטומטית ומתאושש מקריסה:
```powershell
C:\ClaudeCode\kali-gui\install-service.ps1
```
זה מתקין את `kali-gui.service` (enable + start), ורושם משימת Windows שמעלה את WSL בכל התחברות.
לאחר מכן פתח: **http://localhost:8777**

ניהול:
```powershell
wsl -d kali-linux -u root -- systemctl status kali-gui     # מצב
wsl -d kali-linux -u root -- systemctl restart kali-gui    # הפעלה מחדש
wsl -d kali-linux -u root -- journalctl -u kali-gui -n 50  # לוגים
```

## הרצה — פיתוח (ad-hoc)
```powershell
C:\ClaudeCode\kali-gui\start.ps1
# עצירה:
wsl -d kali-linux -u root -- pkill -f server.py
```

## אבטחת ייצור
- **מאזין ל‑127.0.0.1 בלבד** (לא חשוף לרשת) — WSL2 מעביר `localhost` מ‑Windows.
- **טוקן אופציונלי**: הגדר `KALIGUI_TOKEN` (ב‑`docs/kali-gui.service`) כדי לדרוש אימות.
- בדיקת בריאות: `GET /api/health` (ללא אימות) → גרסה, uptime.
- דוחות נשמרים ב‑`reports/<id>.json` ושורדים אתחולים (`/api/reports`, `/api/report/<id>`).
- משתני סביבה: `KALIGUI_PORT`, `KALIGUI_HOST`, `KALIGUI_STEP_TIMEOUT`, `KALIGUI_MAX_KEEP`.

## הפעלת מנוע AI אמיתי (אופציונלי)
כברירת מחדל הסוכנים מבוססי-חוקים (עובד מיד). לניסוח דוחות ע"י LLM מקומי:
```powershell
# ב-WSL: הורד מודל
wsl -d kali-linux -u root -- ollama pull llama3.2
# הרץ את השרת עם:  OLLAMA_URL=http://localhost:11434  OLLAMA_MODEL=llama3.2
```

## הוספת כלי חדש לקטלוג
ערוך את `tools.json`, הוסף אובייקט ל‑`tools`:
```jsonc
{
  "id": "myttool", "name": "MyTool", "binary": "mytool",
  "package": "mytool", "category": "web",
  "desc": "תיאור קצר",
  "options": [
    { "id": "flagx", "flag": "-x", "label": "אפשרות", "type": "bool" },
    { "id": "target", "flag": "", "label": "מטרה", "type": "text",
      "primary": true, "required": true, "placeholder": "example.com" }
  ]
}
```
סוגי שדות: `text`, `number`, `select` (עם `choices:[{v,t}]`), `bool`, plus `primary` (מטרה positional אחרונה),
`eq:true` (מייצר `flag=value`), `default`, `required`, `help`.
שדה עם `flag:""` ולא `primary` → הערך מוכנס כטוקן ישיר (למשל `nmap -sS`, `dig MX`).

## אבטחה ואחריות
- הפקודות נבנות בצד השרת מ‑`tools.json` ומורצות כ‑`argv` ללא shell.
- ⚠️ הרץ כלי בדיקות **אך ורק** על מטרות שיש לך הרשאה חוקית מפורשת לבדוק.
- הסיסמה בשדה ההתקנה משמשת מקומית ל‑`sudo` בלבד ואינה נשמרת.
