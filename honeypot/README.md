# 🍯 מלכודות דבש — Deception Layer

שכבת הטעיה שמזינה את הצוות הכחול ב**תקיפות אמיתיות** במקום בסימולציות בלבד.

```
   🌐 האינטרנט (תוקפים + בוטים)
            │
   ┌────────┴──────────────────────┐
   │  🍯 שרת המלכודות (מוקרב)       │   web_pot.py — טיפש בכוונה:
   │  web.dudaei.com               │   מגיש פיתיונות, כותב JSONL. זהו.
   └────────┬──────────────────────┘
            │  הפרודקשן מושך ← המלכודת לא דוחפת
            ▼
   ┌───────────────────────────────┐
   │  🛡️ kali.dudaei.com (המוח)     │   attack_kb.py — מסווג טכניקות
   │  → Broker → צוות כחול → DB     │   → Sigma/Suricata → המלצות הקשחה
   └───────────────────────────────┘
```

## ⚠️ כללי ברזל

**1. לעולם לא על שרת הפרודקשן.**
מלכודת היא שרת שאתה *מזמין* לפרוץ אליו. אם היא רצה על אותה מכונה כמו
`kali.dudaei.com`, פריצה מוצלחת נותנת דריסת רגל על ה-DB, ה-audit log וה-OAuth
של כל המערכת. הפעל אותה על השרת המוקרב בלבד.

**2. המלכודת לא מריצה כלום.**
אינטראקציה נמוכה (low-interaction): אין shell, אין `eval`, אין `subprocess`,
אין מנוע SQL. **כל** תשובה היא מחרוזת קבועה מראש. אין למה להזריק — וזה גם מה
שהופך אותה לבטוחה וגם למה שהופך אותה לפשוטה.

**3. המלכודת לא מסווגת.**
היא מתעדת גולמי בלבד. הניתוח קורה בפרודקשן, כך שפריצה למלכודת **לא יכולה
להרעיל את המסווג**.

**4. כיוון התקשורת: הפרודקשן מושך.**
אילו המלכודת הייתה דוחפת, היא הייתה צריכה credential לפרודקשן — ואם יפרצו
אותה, ה-credential הזה בידי התוקף. במשיכה, המלכודת לא מחזיקה שום מפתח.

**5. כל התוכן מזויף.**
המשתמשים, ה-`.env`, מפתחות ה-AWS, ה-dump של ה-DB — הכול המצאה. אין נתון אמיתי
אחד מאחורי המלכודת.

> ⚖️ הטעיה מורשית על תשתית שבבעלותך בלבד. אל תפנה את זה לאף אחד אחר.

---

## 🗂️ הרכיבים

| קובץ | רץ על | תפקיד |
|---|---|---|
| `web_pot.py` | 🍯 שרת המלכודות | מגיש אתר חברה מזויף עם פיתיונות; כותב `events.jsonl` |
| `sql_pot.py` | 🍯 שרת המלכודות | **MySQL מזויף (פורט 3306)** — מקבל כל התחברות, מגיש נתונים מזויפים, מריץ כלום |
| `ssh_pot.py` | 🍯 שרת המלכודות | **SSH מזויף (פורט 22)** — לוכד כל שם-משתמש+סיסמה, תמיד דוחה, אין shell (תלוי ב-paramiko) |
| `collector.py` | 🍯 שרת המלכודות | מגיש את האירועים לפרודקשן, מוגן בטוקן (פורט נפרד לכל מלכודת) |
| `attack_kb.py` | 🛡️ פרודקשן | מסווג בקשה גולמית → טכניקת תקיפה (19 טכניקות) |
| `../sensor.py` | 🛡️ פרודקשן | מושך מכל מלכודת, מסווג, ומצטבר ל-DB |

### למה שני בסיסי ידע?

`attack_kb.ATTACK_KB` הוא **התאום ההפוך** של `bluered.DEFENSE_KB` — וההבחנה מהותית:

| | מקור | סמנטיקה |
|---|---|---|
| `DEFENSE_KB` | הצוות האדום שלנו | **"למטרה הזו יש חולשה"** (תנוחה) |
| `ATTACK_KB` | מלכודות הדבש | **"מישהו ניסה את הטכניקה הזו"** (התנהגות) |

הזרמת אירועי מלכודת דרך `DEFENSE_KB` הייתה רושמת טענה שגויה ("למטרה שלי יש
חולשת הזרקה" במקום "מישהו ניסה להזריק") **ומזהמת את סטטיסטיקות התנוחה**. לכן
שני בסיסי ידע ושתי טבלאות חתימות נפרדות.

**ההצלבה ביניהם היא הערך:** טכניקה שתוקפים מנסים *באמת*, נגד חולשה שהסריקה שלנו
מצאה — זה תעדוף מבוסס איום אמיתי.

---

## 🎣 הפיתיונות

| נתיב | מה מוגש | מה נלמד |
|---|---|---|
| `/` `/services` `/about` | אתר לוגיסטיקה סביר | תנועת בסיס (baseline) |
| `/robots.txt` | `Disallow:` ל-`/admin`, `/backup`, `/.git` | פירורי לחם — מי הולך אחריהם |
| `/.env` | משתני סביבה מזויפים + מפתחות AWS מזויפים | ציד סודות |
| `/.git/config` | remote מזויף | ציד סודות |
| `/backup/db-backup.sql` | dump מזויף עם hashes מזויפים | ציד סודות |
| `/api/v1/users?id=` | **נראה פגיע ל-SQLi**; מחזיר שגיאת MySQL מזויפת | payloads של SQLi, זיהוי sqlmap |
| `/login` `/wp-login.php` `/admin` | טופס שתמיד נכשל | **את האישורים שניסו** |
| `/phpmyadmin` `/server-status` | פאנלים מזויפים | מיפוי ממשקי ניהול |

הפיתיון של ה-SQL מחזיר `500` עם **שגיאת MySQL מזויפת** על payload חשוד — כדי
שהתוקף יאמין שהצליח, יעמיק, ויחשוף עוד מהטכניקה שלו ללוג. אין מנוע SQL מאחור.

---

## 🚀 התקנה — שני השרתים

### שלב 1 · 🍯 שרת המלכודת (187.124.189.97)

**דרישות קדם: `python3` בלבד.** המלכודות הן stdlib טהור — אין pip, אין חבילות apt.
זה מכוון: ה-apt בשרת הזה שבור (Ubuntu/Kali מעורבבים), ומלכודת שאי אפשר לפרוס
היא מלכודת שאין לך.

```bash
ssh root@187.124.189.97

# בדיקת דרישות קדם — כנראה כבר מותקן
python3 --version || apt-get install -y python3   # דרוש 3.7+

# הבא את הקוד (בלי git? ראה חלופה למטה)
apt-get install -y git 2>/dev/null || true
git clone https://github.com/Hareli26/kali-tools-gui /opt/src
cd /opt/src && chmod +x deploy/install-honeypot.sh

# התקן — הסקריפט יסרב לרוץ אם הוא מזהה פרודקשן
HP_DOMAIN=web.dudaei.com HP_PROD_IP=72.62.150.169 ./deploy/install-honeypot.sh
```

**הסקריפט מדפיס טוקן בסוף — העתק אותו.**

<details><summary>אין git על השרת? העתק שני קבצים ישירות</summary>

```bash
# מהמחשב שלך
scp honeypot/web_pot.py honeypot/collector.py root@187.124.189.97:/opt/honeypot/
scp deploy/install-honeypot.sh root@187.124.189.97:/tmp/
ssh root@187.124.189.97 'cd /tmp && HP_DOMAIN=web.dudaei.com HP_PROD_IP=72.62.150.169 bash install-honeypot.sh'
```
</details>

### שלב 2 · 🛡️ שרת הפרודקשן (kali.dudaei.com)

```bash
ssh root@72.62.150.169
cd /opt/kali-gui && git pull && systemctl restart kali-gui

# רשום את המלכודת + הפעל פולינג אוטומטי כל 60 שניות
chmod +x deploy/install-sensor.sh
POT_ID=web POT_URL=http://187.124.189.97:8081 POT_TOKEN='<הטוקן משלב 1>' \
  ./deploy/install-sensor.sh
```

לחלופין דרך ה-UI: מסך **🍯 מלכודות** → **➕ הוסף מלכודת**.

### שלב 3 · אימות

```bash
# על המלכודת
systemctl status web-pot hp-collector
curl -s localhost:8081/health

# תקוף אותה מכל מקום — התקיפה תופיע ב-kali.dudaei.com תוך דקה
curl "http://web.dudaei.com/api/v1/users?id=1'%20OR%201=1--"
curl -A "sqlmap/1.7" http://web.dudaei.com/.env

# על הפרודקשן
journalctl -u kali-sensor -f
cd /opt/kali-gui && python3 sensor.py --list
```

| פורט | חשיפה | למה |
|---|---|---|
| `80/443` → `8080` | 🌍 **כל העולם** | זה הפיתיון. זו כל המטרה. |
| `8081` (קולקטור) | 🔒 **רק 72.62.150.169** | ערוץ ניהול. מוגן בטוקן **וגם** ב-firewall. |

---

## 🚀 הרצה ידנית (פיתוח)

```bash
# ברירת מחדל: 0.0.0.0:8080, אירועים -> ./events.jsonl
python3 web_pot.py

# פרודקשן
HP_PORT=8080 HP_EVENTS=/var/log/honeypot/web.jsonl python3 web_pot.py
```

| משתנה | ברירת מחדל | תיאור |
|---|---|---|
| `HP_PORT` | `8080` | פורט האזנה |
| `HP_BIND` | `0.0.0.0` | כתובת האזנה |
| `HP_EVENTS` | `./events.jsonl` | נתיב לוג האירועים |
| `HP_SITE` | `Dudaei Logistics Ltd` | שם החברה המזויפת |

המלכודת **נכשלת בקול בהפעלה** אם לוג האירועים אינו ניתן לכתיבה — `log_event()`
בולע שגיאות בכוונה (כדי שבקשה זדונית לא תפיל אותה), ובלי הבדיקה הזו מלכודת עם
נתיב שגוי הייתה נראית בריאה ולא מתעדת כלום.

### 🐬 מלכודת MySQL (`sql_pot.py`, פורט 3306)

מדברת מספיק מפרוטוקול MySQL כדי שקליינט אמיתי יאמין שהתחבר: שולחת handshake
תקין, **מקבלת כל אישור** (כדי שהתוקף יחשוף מה הוא עושה אחרי כניסה), ועונה על
שאילתות סיור בנתונים מזויפים. אין מנוע SQL — כל תשובה קבועה מראש.

**קבלת כל התחברות היא בחירה מכוונת:** מלכודת שדוחה התחברויות לומדת רק שמות
משתמש; מלכודת שמקבלת אותן לומדת את הפלייבוק שאחרי הכניסה — כתיבת webshell עם
`INTO OUTFILE`, RCE דרך UDF, שאיבת `mysql.user` — וזה המודיעין ששווה משהו.

```bash
HP_SQL_PORT=3306 HP_SQL_EVENTS=/var/log/honeypot/sql.jsonl python3 sql_pot.py
```

| משתנה | ברירת מחדל | תיאור |
|---|---|---|
| `HP_SQL_PORT` | `3306` | פורט האזנה |
| `HP_SQL_EVENTS` | `./sql_events.jsonl` | נתיב לוג האירועים |
| `HP_SQL_VERSION` | `8.0.36-0ubuntu0.24.04.1` | גרסת MySQL מזויפת (תואמת Ubuntu 24.04) |

טכניקות SQL ב-`ATTACK_KB`: `sql-login` (התחברות/brute-force), `sql-enum`
(אנומרציה), `sql-file-access` (INTO OUTFILE/LOAD_FILE — קריטי), `sql-udf-rce`
(RCE דרך UDF — קריטי). נבדק מקצה לקצה מול קליינט `mysql` אמיתי (MariaDB):
כל ארבע הטכניקות סווגו נכון, ו-`SHOW DATABASES` החזיר את רשימת המסדים המזויפת.

**פריסה** (על השרת המוקרב, לצד מלכודת הווב):
```bash
sudo HP_PROD_IP=72.62.150.169 ./deploy/add-sql-honeypot.sh
# מתקין sql-pot.service (3306) + hp-collector-sql.service (8082, מוגבל לפרודקשן),
# מדפיס טוקן. ואז בפרודקשן:
cd /opt/kali-gui && python3 sensor.py --add sql http://187.124.189.97:8082 <token>
```
כל מלכודת כותבת לקובץ **נפרד** עם קולקטור נפרד — שתי מלכודות שכותבות לאותו קובץ
היו משבשות שורות תחת עומס. החיישן מושך מכל המלכודות הרשומות.

### 🔑 מלכודת SSH (`ssh_pot.py`, פורט 22)

SSH הוא השירות הכי מותקף באינטרנט, והסיסמאות שהבוטים מנסים הן **מילון חי** —
הנתון הכי בעל-ערך ללמידה. המלכודת לוכדת כל שם-משתמש+סיסמה ו**תמיד דוחה. אין
shell, אין session, אפס סיכון** — רק קציר אישורים.

**למה זו המלכודת היחידה עם תלות:** אחרי לחיצת היד, SSH מצפין הכל ב-AES —
ול-stdlib של Python אין שום צופן סימטרי. לכן לכידת אישורים בלתי אפשרית ב-stdlib
טהור; חייבים לסיים את ההצפנה, וזה דורש ספריית קריפטו (`paramiko`). היא רצה **רק
על השרת המוקרב**; הפרודקשן (חיישן, `attack_kb`, שרת) נשאר stdlib טהור.

```bash
HP_SSH_PORT=22 HP_SSH_EVENTS=/var/log/honeypot/ssh.jsonl python3 ssh_pot.py
```

| משתנה | ברירת מחדל | תיאור |
|---|---|---|
| `HP_SSH_PORT` | `22` | פורט האזנה |
| `HP_SSH_EVENTS` | `./ssh_events.jsonl` | נתיב לוג האירועים |
| `HP_SSH_HOSTKEY` | `./ssh_host_rsa_key` | host key קבוע (fingerprint יציב) |
| `HP_SSH_BANNER` | `SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.5` | באנר מזויף |

טכניקה ב-`ATTACK_KB`: `ssh-bruteforce` (חייבת להיות **מעל** `cred-attack` — ה-blob
מכיל `user=... pass=...` שאחרת דפוס ה-login של הווב היה חוטף). נבדק מקצה לקצה מול
קליינט SSH אמיתי (paramiko): 6 זוגות אישורים נלכדו עם טביעת אצבע של הכלי, כולם
סווגו `ssh-bruteforce`.

**⚠️ פריסה — פורט 22 הוא ה-SSH האמיתי שלך:**
```bash
sudo HP_PROD_IP=72.62.150.169 ./deploy/add-ssh-honeypot.sh
```
הסקריפט מתקין `paramiko` (מעדיף `apt python3-paramiko`, נופל ל-venv; על השרת המוקרב בלבד), מתקין `ssh-pot.service` +
`hp-collector-ssh.service` (8083). **הוא לא נוגע ב-sshd שלך** — אם פורט 22 תפוס,
הוא מדפיס נוהל הגירה בטוח (הוסף פורט חדש → **אמת בטרמינל שני שאתה נכנס** → הסר 22
→ הפעל את המלכודת). לעולם אל תסגור את הסשן הראשון לפני שאימתת את החדש.

ואז בפרודקשן: `python3 sensor.py --add ssh http://187.124.189.97:8083 <token>`

### פריסה על השרת המוקרב

```bash
mkdir -p /opt/honeypot /var/log/honeypot
# העתק web_pot.py לשרת המוקרב (לא לפרודקשן!)

cat > /etc/systemd/system/web-pot.service <<'EOF'
[Unit]
Description=Web honeypot (low-interaction, deception)
After=network.target

[Service]
Type=simple
User=nobody
Environment=HP_PORT=8080
Environment=HP_EVENTS=/var/log/honeypot/web.jsonl
ExecStart=/usr/bin/python3 /opt/honeypot/web_pot.py
Restart=always
# hardening — this process is internet-exposed by design
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/honeypot
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload && systemctl enable --now web-pot
```

הצב מאחורי Caddy כדי לקבל HTTPS ו-IP אמיתי (המלכודת קוראת `X-Forwarded-For`):

```
web.dudaei.com {
    reverse_proxy 127.0.0.1:8080
}
```

---

## 🧪 בדיקה

```bash
# בדיקה עצמית של המסווג (20 מקרים, כולל התחמקות בקידוד URL)
python3 attack_kb.py
```

```bash
# מקצה לקצה: הרם מלכודת, תקוף אותה, וסווג את מה שנתפס
HP_PORT=9500 HP_EVENTS=/tmp/pot.jsonl python3 web_pot.py &
curl "http://127.0.0.1:9500/api/v1/users?id=1'%20UNION%20SELECT%20null--"
curl -A "sqlmap/1.7.2" http://127.0.0.1:9500/.env
python3 -c "
import json, attack_kb
for l in open('/tmp/pot.jsonl'):
    ev = json.loads(l)
    r = attack_kb.classify(ev['blob'])
    print(ev['path'][:44], '->', r['name'] if r else '(clean)')"
```

### 🐛 באג שנתפס — והוא מלמד

הבדיקה מקצה־לקצה חשפה שהמסווג סיווג **SQLi אמיתי כ"סריקה שגרתית, חומרה נמוכה"**.
הסיבה: התבנית `union\s+select` לא מתאימה ל-`UNION%20SELECT` — ו**תוקפים אמיתיים
מקודדים ב-URL כברירת מחדל** (sqlmap תמיד). בפרודקשן זה היה מתייג כל הזרקה אמיתית
כרעש בוטים משעמם ומפספס בדיוק את מה שבאנו לתפוס.

התיקון (`_views()`): סיווג מול הצורה הגולמית **וגם** המפוענחת, כולל פענוח כפול
(`%252e` → `%2e` → `.`) — טריק התחמקות סטנדרטי מ-WAF. הצורה הגולמית נשמרת כי
חלק מהתבניות מכוונות דווקא לצורה המקודדת. הבדיקה העצמית כוללת כעת מקרים מקודדים
כדי שזה לא יחזור.

### 🐛 באג שני — המלכודת כמעט הפכה לנשק נגד בעליה

`src_ip` מגיע מ-`X-Forwarded-For` — הדר ש**התוקף שולט בו לחלוטין**. הוא נשמר ב-DB
והוצג ב-`innerHTML` בדשבורד. שרשרת התקיפה:

```
X-Forwarded-For: <img src=x onerror=...>  →  DB  →  innerHTML  →  XSS אצל האדמין
```

תוקן בשתי שכבות: `sensor._safe_ip()` מצמצם לתווי כתובת בעת הקליטה (כך ש-payload
לא מגיע ל-DD מלכתחילה), והרינדור מסנן גם. ב-`hpPotEditor` הערכים מוצבים דרך
`.value` ולא באינטרפולציה, כי `escapeHtml` הקיים אינו מסנן מרכאות והן היו שוברות
מתוך התכונה.

**לקח:** מלכודת דבש היא צינור שמזרים קלט של תוקף היישר ללב המערכת שלך. כל שדה
משם הוא עוין עד שהוכח אחרת.

---

## 📋 מצב

| רכיב | מצב |
|---|---|
| `attack_kb.py` — 19 טכניקות + Sigma/Suricata | ✅ 30/30 בדיקות |
| `web_pot.py` — מלכודת ווב | ✅ נבדק מקצה לקצה |
| `sql_pot.py` — מלכודת MySQL (3306) | ✅ נבדק מול קליינט mysql אמיתי |
| `ssh_pot.py` — מלכודת SSH (22) | ✅ נבדק מול קליינט SSH אמיתי |
| `collector.py` — משיכה מוגנת בטוקן | ✅ 401/200 מאומת |
| `sensor.py` — משיכה → סיווג → DB | ✅ אידמפוטנטי (סמן) |
| מסך 🍯 מלכודות ב-UI (ניהול מ-kali.dudaei.com) | ✅ |
| הצלבה מול `DEFENSE_KB` + **לולאת למידה בתכנון** | ✅ |
| פריסת מלכודת ווב (187.124.189.97 / web.dudaei.com) | ✅ חי עם HTTPS |
| פריסת מלכודת SQL (פורט 3306) | 🚀 `deploy/add-sql-honeypot.sh` |
| פריסת מלכודת SSH (פורט 22) | 🚀 `deploy/add-ssh-honeypot.sh` |

## 🛡️ הרעלת נתונים — למה החיישן חייב להיזהר

התוקף **שולט בקלט של המלכודת מעצם הגדרתה**. אי אפשר למנוע הרעלה — רק להכיל:

- חתימות ממלכודת נשמרות עם `source=honeypot` בטבלה נפרדת — לעולם לא מעורבבות
  עם ממצאי התנוחה של הצוות האדום.
- **לעולם אין תיקון אוטומטי מנתוני מלכודת.** תוקף שיבין שיש לולאת תיקון יוכל
  להזין חתימה שתגרום להקשחה ש**נועלת אותך בחוץ** (הכניסה ל-VPS היא בסיסמת root
  ב-SSH, בלי מפתח). המלצה בלבד, באישור מפורש — כמו ה-fixer הקיים.
- הגבלת קצב וחיתוך: `MAX_BODY`, `MAX_FIELD` ותקרת אירועים לכל מקור, כדי
  שהצפה לא תסתיר תקיפה אמיתית אחת בין 10,000 מזויפות.
