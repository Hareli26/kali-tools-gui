#!/usr/bin/env python3
"""
Obsidian vault export for Kali Tools GUI.

Turns the stored reports + learning knowledge into an Obsidian-friendly vault:
  vault/Reports/<date> <target> <id>.md   — each report, with YAML frontmatter
  vault/Threats/<threat>.md                — one note per known threat signature
  vault/Security Dashboard (MOC).md        — Map of Content linking everything

Reports are already Markdown, so notes are portable. Wikilinks connect reports
to the threats they mention, and tags allow Obsidian's graph/search to work.
Sync the vault folder to your machine (git / Obsidian Sync / rsync) and open it.
"""
import os
import re

_ILLEGAL = re.compile(r'[\\/:*?"<>|#\^\[\]]')


def _slug(s):
    s = _ILLEGAL.sub(" ", (s or "")).strip()
    s = re.sub(r"\s+", " ", s)
    return (s or "note")[:90]


def _report_note_name(m):
    date = (m.get("when") or "").split(" ")[0]
    return _slug(f"{date} {m.get('target','')} {(m.get('id') or '')[:6]}")


def export(vault_dir, reports, kb, remediation_lookup=None):
    reports_dir = os.path.join(vault_dir, "Reports")
    threats_dir = os.path.join(vault_dir, "Threats")
    os.makedirs(reports_dir, exist_ok=True)
    os.makedirs(threats_dir, exist_ok=True)

    sigs = kb.get("signatures", {})
    # map threat display-name -> note slug (for wikilinks from reports)
    name_slug = {v.get("name", sig): _slug(v.get("name", sig)) for sig, v in sigs.items()}

    # --- report notes ---
    for r in reports:
        m = r.get("meta", {})
        body = r.get("report", "") or ""
        # link any threat names that appear in the body to their notes
        related = [nm for nm in name_slug if nm and nm in body]
        fm = ("---\n"
              f"type: {m.get('kind','report')}\n"
              f"target: {m.get('target','')}\n"
              f"date: {m.get('when','')}\n"
              f"id: {m.get('id','')}\n"
              f"tags: [security, kali-tools-gui, {m.get('kind','report')}]\n"
              "---\n\n")
        rel = ""
        if related:
            rel = "\n\n## איומים קשורים\n" + "\n".join(f"- [[{name_slug[nm]}]]" for nm in related)
        content = fm + body + rel + "\n"
        with open(os.path.join(reports_dir, _report_note_name(m) + ".md"), "w", encoding="utf-8") as f:
            f.write(content)

    # --- threat notes ---
    for sig, v in sigs.items():
        rem = (remediation_lookup(sig) if remediation_lookup else None) or {}
        lines = ["---",
                 "type: threat",
                 f"signature: {sig}",
                 f"severity: {v.get('severity','')}",
                 f"count: {v.get('count',0)}",
                 f"tags: [security, threat, severity/{v.get('severity','')}]",
                 "---", "",
                 f"# {v.get('name', sig)}", "",
                 f"- **חומרה:** {v.get('severity','')}",
                 f"- **נצפה:** {v.get('count',0)} פעמים",
                 f"- **ראשון:** {v.get('first_seen','')} · **אחרון:** {v.get('last_seen','')}"]
        if rem.get("title"):
            lines.append(f"- **תיקון אפשרי:** {rem['title']} ({rem.get('risk','')})")
        lines.append("\n> [[Security Dashboard (MOC)]]")
        with open(os.path.join(threats_dir, _slug(v.get("name", sig)) + ".md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # --- Map of Content ---
    moc = ["---", "type: moc", "tags: [security, moc]", "---", "",
           "# 🛡️ Security Dashboard (MOC)", "",
           f"מפת תוכן שנוצרה מ‑Kali Tools GUI — **{len(reports)}** דוחות · **{len(sigs)}** סוגי איומים.", "",
           "## 📄 דוחות"]
    for r in reports:
        m = r.get("meta", {})
        moc.append(f"- [[{_report_note_name(m)}]] — `{m.get('target','')}` · {m.get('when','')}")
    moc.append("")
    moc.append("## 🎯 איומים (לפי שכיחות)")
    for sig, v in sorted(sigs.items(), key=lambda kv: -kv[1].get("count", 0)):
        moc.append(f"- [[{_slug(v.get('name', sig))}]] — {v.get('count',0)}× · {v.get('severity','')}")
    with open(os.path.join(vault_dir, "Security Dashboard (MOC).md"), "w", encoding="utf-8") as f:
        f.write("\n".join(moc) + "\n")

    return {"vault": vault_dir, "reports": len(reports), "threats": len(sigs)}
