"use strict";

/* ------------------------------------------------------------------ state */
let CATALOG = null;
let CATS = {};
let CURRENT_TOOL = null;
let CURRENT_JOB = null;
let POLL_TIMER = null;
let activeCat = "all";
let searchTerm = "";
let pendingInstall = null;

/* --------------------------------------------------------------- helpers */
const $ = (id) => document.getElementById(id);
const el = (tag, cls, txt) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
};

function showScreen(name) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  $("screen-" + name).classList.add("active");
  const isDash = name === "dashboard";
  const isAI = name.startsWith("ai-") || name === "purple";
  const isTools = !isDash && !isAI;
  const mt = $("modeTools"), ma = $("modeAI"), md = $("modeDash");
  if (mt) mt.classList.toggle("active", isTools);
  if (ma) ma.classList.toggle("active", isAI);
  if (md) md.classList.toggle("active", isDash);
  if (isDash) loadDashboard();
  window.scrollTo(0, 0);
}

/* --------------------------------------------------------------- loading */
async function loadCatalog() {
  const res = await fetch("/api/tools");
  CATALOG = await res.json();
  CATS = {};
  (CATALOG.categories || []).forEach(c => CATS[c.id] = c);
  renderCatFilters();
  renderGrid();
  const total = CATALOG.tools.length;
  const installed = CATALOG.tools.filter(t => t.installed).length;
  $("statLine").textContent = `${installed}/${total} כלים מותקנים`;
}

/* ------------------------------------------------------- screen 1: picker */
function renderCatFilters() {
  const box = $("catFilters");
  box.innerHTML = "";
  const mk = (id, label) => {
    const chip = el("div", "cat-chip" + (activeCat === id ? " active" : ""), label);
    chip.onclick = () => { activeCat = id; renderCatFilters(); renderGrid(); };
    box.appendChild(chip);
  };
  mk("all", "הכל");
  (CATALOG.categories || []).forEach(c => mk(c.id, `${c.icon} ${c.name}`));
}

function renderGrid() {
  const grid = $("toolGrid");
  grid.innerHTML = "";
  const term = searchTerm.toLowerCase();
  const list = CATALOG.tools.filter(t => {
    if (activeCat !== "all" && t.category !== activeCat) return false;
    if (term && !(`${t.name} ${t.binary} ${t.desc}`.toLowerCase().includes(term))) return false;
    return true;
  });
  $("pickerEmpty").classList.toggle("hidden", list.length > 0);
  list.forEach(t => {
    const cat = CATS[t.category] || {};
    const card = el("div", "tool-card" + (t.installed ? "" : " disabled"));
    const badge = el("span", "badge " + (t.installed ? "on" : "off"), t.installed ? "מותקן" : "לא מותקן");
    card.appendChild(badge);
    const top = el("div", "tc-top");
    top.appendChild(el("span", "tc-icon", cat.icon || "🛠️"));
    const nameWrap = el("div");
    nameWrap.appendChild(el("div", "tc-name", t.name));
    nameWrap.appendChild(el("div", "tc-bin", t.binary));
    top.appendChild(nameWrap);
    card.appendChild(top);
    card.appendChild(el("div", "tc-desc", t.desc));
    card.onclick = () => t.installed ? openForm(t) : askInstall(t);
    grid.appendChild(card);
  });
}

/* --------------------------------------------------------- screen 2: form */
function openForm(tool) {
  CURRENT_TOOL = tool;
  const cat = CATS[tool.category] || {};
  $("formIcon").textContent = cat.icon || "🛠️";
  $("formTitle").textContent = tool.name;
  $("formDesc").textContent = tool.desc;
  $("formBinary").textContent = tool.binary;
  $("formError").classList.add("hidden");

  const form = $("toolForm");
  form.innerHTML = "";
  (tool.options || []).forEach(opt => form.appendChild(renderField(opt)));

  // free-form extra args
  const extra = renderField({ id: "_extra", label: "ארגומנטים נוספים (מתקדם)", type: "text",
    help: "יתווספו לפקודה כפי שהם", placeholder: "--flag value" });
  form.appendChild(extra);

  // examples
  const exBox = $("formExamples");
  exBox.innerHTML = "";
  if (tool.examples && tool.examples.length) {
    exBox.appendChild(el("div", null, "דוגמאות:"));
    tool.examples.forEach(ex => exBox.appendChild(el("code", null, ex)));
  }

  form.oninput = updatePreview;
  form.onchange = updatePreview;
  updatePreview();
  showScreen("form");
}

function renderField(opt) {
  const type = opt.type || "text";
  const wrap = el("div", "field" + (opt.primary ? " primary" : "") + (type === "bool" ? " bool" : ""));
  const labelTxt = opt.label + (opt.flag ? "  (" + opt.flag + ")" : "");

  if (type === "bool") {
    const cb = el("input");
    cb.type = "checkbox"; cb.id = "f_" + opt.id; cb.dataset.oid = opt.id;
    if (opt.default === true) cb.checked = true;
    const lab = el("label", null, labelTxt); lab.htmlFor = cb.id;
    wrap.appendChild(cb); wrap.appendChild(lab);
    return wrap;
  }

  const lab = el("label");
  lab.appendChild(document.createTextNode(labelTxt + " "));
  if (opt.required) { const r = el("span", "req", "*"); lab.appendChild(r); }
  wrap.appendChild(lab);

  let input;
  if (type === "select") {
    input = el("select");
    (opt.choices || []).forEach(ch => {
      const o = el("option", null, ch.t); o.value = ch.v;
      input.appendChild(o);
    });
    if (opt.default != null) input.value = opt.default;
  } else {
    input = el("input");
    input.type = type === "number" ? "number" : "text";
    if (opt.placeholder) input.placeholder = opt.placeholder;
    if (opt.default != null && opt.default !== true) input.value = opt.default;
  }
  input.id = "f_" + opt.id; input.dataset.oid = opt.id;
  wrap.appendChild(input);
  if (opt.help) wrap.appendChild(el("div", "help", opt.help));
  return wrap;
}

function collectValues() {
  const values = {};
  $("toolForm").querySelectorAll("[data-oid]").forEach(inp => {
    const oid = inp.dataset.oid;
    if (inp.type === "checkbox") values[oid] = inp.checked;
    else values[oid] = inp.value;
  });
  return values;
}

/* build the command preview (mirrors server-side build_argv) */
function buildArgv(tool, values) {
  const argv = [tool.binary];
  let positional = null;
  (tool.options || []).forEach(opt => {
    const flag = opt.flag || "";
    const type = opt.type || "text";
    const raw = values[opt.id];
    if (type === "bool") { if (raw === true) { if (flag) argv.push(flag); } return; }
    const val = (raw == null ? "" : String(raw)).trim();
    if (val === "") return;
    if (flag === "") {
      if (opt.primary) positional = val;
      else argv.push(val);
    } else if (opt.eq) {
      argv.push(flag + "=" + val);
    } else {
      argv.push(flag); argv.push(val);
    }
  });
  const extra = (values._extra || "").trim();
  if (extra) extra.split(/\s+/).forEach(a => argv.push(a));
  if (positional != null) argv.push(positional);
  return argv;
}

function shquote(a) {
  return /^[a-zA-Z0-9_\-.,:\/=@%+]+$/.test(a) ? a : "'" + a.replace(/'/g, "'\\''") + "'";
}

function updatePreview() {
  const argv = buildArgv(CURRENT_TOOL, collectValues());
  $("cmdPreview").textContent = argv.map(shquote).join(" ");
}

/* ------------------------------------------------------- run + screen 3 */
async function runTool() {
  const values = collectValues();
  const errBox = $("formError");
  errBox.classList.add("hidden");
  $("runBtn").disabled = true;
  try {
    const res = await fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool_id: CURRENT_TOOL.id, values })
    });
    const data = await res.json();
    if (!res.ok) {
      errBox.textContent = data.error || "שגיאה בהרצה";
      errBox.classList.remove("hidden");
      return;
    }
    CURRENT_JOB = data.job_id;
    openResults(CURRENT_TOOL.name, data.command);
    pollJob();
  } catch (e) {
    errBox.textContent = "שגיאת רשת: " + e;
    errBox.classList.remove("hidden");
  } finally {
    $("runBtn").disabled = false;
  }
}

function openResults(title, command) {
  $("resultsTitle").textContent = title;
  $("resultsCmd").textContent = command;
  $("output").textContent = "מריץ...\n";
  setStatus("running");
  $("stopBtn").classList.remove("hidden");
  showScreen("results");
}

function setStatus(status) {
  const map = { running: "רץ ▶", done: "הושלם ✓", error: "שגיאה ✕", stopped: "נעצר ⏹", starting: "מתחיל..." };
  const b = $("resultsStatus");
  b.className = "status-badge " + status;
  b.textContent = map[status] || status;
}

function stripAnsi(s) {
  // remove ANSI/VT100 escape sequences so raw color codes don't clutter output
  return s.replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, "").replace(/\x1b\][^\x07]*\x07/g, "");
}

async function pollJob() {
  clearTimeout(POLL_TIMER);
  if (!CURRENT_JOB) return;
  try {
    const res = await fetch("/api/job/" + CURRENT_JOB);
    const data = await res.json();
    if (data.output != null) {
      const out = $("output");
      const atBottom = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
      out.textContent = stripAnsi(data.output) || "(אין פלט עדיין)";
      if (atBottom) out.scrollTop = out.scrollHeight;
    }
    setStatus(data.status);
    const running = data.status === "running" || data.status === "starting";
    $("stopBtn").classList.toggle("hidden", !running);
    if (running) POLL_TIMER = setTimeout(pollJob, 900);
  } catch (e) {
    setStatus("error");
    $("output").textContent += "\n[שגיאת פולינג] " + e;
  }
}

async function stopJob() {
  if (!CURRENT_JOB) return;
  await fetch("/api/job/" + CURRENT_JOB + "/stop", { method: "POST" });
  pollJob();
}

/* -------------------------------------------------------------- install */
function askInstall(tool) {
  pendingInstall = tool;
  $("installMsg").textContent = `הכלי "${tool.name}" (${tool.binary}) אינו מותקן. להתקין את החבילה "${tool.package}"?`;
  $("sudoPass").value = "";
  $("installOut").classList.add("hidden");
  $("installOut").textContent = "";
  $("installModal").classList.remove("hidden");
  setTimeout(() => $("sudoPass").focus(), 50);
}

async function doInstall() {
  if (!pendingInstall) return;
  const pass = $("sudoPass").value;
  const out = $("installOut");
  out.classList.remove("hidden");
  out.textContent = "מתקין... זה עשוי לקחת דקה.\n";
  $("installGo").disabled = true;
  try {
    const res = await fetch("/api/install", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ package: pendingInstall.package, password: pass })
    });
    const data = await res.json();
    if (!res.ok) { out.textContent = data.error || "שגיאה"; $("installGo").disabled = false; return; }
    const jid = data.job_id;
    const poll = async () => {
      const r = await fetch("/api/job/" + jid);
      const d = await r.json();
      out.textContent = d.output || "מתקין...";
      out.scrollTop = out.scrollHeight;
      if (d.status === "running" || d.status === "starting") { setTimeout(poll, 1000); }
      else {
        $("installGo").disabled = false;
        if (d.status === "done") {
          out.textContent += "\n\n✓ ההתקנה הושלמה. מרענן רשימה...";
          setTimeout(async () => { $("installModal").classList.add("hidden"); await loadCatalog(); }, 1200);
        } else {
          out.textContent += "\n\n✕ ההתקנה נכשלה (בדוק סיסמה/הרשאות/חיבור).";
        }
      }
    };
    poll();
  } catch (e) {
    out.textContent = "שגיאת רשת: " + e; $("installGo").disabled = false;
  }
}

/* ------------------------------------------------------------- wiring */
function download() {
  const blob = new Blob([$("output").textContent], { type: "text/plain" });
  const a = el("a"); a.href = URL.createObjectURL(blob);
  a.download = (CURRENT_TOOL ? CURRENT_TOOL.binary : "output") + "_result.txt";
  a.click();
}

/* ==================================================================
   AI ASSISTANT  (Planner -> Executor -> Verifier -> Reporter)
   ================================================================== */
let PLAN = null;
let MISSION_ID = null;
let MISSION_TIMER = null;
let REPORT_MD = "";

const AI_EXAMPLES = [
  "בדיקת DNS מקיפה", "בדיקת חדירות לאתר", "סריקת פורטים ושירותים",
  "אנומרציית SMB / Windows", "גילוי תת-דומיינים", "בדיקת SSL/TLS", "איסוף מודיעין OSINT",
];

function renderAIExamples() {
  const box = $("aiExamples");
  if (!box) return;
  box.innerHTML = "";
  AI_EXAMPLES.forEach(ex => {
    const c = el("div", "ai-chip", ex);
    c.onclick = () => { $("aiIntent").value = ex; };
    box.appendChild(c);
  });
}

async function makePlan() {
  const intent = $("aiIntent").value.trim();
  const target = $("aiTarget").value.trim();
  const err = $("aiPromptErr");
  err.classList.add("hidden");
  if (!intent || !target) {
    err.textContent = "יש להזין גם כוונה וגם מטרה."; err.classList.remove("hidden"); return;
  }
  $("planBtn").disabled = true;
  $("planBtn").textContent = "🧠 מתכנן...";
  try {
    const res = await fetch("/api/plan", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent, target })
    });
    const data = await res.json();
    if (!res.ok) { err.textContent = data.error || "שגיאה"; err.classList.remove("hidden"); return; }
    PLAN = data;
    renderPlan(data);
    showScreen("ai-plan");
  } catch (e) {
    err.textContent = "שגיאת רשת: " + e; err.classList.remove("hidden");
  } finally {
    $("planBtn").disabled = false;
    $("planBtn").textContent = "🧠 צור תוכנית";
  }
}

function renderPlan(data) {
  $("planMeta").innerHTML =
    `<span class="pill">מנוע: ${data.engine === "llm" ? "AI" : "חוקים"}</span>` +
    `<span class="pill">מטרה: ${escapeHtml(data.target)}</span>` +
    (data.playbooks || []).map(p => `<span class="pill">${escapeHtml(p)}</span>`).join("");
  const box = $("planSteps");
  box.innerHTML = "";
  data.steps.forEach((s, i) => {
    const row = el("div", "plan-step");
    const cb = el("input"); cb.type = "checkbox"; cb.checked = true; cb.dataset.idx = i;
    cb.onchange = () => { row.classList.toggle("excluded", !cb.checked); updatePlanCount(); };
    const body = el("div", "plan-step-body");
    const title = el("div", "plan-step-title");
    title.appendChild(el("span", null, `${i + 1}. ${s.tool_name}`));
    title.appendChild(el("span", "mini-badge pb", s.playbook || ""));
    if (s.needs_root) title.appendChild(el("span", "mini-badge root", "root"));
    if (s.installed === false) title.appendChild(el("span", "badge off", "לא מותקן"));
    body.appendChild(title);
    body.appendChild(el("div", "plan-step-why", s.why || ""));
    body.appendChild(el("div", "plan-step-cmd", s.command || ""));
    if (s.suggestion) body.appendChild(el("div", "plan-step-sugg", "💡 " + s.suggestion));
    row.appendChild(cb); row.appendChild(body);
    box.appendChild(row);
  });
  updatePlanCount();
}

function updatePlanCount() {
  const n = document.querySelectorAll("#planSteps input[type=checkbox]:checked").length;
  $("planCount").textContent = n;
  $("missionBtn").disabled = n === 0;
}

async function startMission() {
  if (!PLAN) return;
  const included = [];
  document.querySelectorAll("#planSteps input[type=checkbox]").forEach(cb => {
    if (cb.checked) included.push(PLAN.steps[parseInt(cb.dataset.idx, 10)]);
  });
  if (!included.length) return;
  $("missionBtn").disabled = true;
  try {
    const res = await fetch("/api/mission", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent: PLAN.intent, target: PLAN.target, steps: included })
    });
    const data = await res.json();
    if (!res.ok) { alert(data.error || "שגיאה"); return; }
    MISSION_ID = data.mission_id;
    $("missionMeta").innerHTML =
      `<span class="pill">${escapeHtml(PLAN.intent)}</span><span class="pill">${escapeHtml(PLAN.target)}</span>`;
    $("viewReportBtn").classList.add("hidden");
    $("missionStopBtn").classList.remove("hidden");
    showScreen("ai-mission");
    pollMission();
  } finally {
    $("missionBtn").disabled = false;
  }
}

const V_LABEL = { ok: "תקין", ok_findings: "ממצאים", warn: "אזהרה", fail: "נכשל", stopped: "נעצר" };
const S_ICON = { pending: "⏳", running: "🔄", done: "•", skipped: "⤵️", error: "❌" };

async function pollMission() {
  clearTimeout(MISSION_TIMER);
  if (!MISSION_ID) return;
  try {
    const res = await fetch("/api/mission/" + MISSION_ID);
    const m = await res.json();
    renderMission(m);
    if (m.status === "running") {
      MISSION_TIMER = setTimeout(pollMission, 1000);
    } else {
      $("missionStatus").className = "status-badge " + (m.status === "stopped" ? "stopped" : "done");
      $("missionStatus").textContent = m.status === "stopped" ? "נעצר" : "הושלם";
      $("missionStopBtn").classList.add("hidden");
      if (m.report) {
        REPORT_MD = m.report;
        $("viewReportBtn").classList.remove("hidden");
      }
    }
  } catch (e) {
    MISSION_TIMER = setTimeout(pollMission, 1500);
  }
}

function renderMission(m) {
  const box = $("missionSteps");
  box.innerHTML = "";
  m.steps.forEach((s, i) => {
    const wrap = el("div", "mstep" + (i === m.current && m.status === "running" ? " active" : ""));
    const head = el("div", "mstep-head");
    let ico = S_ICON[s.status] || "•";
    let vcls = "v-pending", vlabel = "ממתין";
    if (s.status === "running") { ico = "🔄"; vcls = "v-running"; vlabel = "רץ"; }
    if (s.verdict) {
      const v = s.verdict.verdict;
      vcls = "v-" + v; vlabel = s.verdict.label || V_LABEL[v] || v;
      ico = { ok: "✅", ok_findings: "🔎", warn: "⚠️", fail: "❌", stopped: "⏹️" }[v] || "•";
    }
    head.appendChild(el("span", "mstep-ico", ico));
    const info = el("div", "mstep-info");
    info.appendChild(el("div", "mstep-title", `${i + 1}. ${s.tool_name}`));
    info.appendChild(el("div", "mstep-why", s.why || ""));
    head.appendChild(info);
    head.appendChild(el("span", "mstep-verdict " + vcls, vlabel));
    wrap.appendChild(head);

    // findings (if any)
    if (s.verdict && s.verdict.findings && s.verdict.findings.length) {
      const f = el("div", "mstep-findings");
      f.appendChild(el("div", null, "ממצאים:"));
      s.verdict.findings.slice(0, 8).forEach(x => f.appendChild(el("code", null, x)));
      wrap.appendChild(f);
    }
    // live output for the active step
    if (i === m.current && s.output) {
      const pre = el("pre", "mstep-out", stripAnsi(s.output));
      wrap.appendChild(pre);
      head.onclick = () => pre.classList.toggle("hidden");
    } else if (s.output) {
      const pre = el("pre", "mstep-out hidden", stripAnsi(s.output));
      wrap.appendChild(pre);
      head.style.cursor = "pointer";
      head.onclick = () => pre.classList.toggle("hidden");
    }
    box.appendChild(wrap);
  });
}

async function stopMission() {
  if (!MISSION_ID) return;
  await fetch("/api/mission/" + MISSION_ID + "/stop", { method: "POST" });
  pollMission();
}

/* ============================ DASHBOARD (מרכז בקרה) ======================== */
let DASH_TIMER = null;

function relTime(ts) {
  if (!ts) return "";
  const diff = Math.max(0, Date.now() / 1000 - ts);
  if (diff < 60) return "הרגע";
  if (diff < 3600) return "לפני " + Math.floor(diff / 60) + " ד׳";
  if (diff < 86400) return "לפני " + Math.floor(diff / 3600) + " ש׳";
  return "לפני " + Math.floor(diff / 86400) + " ימים";
}

async function loadDashboard() {
  clearTimeout(DASH_TIMER);
  try {
    const d = await (await fetch("/api/dashboard")).json();
    renderDashboard(d);
  } catch (e) { /* ignore transient */ }
  // keep refreshing only while the dashboard is visible
  if ($("screen-dashboard").classList.contains("active")) {
    DASH_TIMER = setTimeout(loadDashboard, 3000);
  }
}

function renderDashboard(d) {
  const live = $("dashLive");
  live.className = "live-pill" + (d.live ? " on" : "");
  live.textContent = d.live ? "● פעיל כעת" : "● לא פעיל";

  // agents
  const ag = $("dashAgents");
  ag.innerHTML = "";
  d.agents.forEach(a => {
    const card = el("div", "agent-card " + a.status);
    const top = el("div", "agent-top");
    top.appendChild(el("span", "agent-ico", a.icon));
    const info = el("div");
    info.appendChild(el("div", "agent-name", a.name));
    info.appendChild(el("div", "agent-role", a.role));
    top.appendChild(info);
    const stLabel = { active: "פעיל", idle: "ממתין", done: "סיים" }[a.status] || a.status;
    top.appendChild(el("span", "agent-status " + a.status, stLabel));
    card.appendChild(top);
    card.appendChild(el("div", "agent-detail", a.detail));
    ag.appendChild(card);
  });

  // stats
  const k = d.knowledge;
  const stats = $("dashStats");
  stats.innerHTML = "";
  const mk = (n, lbl) => { const c = el("div", "stat-card"); c.innerHTML = `<b>${n}</b><span>${lbl}</span>`; return c; };
  stats.appendChild(mk(k.runs, "הרצות"));
  stats.appendChild(mk(k.total_signatures, "סוגי ממצאים"));
  stats.appendChild(mk(`${d.tools.installed}/${d.tools.total}`, "כלים מותקנים"));

  // severity bars
  const sev = $("dashSeverity");
  sev.innerHTML = "";
  const order = [["critical", "קריטי"], ["high", "גבוה"], ["medium", "בינוני"], ["low", "נמוך"]];
  const max = Math.max(1, ...order.map(([c]) => k.severity[c] || 0));
  order.forEach(([c, he]) => {
    const n = k.severity[c] || 0;
    const row = el("div", "sev-row");
    row.appendChild(el("span", "lbl", he));
    const bar = el("div", "bar");
    const fill = el("div", "fill " + c);
    fill.style.width = (n / max * 100) + "%";
    bar.appendChild(fill);
    row.appendChild(bar);
    row.appendChild(el("span", "n", n));
    sev.appendChild(row);
  });

  // top threats
  const top = $("dashTop");
  top.innerHTML = "";
  if (!k.top.length) top.appendChild(el("div", "feed-empty", "אין נתונים עדיין — הרץ משימת Purple"));
  k.top.forEach(t => {
    const row = el("div", "top-threat");
    row.appendChild(el("span", "arrow", "‹"));
    row.appendChild(el("span", null, (SEV_ICON[t.severity] || "•") + " " + t.name));
    row.appendChild(el("span", "cnt", t.count + "×"));
    row.onclick = () => openThreat(t.signature);
    top.appendChild(row);
  });

  // activity feed (magazine)
  const feed = $("dashFeed");
  feed.innerHTML = "";
  if (!d.activity.length) { feed.appendChild(el("div", "feed-empty", "עדיין לא בוצעו משימות. עבור ל🤖 עוזר AI כדי להתחיל.")); return; }
  d.activity.forEach(a => {
    const card = el("div", "feed-card" + (a.type === "purple" ? " purple" : ""));
    const head = el("div", "feed-head");
    const icon = a.type === "purple" ? "🟣" : "🤖";
    head.appendChild(el("span", null, `${icon} ${a.intent || "משימה"}`));
    head.appendChild(el("span", "feed-when", relTime(a.ts) || a.when));
    card.appendChild(head);
    const body = el("div", "feed-body");
    if (a.type === "purple") {
      body.innerHTML = `<span class="tag">🎯 ${escapeHtml(a.target)}</span>` +
        `<span class="tag">🔴 ${a.red_findings} ממצאים</span>` +
        `<span class="tag">🔵 ${a.threats} איומים</span>` +
        (a.severity ? `<span class="tag">${SEV_ICON[a.severity] || ""} ${SEV_HE[a.severity] || a.severity}</span>` : "") +
        (a.new_learned && a.new_learned.length ? `<div class="learn-new">🧠 נלמד חדש: ${escapeHtml(a.new_learned.join(", "))}</div>` : "");
    } else {
      body.innerHTML = `<span class="tag">🎯 ${escapeHtml(a.target)}</span>` +
        `<span class="tag">${a.steps} שלבים</span>` +
        `<span class="tag">🔎 ${a.findings} ממצאים</span>`;
    }
    card.appendChild(body);
    feed.appendChild(card);
  });
}

async function openThreat(sig) {
  const modal = $("threatModal"), body = $("threatBody");
  body.innerHTML = '<p style="color:var(--text-dim)">טוען...</p>';
  modal.classList.remove("hidden");
  let t;
  try {
    const res = await fetch("/api/threat/" + encodeURIComponent(sig));
    t = await res.json();
    if (!res.ok) { body.innerHTML = `<p>${escapeHtml(t.error || "שגיאה")}</p>`; return; }
  } catch (e) { body.innerHTML = "<p>שגיאת רשת</p>"; return; }

  const list = (arr) => "<ul>" + arr.map(x => `<li>${escapeHtml(x)}</li>`).join("") + "</ul>";
  let html = "";
  html += `<div class="tm-head"><h2>${SEV_ICON[t.severity] || ""} ${escapeHtml(t.name)}</h2>`;
  html += `<span class="tm-sev ${t.severity}">${SEV_HE[t.severity] || t.severity}</span></div>`;
  if (t.mitre) html += `<div class="tm-meta">MITRE ATT&CK: <span class="mitre">${escapeHtml(t.mitre)}</span></div>`;

  html += `<div class="tm-stats">`;
  html += `<div class="tm-stat"><b>${t.count}</b><span>הופעות</span></div>`;
  html += `<div class="tm-stat"><b>${t.occurrences.length}</b><span>הרצות</span></div>`;
  if (t.first_seen) html += `<div class="tm-stat"><b style="font-size:12px">${escapeHtml(t.first_seen)}</b><span>נראה לראשונה</span></div>`;
  html += `</div>`;

  html += `<div class="tm-threat">⚠️ ${escapeHtml(t.threat)}</div>`;
  html += `<h4>🛡️ פעולות הגנה מומלצות</h4>${list(t.defenses)}`;
  html += `<h4>👁️ זיהוי וניטור</h4>${list(t.detections)}`;
  if (t.config) html += `<h4>⚙️ תצורה לדוגמה</h4><pre>${escapeHtml(t.config)}</pre>`;

  html += `<h4>📍 היכן נצפה</h4>`;
  if (t.occurrences.length) {
    html += `<div class="tm-occ">`;
    t.occurrences.forEach(o => {
      html += `<div class="tm-occ-row"><span class="t">${escapeHtml(o.target)}</span>` +
              `<span>${escapeHtml(o.intent || "")}</span>` +
              `<span class="w">${o.ts ? relTime(o.ts) : escapeHtml(o.when)}</span></div>`;
    });
    html += `</div>`;
  } else {
    html += `<p style="color:var(--text-dim);font-size:13px">אין רישום מפורט של הופעות (הידע נצבר לפני הוספת יומן הפעילות).</p>`;
  }
  body.innerHTML = html;
}

/* ================= PURPLE TEAM (Red -> Broker -> Blue -> Orchestrator) ===== */
let PURPLE_ID = null;
let PURPLE_TIMER = null;

async function startPurple() {
  if (!PLAN) return;
  const included = [];
  document.querySelectorAll("#planSteps input[type=checkbox]").forEach(cb => {
    if (cb.checked) included.push(PLAN.steps[parseInt(cb.dataset.idx, 10)]);
  });
  if (!included.length) return;
  $("purpleBtn").disabled = true;
  try {
    const res = await fetch("/api/purple", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent: PLAN.intent, target: PLAN.target, steps: included })
    });
    const data = await res.json();
    if (!res.ok) { alert(data.error || "שגיאה"); return; }
    PURPLE_ID = data.purple_id;
    $("purpleMeta").innerHTML =
      `<span class="pill">${escapeHtml(PLAN.intent)}</span><span class="pill">${escapeHtml(PLAN.target)}</span>`;
    $("purpleReportBtn").classList.add("hidden");
    $("purpleStopBtn").classList.remove("hidden");
    $("purpleBlue").innerHTML = '<div class="threats-empty">⏳ ממתין לממצאי הצוות האדום...</div>';
    $("purpleLearn").innerHTML = "";
    showScreen("purple");
    pollPurple();
  } finally {
    $("purpleBtn").disabled = false;
  }
}

async function pollPurple() {
  clearTimeout(PURPLE_TIMER);
  if (!PURPLE_ID) return;
  try {
    const res = await fetch("/api/purple/" + PURPLE_ID);
    const p = await res.json();
    renderPurpleRed(p.red);
    // phase badge
    const badge = $("purplePhase");
    if (p.phase === "red") { badge.className = "status-badge running"; badge.textContent = "🔴 צוות אדום פועל"; }
    else if (p.phase === "blue") { badge.className = "status-badge running blue-phase"; badge.textContent = "🔵 צוות כחול מנתח"; }
    else { badge.className = "status-badge done"; badge.textContent = "🟣 הושלם"; }

    if (p.threats && (p.threats.length || p.phase === "done")) renderThreats(p.threats);
    if (p.learning) renderLearning(p.learning);

    if (p.status === "running") {
      PURPLE_TIMER = setTimeout(pollPurple, 1000);
    } else {
      $("purpleStopBtn").classList.add("hidden");
      if (p.report) { REPORT_MD = p.report; $("purpleReportBtn").classList.remove("hidden"); }
    }
  } catch (e) {
    PURPLE_TIMER = setTimeout(pollPurple, 1500);
  }
}

function renderPurpleRed(m) {
  const box = $("purpleRed");
  box.innerHTML = "";
  if (!m || !m.steps) return;
  m.steps.forEach((s, i) => {
    const wrap = el("div", "mstep" + (i === m.current && m.status === "running" ? " active" : ""));
    const head = el("div", "mstep-head");
    let ico = S_ICON[s.status] || "•", vcls = "v-pending", vlabel = "ממתין";
    if (s.status === "running") { ico = "🔄"; vcls = "v-running"; vlabel = "רץ"; }
    if (s.verdict) {
      const v = s.verdict.verdict;
      vcls = "v-" + v; vlabel = s.verdict.label || v;
      ico = { ok: "✅", ok_findings: "🔎", warn: "⚠️", fail: "❌", stopped: "⏹️" }[v] || "•";
    }
    head.appendChild(el("span", "mstep-ico", ico));
    const info = el("div", "mstep-info");
    info.appendChild(el("div", "mstep-title", `${i + 1}. ${s.tool_name}`));
    info.appendChild(el("div", "mstep-why", s.why || ""));
    head.appendChild(info);
    head.appendChild(el("span", "mstep-verdict " + vcls, vlabel));
    wrap.appendChild(head);
    if (s.verdict && s.verdict.findings && s.verdict.findings.length) {
      const f = el("div", "mstep-findings");
      s.verdict.findings.slice(0, 6).forEach(x => f.appendChild(el("code", null, x)));
      wrap.appendChild(f);
    }
    box.appendChild(wrap);
  });
}

const SEV_HE = { critical: "קריטי", high: "גבוה", medium: "בינוני", low: "נמוך" };
const SEV_ICON = { critical: "🟥", high: "🟧", medium: "🟨", low: "🟩" };

function renderThreats(threats) {
  const box = $("purpleBlue");
  box.innerHTML = "";
  if (!threats.length) {
    box.innerHTML = '<div class="threats-empty">לא נמצאו ממצאים למיפוי הגנתי בהרצה זו.</div>';
    return;
  }
  threats.forEach(t => {
    const card = el("div", "threat sev-" + t.severity);
    const title = el("div", "threat-title");
    title.appendChild(el("span", null, `${SEV_ICON[t.severity]} ${t.name}`));
    title.appendChild(el("span", "threat-sev", SEV_HE[t.severity] || t.severity));
    card.appendChild(title);
    card.appendChild(el("div", "threat-desc", t.threat));
    if (t.mitre) card.appendChild(el("div", "threat-mitre", "MITRE ATT&CK: " + t.mitre));

    const ev = el("div", "evidence");
    ev.appendChild(el("h4", null, "🔴 עדות (צוות אדום):"));
    (t.evidence || []).slice(0, 3).forEach(e => ev.appendChild(el("code", null, e)));
    card.appendChild(ev);

    const def = el("div");
    def.appendChild(el("h4", null, "🛡️ פעולות הגנה:"));
    const ul = el("ul");
    t.defenses.forEach(d => ul.appendChild(el("li", null, d)));
    def.appendChild(ul);
    card.appendChild(def);

    const det = el("div");
    det.appendChild(el("h4", null, "👁️ זיהוי וניטור:"));
    const ul2 = el("ul");
    t.detections.forEach(d => ul2.appendChild(el("li", null, d)));
    det.appendChild(ul2);
    card.appendChild(det);

    if (t.config) {
      card.appendChild(el("h4", null, "⚙️ תצורה לדוגמה:"));
      card.appendChild(el("pre", null, t.config));
    }
    box.appendChild(card);
  });
}

function renderLearning(l) {
  const box = $("purpleLearn");
  box.innerHTML = "";
  const h = el("h3", null, "🧠 למידה מצטברת");
  box.appendChild(h);
  const stat = el("div", "stat");
  const s1 = el("div"); s1.innerHTML = `<b>${l.runs}</b><span>הרצות</span>`;
  const s2 = el("div"); s2.innerHTML = `<b>${l.total_signatures}</b><span>סוגי ממצאים ידועים</span>`;
  const s3 = el("div"); s3.innerHTML = `<b>${l.new_this_run.length}</b><span>חדשים בהרצה זו</span>`;
  stat.appendChild(s1); stat.appendChild(s2); stat.appendChild(s3);
  box.appendChild(stat);
  if (l.new_this_run.length) box.appendChild(el("div", "learn-new", "✨ חדש: " + l.new_this_run.join(", ")));
  if (l.top && l.top.length) {
    box.appendChild(el("div", null, "הנפוצים ביותר:"));
    const ul = el("ul");
    l.top.forEach(x => ul.appendChild(el("li", null, `${x.name} — ${x.count}×`)));
    box.appendChild(ul);
  }
}

async function stopPurple() {
  if (!PURPLE_ID) return;
  await fetch("/api/purple/" + PURPLE_ID + "/stop", { method: "POST" });
  pollPurple();
}

/* ---- minimal, safe Markdown -> HTML for the report ---- */
function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function mdInline(s) {
  return escapeHtml(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}
function mdToHtml(md) {
  const lines = md.split("\n");
  let html = "", inList = false, inCode = false, code = "";
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      if (inCode) { html += "<pre><code>" + escapeHtml(code) + "</code></pre>"; code = ""; inCode = false; }
      else { closeList(); inCode = true; }
      continue;
    }
    if (inCode) { code += line + "\n"; continue; }
    if (/^###\s+/.test(line)) { closeList(); html += "<h3>" + mdInline(line.replace(/^###\s+/, "")) + "</h3>"; }
    else if (/^##\s+/.test(line)) { closeList(); html += "<h2>" + mdInline(line.replace(/^##\s+/, "")) + "</h2>"; }
    else if (/^#\s+/.test(line)) { closeList(); html += "<h1>" + mdInline(line.replace(/^#\s+/, "")) + "</h1>"; }
    else if (/^---\s*$/.test(line)) { closeList(); html += "<hr>"; }
    else if (/^\s*-\s+/.test(line)) {
      if (!inList) { html += "<ul>"; inList = true; }
      const indent = /^\s{2,}-/.test(line);
      html += "<li" + (indent ? " style='margin-inline-start:18px'" : "") + ">" + mdInline(line.replace(/^\s*-\s+/, "")) + "</li>";
    }
    else if (line.trim() === "") { closeList(); }
    else { closeList(); html += "<p>" + mdInline(line) + "</p>"; }
  }
  closeList();
  if (inCode) html += "<pre><code>" + escapeHtml(code) + "</code></pre>";
  return html;
}

function showReport() {
  $("reportBody").innerHTML = mdToHtml(REPORT_MD || "*(אין דוח)*");
  showScreen("ai-report");
}

function downloadReport() {
  const blob = new Blob([REPORT_MD], { type: "text/markdown" });
  const a = el("a"); a.href = URL.createObjectURL(blob); a.download = "kali_report.md"; a.click();
}

function initAI() {
  renderAIExamples();
  $("planBtn").onclick = makePlan;
  $("missionBtn").onclick = startMission;
  $("missionStopBtn").onclick = stopMission;
  $("viewReportBtn").onclick = showReport;
  $("purpleBtn").onclick = startPurple;
  $("purpleStopBtn").onclick = stopPurple;
  $("purpleReportBtn").onclick = showReport;
  $("reportCopyBtn").onclick = () => navigator.clipboard.writeText(REPORT_MD);
  $("reportDownloadBtn").onclick = downloadReport;
  $("newMissionBtn").onclick = () => { showScreen("ai-prompt"); };
}

function init() {
  $("homeBtn").onclick = () => showScreen("picker");
  $("search").oninput = (e) => { searchTerm = e.target.value; renderGrid(); };
  document.querySelectorAll("[data-goto]").forEach(b => b.onclick = () => showScreen(b.dataset.goto));
  $("runBtn").onclick = runTool;
  $("stopBtn").onclick = stopJob;
  $("copyBtn").onclick = () => navigator.clipboard.writeText($("output").textContent);
  $("downloadBtn").onclick = download;
  $("rerunBtn").onclick = () => { if (CURRENT_TOOL) { showScreen("form"); } };
  $("threatClose").onclick = () => $("threatModal").classList.add("hidden");
  $("threatModal").onclick = (e) => { if (e.target === $("threatModal")) $("threatModal").classList.add("hidden"); };
  $("installCancel").onclick = () => $("installModal").classList.add("hidden");
  $("installGo").onclick = doInstall;
  $("sudoPass").onkeydown = (e) => { if (e.key === "Enter") doInstall(); };
  initAI();
  loadCatalog();
}

document.addEventListener("DOMContentLoaded", init);
