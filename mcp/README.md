# שרת MCP ל‑Kali Tools GUI

שרת MCP שחושף את Kali Tools GUI ככלים ש‑**Claude** (או כל לקוח MCP) יכול להפעיל בשיחה:
להריץ כלים, לתכנן בדיקות, להריץ משימות ו‑Purple‑Team, ולקרוא דוחות, דשבורד וידע.

הוא **client דק** מעל ה‑REST API הקיים — לא מריץ כלים בעצמו אלא פונה ל‑`http://127.0.0.1:8777`.

## הכלים שנחשפים
| כלי MCP | מה הוא עושה |
|---------|-------------|
| `list_tools(category?)` | רשימת הכלים (שם, בינארי, קטגוריה, מותקן) |
| `tool_options(tool_id)` | השדות של כלי מסוים (מה להעביר ל‑run_tool) |
| `run_tool(tool_id, values)` | הרצת כלי בודד והחזרת הפלט |
| `plan(intent, target)` | תכנון בדיקה מכוונה בשפה חופשית (בלי להריץ) |
| `run_mission(intent, target)` | הרצת משימה מלאה → דוח |
| `run_purple(intent, target)` | הרצת Purple‑Team → איומים + הגנות + דוח |
| `dashboard()` | מצב חי: כלים, מודיעין, פעילות אחרונה |
| `knowledge()` | בסיס הידע הנצבר (חתימות ממצאים) |

## התקנה
```bash
cd /opt/kali-gui        # או התיקייה שלך
python3 -m venv .venv
.venv/bin/pip install -r mcp/requirements.txt
```

## הגדרה בלקוח

### Claude Code (CLI)
```bash
claude mcp add kali-tools-gui \
  --env KALIGUI_URL=http://127.0.0.1:8777 \
  -- /opt/kali-gui/.venv/bin/python /opt/kali-gui/mcp/kali_gui_mcp.py
```

### Claude Desktop
הוסף ל‑`claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "kali-tools-gui": {
      "command": "/opt/kali-gui/.venv/bin/python",
      "args": ["/opt/kali-gui/mcp/kali_gui_mcp.py"],
      "env": { "KALIGUI_URL": "http://127.0.0.1:8777" }
    }
  }
}
```

## חיבור לשרת מרוחק (VPS)
האפליקציה על ה‑VPS מאזינה ל‑`127.0.0.1` בלבד (מאחורי Google auth). לגישת MCP, פתח מנהרת SSH מהמחשב שלך והשאר את ה‑MCP מקומי:
```bash
ssh -L 8777:127.0.0.1:8777 root@<VPS_IP>
```
ואז `KALIGUI_URL=http://127.0.0.1:8777` (דרך המנהרה). כך ה‑MCP ניגש ישירות לאפליקציה בלי לעבור דרך oauth2‑proxy.

## דוגמאות שימוש (בתוך Claude)
- "השתמש ב‑kali‑tools‑gui: הרץ nmap על 192.168.1.10"
- "תכנן בדיקת חדירות ל‑example.com והצג לי את השלבים"
- "הרץ Purple‑Team על scanme.nmap.org ותן לי את הדוח"
- "מה מצב הדשבורד? אילו איומים הכי נפוצים?"

## אבטחה
- הרץ אך ורק כנגד מטרות מורשות.
- ה‑MCP יורש את אותה מדיניות — הוא רק שכבת נוחות מעל ה‑API המקומי.
