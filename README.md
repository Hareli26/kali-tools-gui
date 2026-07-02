# Kali Tools GUI 🐉

ממשק גרפי (web) לכלי ה‑Kali Linux שרצים תחת WSL2 על Windows.

**שני מצבי עבודה:**
- **🧰 כלים** — בחירת כלי → טופס יכולות + תצוגת פקודה חיה → הרצה → מסך תוצאות נפרד.
- **🤖 עוזר AI** — תאר במילים שלך מה לבדוק, ושכבת סוכנים תתכנן, תריץ, תאמת ותפיק דוח.

## למה זה עובד בכל מצב
Kali WSL בהתקנת ברירת מחדל היא **מינימלית** — רוב הכלים לא מותקנים.
המערכת **מזהה אוטומטית** אילו כלים מותקנים:
- כלי מותקן → ניתן להריץ מיד.
- כלי חסר → כרטיס מסומן "לא מותקן" + כפתור התקנה (דרך `apt` עם סיסמת sudo מקומית).
הרשימה מתעדכנת ככל שמתקינים עוד כלים.

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

## הרשאות (root)
השרת מורץ כ‑**root** בתוך WSL (`wsl -u root` — ללא סיסמה) כדי שכל הכלים יעבדו
(nmap -sS, tcpdump, masscan, hping3 ...) וגם התקנת חבילות ללא סיסמה.

## הרצה
מ‑PowerShell ב‑Windows:
```powershell
C:\ClaudeCode\kali-gui\start.ps1
```
או ידנית:
```powershell
wsl -d kali-linux -u root -- python3 /mnt/c/ClaudeCode/kali-gui/server.py
# ואז דפדפן: http://localhost:8777
```
WSL2 מעביר `localhost` אוטומטית — הדפדפן ב‑Windows ניגש ישירות.

עצירה:
```powershell
wsl -d kali-linux -u root -- pkill -f server.py
```

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
