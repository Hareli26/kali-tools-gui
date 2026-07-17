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


# ----------------------------------------------------- 🍯 deception export ----
def _flag(cc):
    if not cc or len(cc) != 2 or not cc.isalpha():
        return "🏴"
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord("A")) for c in cc)


_CRED_RE = re.compile(r"\buser=(\S+)(?:.*?\b(?:pass|auth)=(\S+))?", re.S)


def export_honeypot(vault_dir, hp, correlation, events, attack_lookup=None,
                    country_detail=None):
    """Write the honeypot intel into the vault as Attack notes wikilinked to the
    posture Threat notes they cross — so Obsidian's graph shows, visually, which
    real-world attacks target weaknesses we actually have. Plus per-Country notes
    and a Deception MOC. Fails soft: with no honeypot data it writes nothing."""
    hp = hp or {}
    sigs = hp.get("signatures", [])
    if not sigs and not events:
        return {"attacks": 0, "countries": 0}

    attacks_dir = os.path.join(vault_dir, "Attacks")
    os.makedirs(attacks_dir, exist_ok=True)

    # attack technique -> the posture weaknesses it exploits (from the crossing)
    cross = {}
    for c in (correlation or []):
        cross.setdefault(c["attack"], []).append(c["weakness_name"])
    # countries whose favourite this technique is (from top_countries)
    fav_by_tech = {}
    for c in hp.get("top_countries", []):
        if c.get("top_technique"):
            fav_by_tech.setdefault(c["top_technique"], []).append((c.get("cc", ""), c.get("country", "")))

    # --- one note per observed attack technique ---
    for s in sigs:
        sig = s["sig"]
        info = (attack_lookup(sig) if attack_lookup else None) or {}
        lines = ["---", "type: attack", f"technique: {sig}",
                 f"severity: {s.get('severity','')}", f"count: {s.get('count',0)}",
                 f"tags: [security, deception, attack, severity/{s.get('severity','')}]",
                 "---", "", f"# ⚔️ {s.get('name', sig)}", "",
                 f"- **חומרה:** {s.get('severity','')}",
                 f"- **נצפה במלכודות:** {s.get('count',0)} פעמים"]
        if info.get("mitre"):
            lines.append(f"- **MITRE ATT&CK:** {info['mitre']}")
        if info.get("technique"):
            lines += ["", "## מה התוקף מנסה", info["technique"]]
        if info.get("defenses"):
            lines += ["", "## 🛡️ הגנות"] + [f"- {d}" for d in info["defenses"]]
        weak = list(dict.fromkeys(cross.get(sig, [])))
        if weak:
            lines += ["", "## 🔥 אנחנו חשופים לזה", "*תוקפים מנסים את זה, והסריקה שלנו מצאה אצלנו:*"]
            lines += [f"- [[{_slug(w)}]]" for w in weak]
        countries = fav_by_tech.get(sig, [])
        if countries:
            lines += ["", "## 🌍 מדינות שזו הטכניקה המועדפת שלהן"]
            lines += [f"- {_flag(cc)} {co}" for cc, co in countries]
        lines.append("\n> [[🍯 Deception (MOC)]]")
        with open(os.path.join(attacks_dir, _slug(s.get("name", sig)) + ".md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # --- Deception MOC ---
    m = ["---", "type: moc", "tags: [security, deception, moc]", "---", "",
         "# 🍯 Deception — מודיעין ממלכודות", "",
         f"נקלטו **{hp.get('events',0)}** תקיפות אמיתיות מ‑**{hp.get('attackers',0)}** "
         f"כתובות ({hp.get('events_24h',0)} ב‑24 השעות האחרונות)."]

    if correlation:
        m += ["", "## 🔥 איומים מאומתים — תוקפים מנסים, ואנחנו חשופים"]
        for c in correlation:
            m.append(f"- [[{_slug(c['attack_name'])}]] × {c['attack_count']} "
                     f"→ אצלנו: [[{_slug(c['weakness_name'])}]]")

    # --- one note per attacking country (techniques + attacker IPs) ---
    if country_detail:
        countries_dir = os.path.join(vault_dir, "Countries")
        os.makedirs(countries_dir, exist_ok=True)
        for cd in country_detail:
            cc, country = cd.get("cc", ""), cd.get("country", "?")
            cl = ["---", "type: country", f"country: {country}", f"cc: {cc}",
                  f"events: {cd.get('events',0)}",
                  "tags: [security, deception, country]", "---", "",
                  f"# {_flag(cc)} {country}", "",
                  f"- **תקיפות:** {cd.get('events',0)}",
                  f"- **תוקפים ייחודיים:** {len(cd.get('attackers',[]))}"]
            if cd.get("techniques"):
                cl += ["", "## 🎯 טכניקות מהמדינה הזו"]
                cl += [f"- [[{_slug(_tech_name(t, attack_lookup))}]] — {n}×"
                       for t, n in cd["techniques"] if t]
            if cd.get("attackers"):
                cl += ["", "## 🌐 כתובות תוקפות"]
                cl += [f"- `{ip}` — {n} בקשות" for ip, n in cd["attackers"][:30]]
            cl.append("\n> [[🍯 Deception (MOC)]]")
            with open(os.path.join(countries_dir, _slug(country) + ".md"), "w", encoding="utf-8") as f:
                f.write("\n".join(cl) + "\n")

    if hp.get("top_countries"):
        m += ["", "## 🌍 מדינות תוקפות מובילות"]
        for c in hp["top_countries"]:
            fav = f" · מועדף: [[{_slug(_tech_name(c['top_technique'], attack_lookup))}]]" if c.get("top_technique") else ""
            m.append(f"- {_flag(c.get('cc',''))} [[{_slug(c.get('country','?'))}]] — {c['events']} תקיפות · {c['attackers']} כתובות{fav}")

    if sigs:
        m += ["", "## 🎯 טכניקות שנצפו (לפי שכיחות)"]
        for s in sorted(sigs, key=lambda x: -x.get("count", 0)):
            m.append(f"- [[{_slug(s.get('name', s['sig']))}]] — {s.get('count',0)}× · {s.get('severity','')}")

    creds = []
    for e in (events or []):
        mm = _CRED_RE.search(e.get("blob", "") or "")
        if mm and mm.group(2):
            creds.append((e.get("src_ip", ""), e.get("country", ""), mm.group(1), mm.group(2)))
    if creds:
        m += ["", "## 🔑 אישורים שנתפסו (דגימה)", "", "| מקור | משתמש | סיסמה |", "|---|---|---|"]
        for ip, co, u, p in creds[:25]:
            flag = _flag_from_country_hint(co)
            m.append(f"| {flag} `{ip}` | `{u}` | `{p}` |")

    if hp.get("top_attackers"):
        m += ["", "## 🌐 תוקפים מובילים"]
        for a in hp["top_attackers"]:
            m.append(f"- {_flag(a.get('cc',''))} `{a['src_ip']}` — {a['n']} בקשות · {a.get('country','')}")

    m.append("\n> [[Security Dashboard (MOC)]]")
    with open(os.path.join(vault_dir, "🍯 Deception (MOC).md"), "w", encoding="utf-8") as f:
        f.write("\n".join(m) + "\n")

    return {"attacks": len(sigs), "countries": len(country_detail or hp.get("top_countries", []))}


def _tech_name(sig, attack_lookup):
    info = (attack_lookup(sig) if attack_lookup else None) or {}
    return info.get("name", sig)


def _flag_from_country_hint(country):
    # top_attackers/events carry cc separately; here we only have a country name
    # sample, so just show a generic marker — the flag lives on the attacker rows.
    return "🌍" if country and country != "Local" else "🏴"
