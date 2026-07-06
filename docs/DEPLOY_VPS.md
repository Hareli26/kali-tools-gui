# פריסה מאובטחת על VPS עם התחברות Google

מדריך זה מפרט כיצד להריץ את **Kali Tools GUI** על שרת VPS (Ubuntu/Debian) עם גישה מבחוץ,
מאחורי **התחברות Google**, **אישור משתמשים** ו**לוג ביקורת** — בצורה מאובטחת.

---

## ⚠️ עקרון האבטחה
האפליקציה רצה כ‑root ומריצה כלים אמיתיים. לכן **היא לעולם לא נחשפת ישירות לרשת**.
היא מאזינה ל‑`127.0.0.1:8777` בלבד, ומעליה שכבות הגנה:

```
אינטרנט
   │  HTTPS (443)
   ▼
Caddy ──────────────► TLS אוטומטי (Let's Encrypt) + לוג גישות
   │  127.0.0.1:4180
   ▼
oauth2-proxy ───────► התחברות Google + רשימת מיילים מאושרים + לוג
   │  127.0.0.1:8777  (+ header X-Forwarded-Email)
   ▼
Kali Tools GUI ─────► רץ פרטית; רושם לוג ביקורת של מי הריץ מה
```

---

## דרישות מקדימות
- שרת VPS עם **Ubuntu 22.04+ / Debian 12+**, גישת root (SSH).
- **דומיין** שבבעלותך (למשל `kali.example.com`).
- חשבון Google (לזה שמגדיר את ה‑OAuth).

---

## שלב 1 — DNS
צור רשומת **A** אצל ספק הדומיין שלך שמפנה את הדומיין (או תת‑דומיין) ל‑**IP הציבורי של ה‑VPS**:
```
kali.example.com   A   <VPS_PUBLIC_IP>
```
המתן שההפצה תתעדכן (בדוק: `ping kali.example.com`).

---

## שלב 2 — הגדרת Google OAuth
1. היכנס ל‑**Google Cloud Console** → צור פרויקט חדש.
2. **APIs & Services → OAuth consent screen**:
   - סוג: **External**. מלא שם אפליקציה, מייל תמיכה.
   - תחת **Test users** הוסף את המייל שלך (או פרסם את האפליקציה).
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Web application**.
   - **Authorized redirect URIs**: `https://kali.example.com/oauth2/callback`
     (החלף בדומיין שלך — חייב להיות מדויק).
4. שמור את **Client ID** ו‑**Client Secret**.

---

## שלב 3 — הבאת הקוד לשרת
```bash
sudo apt update && sudo apt install -y git
sudo git clone https://github.com/Hareli26/kali-tools-gui.git /opt/kali-gui
cd /opt/kali-gui
```

## שלב 4 — הגדרות פריסה
```bash
cp deploy/deploy.env.example deploy/deploy.env
nano deploy/deploy.env
```
מלא: `DOMAIN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ADMIN_EMAIL`.

## שלב 5 — הרצת המתקין
```bash
sudo bash deploy/install-vps.sh
```
המתקין: מתקין כלים, פורס את האפליקציה, מתקין Caddy + oauth2-proxy, יוצר תעודת TLS,
מגדיר firewall (ufw) + fail2ban, ומפעיל את השירותים. בסיום — פתח `https://kali.example.com`.

---

## שלב 6 — אישור משתמשים (רשימת היתר)
אתה שולט מי נכנס. ערוך את קובץ ההיתר — מייל אחד בכל שורה:
```bash
sudo nano /opt/kali-gui/deploy/authenticated-emails.txt
sudo systemctl restart oauth2-proxy
```
משתמש שאינו ברשימה יקבל דחייה גם אם התחבר ל‑Google. הסרת שורה = שלילת גישה.

---

## לוג ביקורת — מי נכנס ומה עשה
| מה | היכן |
|----|------|
| מי הריץ איזה כלי/משימה | `/opt/kali-gui/audit.log` |
| מי התחבר / נדחה | `journalctl -u oauth2-proxy` |
| גישות HTTP | `/var/log/caddy/kali-gui-access.log` |

דוגמה מ‑`audit.log`:
```
2026-07-06 12:38:54  user=hareli26@gmail.com  action=run-tool   ping | ping -c 1 127.0.0.1
2026-07-06 12:41:02  user=someone@gmail.com   action=purple     בדיקת חדירות | example.com
```
בממשק עצמו, הכותרת מציגה את המשתמש המחובר, וכל פעילות ביומן נושאת את שם המריץ.

---

## ניהול השירותים
```bash
systemctl status  kali-gui oauth2-proxy caddy
systemctl restart kali-gui          # לאחר עדכון קוד (git pull)
journalctl -u kali-gui -n 50        # לוגים
```
עדכון גרסה:
```bash
cd /opt/kali-gui && sudo git pull && sudo systemctl restart kali-gui
```

---

## רשימת הקשחה (חובה)
- [ ] **SSH במפתחות בלבד** — כבה התחברות סיסמה (`PasswordAuthentication no`), והשבת root login.
- [ ] **ufw** פעיל — רק 22/80/443 פתוחים (המתקין עושה זאת).
- [ ] **fail2ban** פעיל (המתקין מתקין).
- [ ] עדכונים אוטומטיים: `sudo apt install unattended-upgrades`.
- [ ] הגבל את רשימת ההיתר למינימום ההכרחי.
- [ ] גיבוי של `authenticated-emails.txt`, `knowledge.json`, `reports/`.
- [ ] ⚠️ הרץ כלים אך ורק כנגד מטרות שיש לך הרשאה חוקית לבדוק. השרת הזה הוא כלי רב‑עוצמה — האחריות עליך.

---

## פתרון תקלות
| תקלה | פתרון |
|------|--------|
| התעודה לא נוצרת | ודא ש‑DNS מפנה נכון ושפורטים 80/443 פתוחים; `journalctl -u caddy` |
| נדחה אחרי התחברות Google | המייל לא ברשימת ההיתר, או redirect URI לא תואם |
| שגיאת redirect_uri_mismatch | ה‑URI ב‑Google חייב להיות בדיוק `https://<DOMAIN>/oauth2/callback` |
| האפליקציה לא עולה | `journalctl -u kali-gui -n 50` |
