# התקנה ודרישות מקדימות — Kali Tools GUI

מדריך זה מפרט **מה צריך להתקין לפני ההפעלה** ואיך להריץ. המערכת מיועדת ל‑Windows עם Kali Linux תחת WSL2.

---

## 1. דרישות מקדימות (Prerequisites)

| רכיב | גרסה מומלצת | בדיקה |
|------|--------------|--------|
| Windows 10/11 | 64‑bit | — |
| WSL2 | הגרסה העדכנית | `wsl --version` |
| Kali Linux (WSL) | Rolling 2025+ | `wsl -l -v` |
| Python 3 (בתוך Kali) | 3.9+ | `wsl -d kali-linux -u root -- python3 --version` |
| דפדפן מודרני | Chrome/Edge/Firefox | — |

> אין צורך ב‑pip או בחבילות פייתון חיצוניות — השרת משתמש בספרייה הסטנדרטית בלבד.

---

## 2. התקנת WSL + Kali (אם עדיין לא מותקן)
ב‑PowerShell כמנהל:
```powershell
wsl --install
wsl --install -d kali-linux
```
אתחל את המחשב אם התבקשת, ואז פתח את Kali פעם אחת כדי לסיים אתחול ראשוני.

---

## 3. התקנת כלי ה‑Kali
התקנת ברירת המחדל של Kali‑WSL היא **מינימלית** (כמעט בלי כלים). בחר אחת:

**א. סט סטנדרטי (מומלץ, ~2–4GB):**
```bash
sudo apt update && sudo apt install -y kali-linux-default
```

**ב. הכול (כבד מאוד, עשרות GB):**
```bash
sudo apt update && sudo apt install -y kali-linux-everything
```

**ג. כלים בודדים לפי הצורך** — או פשוט דרך כפתור ההתקנה בממשק.

> המערכת מזהה אוטומטית אילו כלים מותקנים; אין חובה להתקין הכול מראש.

---

## 4. הרשאות (root)
כדי שכל הכלים יעבדו (כולל nmap ‑sS, tcpdump, masscan) המערכת מורצת כ‑**root**.
ב‑WSL אפשר להריץ כ‑root **ללא סיסמה** באמצעות `-u root` — כפי שעושה סקריפט ההפעלה.

---

## 5. תיקון DNS ב‑WSL (אם דומיינים חיצוניים לא נפתרים)
```bash
# כ-root בתוך Kali:
printf '[network]\ngenerateResolvConf = false\n' | sudo tee /etc/wsl.conf
sudo rm -f /etc/resolv.conf
printf 'nameserver 8.8.8.8\nnameserver 1.1.1.1\n' | sudo tee /etc/resolv.conf
```
ואז ב‑PowerShell: `wsl --shutdown` והפעל מחדש.

---

## 6. הפעלה
```powershell
C:\ClaudeCode\kali-gui\start.ps1
```
או ידנית:
```powershell
wsl -d kali-linux -u root -- python3 /mnt/c/ClaudeCode/kali-gui/server.py
```
פתח בדפדפן: **http://localhost:8777**

עצירה:
```powershell
wsl -d kali-linux -u root -- pkill -f server.py
```

---

## 7. (אופציונלי) מנוע AI מקומי
לשדרוג ניסוח הדוחות באמצעות LLM מקומי:
```bash
# התקן Ollama בתוך Kali והורד מודל:
ollama pull llama3.2
```
הרץ את השרת עם משתני הסביבה `OLLAMA_URL=http://localhost:11434` ו‑`OLLAMA_MODEL=llama3.2`.
ללא זה — הסוכנים עובדים מצוין במנוע מבוסס‑החוקים.

---

## 8. פתרון תקלות נפוצות
| תקלה | פתרון |
|------|--------|
| הדף לא נטען | ודא שהשרת רץ ושאין חוסם על פורט 8777 |
| כלי מסומן "לא מותקן" | לחץ התקן, או `apt install <package>` |
| "דרוש root" בכלי | ודא שהרצת עם `-u root` (סקריפט ההפעלה עושה זאת) |
| דומיין לא נפתר | בצע את שלב 5 (תיקון DNS) |
| כלי אלחוטי לא עובד | WSL ללא גישת Wi‑Fi monitor mode — צפוי |
