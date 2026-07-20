#!/usr/bin/env python3
"""Which tools does each playbook need, and which are missing on this host?
Run from /opt/kali-gui:  python3 check_playbooks.py"""
import io, json, os, shutil, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents

# same detection the app uses: which() over the standard PATH + ~/.local/bin
PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
for extra in (os.path.expanduser("~/.local/bin"), "/root/.local/bin"):
    if os.path.isdir(extra):
        PATH += ":" + extra

TOOLS = {t["id"]: t for t in json.load(open("tools.json", encoding="utf-8"))["tools"]}
def installed(tid):
    t = TOOLS.get(tid)
    return bool(t) and shutil.which(t["binary"], path=PATH) is not None

sample = agents.target_variants("example.com")
missing_pkgs, missing_bins = {}, set()
print(f"{'PLAYBOOK':<34} {'מותקן':>6}  חסר")
print("-" * 78)
for pb in agents.PLAYBOOKS:
    try:
        tids = list(dict.fromkeys(s["tool_id"] for s in pb["build"](sample)))
    except Exception:
        tids = []
    miss = [t for t in tids if not installed(t)]
    for t in miss:
        tool = TOOLS.get(t, {})
        missing_bins.add(tool.get("binary", t))
        if tool.get("package"):
            missing_pkgs[tool["package"]] = True
    ok = len(tids) - len(miss)
    flag = "✅" if not miss else "⚠️ "
    miss_names = ", ".join(TOOLS.get(t, {}).get("binary", t) for t in miss)
    print(f"{flag} {pb['name'][:30]:<31} {ok}/{len(tids):<4} {miss_names}")

print("\n" + "=" * 78)
if missing_pkgs:
    print("כלים חסרים (ייחודי):", ", ".join(sorted(missing_bins)))
    print("\n📦 פקודת התקנה לכל החסרים:")
    print("   sudo apt install -y " + " ".join(sorted(missing_pkgs)))
else:
    print("🎉 כל הכלים לכל ה-playbooks מותקנים!")
