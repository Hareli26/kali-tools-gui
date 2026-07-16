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
  if (typeof hyperjump === "function") hyperjump();   // brief jump to lightspeed on nav
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  $("screen-" + name).classList.add("active");
  const isDash = name === "dashboard";
  const isVault = name === "vault";
  const isUsers = name === "users";
  const isHistory = name === "history";
  const isPlaybooks = name === "playbooks";
  const isLearning = name === "learning";
  const isAI = name.startsWith("ai-") || name === "purple";
  const isTools = !isDash && !isAI && !isVault && !isUsers && !isHistory && !isPlaybooks && !isLearning;
  const mt = $("modeTools"), ma = $("modeAI"), md = $("modeDash"), mv = $("modeVault"),
        mu = $("modeUsers"), mh = $("modeHistory"), mp = $("modePlaybooks"), ml = $("modeLearning");
  if (mt) mt.classList.toggle("active", isTools);
  if (ma) ma.classList.toggle("active", isAI);
  if (md) md.classList.toggle("active", isDash);
  if (mv) mv.classList.toggle("active", isVault);
  if (mu) mu.classList.toggle("active", isUsers);
  if (mh) mh.classList.toggle("active", isHistory);
  if (mp) mp.classList.toggle("active", isPlaybooks);
  if (ml) ml.classList.toggle("active", isLearning);
  if (isDash) { DASH_ANIMATE = true; loadDashboard(); }
  else if (typeof agents3dStop === "function") agents3dStop();  // pause agents 3D off-screen
  if (isVault) loadVault();
  else if (typeof galaxyStop === "function") galaxyStop();  // pause the 3D loop off-screen
  if (isUsers) loadUsers();
  if (isHistory) loadHistory();
  if (isPlaybooks) loadPlaybooks();
  if (isLearning) loadLearning();
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
  const anim = !searchTerm && activeCat === "all";   // cascade only on the full view, not while filtering
  list.forEach((t, i) => {
    const cat = CATS[t.category] || {};
    const card = el("div", "tool-card hud tilt" + (anim ? " reveal" : "") + (t.installed ? "" : " disabled"));
    if (anim) card.style.animationDelay = Math.min(i, 24) * 0.028 + "s";
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

  // "about" — what the tool is and what you can do with it
  const about = $("formAbout");
  about.innerHTML = "";
  if (tool.about) {
    about.appendChild(el("div", "tool-about-label", "ℹ️ על הכלי — מה זה ומה אפשר לעשות"));
    about.appendChild(el("p", "tool-about-text", tool.about));
    about.classList.remove("hidden");
  } else {
    about.classList.add("hidden");
  }

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
  if (!requireRun()) return;
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
  if (!requireRun()) return;
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
let REPORT_META = null;   // {intent, target, type} of the currently shown report

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
  if (!requireRun()) return;
  const intent = $("aiIntent").value.trim();
  const target = $("aiTarget").value.trim();
  const err = $("aiPromptErr");
  err.classList.add("hidden");
  if (!intent || !target) {
    err.textContent = "יש להזין גם כוונה וגם מטרה."; err.classList.remove("hidden"); return;
  }
  const ai = $("aiPlanLLM").checked;
  $("planBtn").disabled = true;
  $("planBtn").textContent = ai ? "🧠 ה‑AI מתכנן..." : "🧠 מתכנן...";
  try {
    const res = await fetch("/api/plan", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent, target, ai })
    });
    const data = await res.json();
    if (!res.ok) { err.textContent = data.error || "שגיאה"; err.classList.remove("hidden"); return; }
    if (data.ai_note) alert("ℹ️ " + data.ai_note);
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
    `<span class="pill ${data.engine === "ai-llm" ? "ai" : ""}">מנוע: ${data.engine === "ai-llm" ? "🧠 AI (LLM)" : "⚙️ חוקים"}</span>` +
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

async function runMission(intent, target, steps) {
  const res = await fetch("/api/mission", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ intent, target, steps })
  });
  const data = await res.json();
  if (!res.ok) { alert(data.error || "שגיאה"); return false; }
  MISSION_ID = data.mission_id;
  $("missionMeta").innerHTML =
    `<span class="pill">${escapeHtml(intent)}</span><span class="pill">${escapeHtml(target)}</span>`;
  $("viewReportBtn").classList.add("hidden");
  $("missionStopBtn").classList.remove("hidden");
  showScreen("ai-mission");
  pollMission();
  trackActive();
  return true;
}

async function startMission() {
  if (!requireRun()) return;
  if (!PLAN) return;
  const included = [];
  document.querySelectorAll("#planSteps input[type=checkbox]").forEach(cb => {
    if (cb.checked) included.push(PLAN.steps[parseInt(cb.dataset.idx, 10)]);
  });
  if (!included.length) return;
  $("missionBtn").disabled = true;
  try { await runMission(PLAN.intent, PLAN.target, included); }
  finally { $("missionBtn").disabled = false; }
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
        REPORT_META = { intent: m.intent, target: m.target, type: "mission" };
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

/* ==================================================== GLOBAL RUNNING BAR =====
   A run continues on the server no matter where you navigate. This bar polls
   /api/active and stays visible across every screen, showing live what the
   agent is doing, with a one-click jump back to the full view. Also re-attaches
   after a page reload. */
let ACTIVE_TIMER = null;
let RUN_BAR_SEEN = null;   // {kind, id} of the run currently shown as "running"

async function trackActive() {
  clearTimeout(ACTIVE_TIMER);
  let idle = true;
  try {
    const a = await (await fetch("/api/active")).json();
    const run = a.purple || a.mission;
    const kind = a.purple ? "purple" : "mission";
    if (run) {
      idle = false;
      RUN_BAR_SEEN = { kind, id: run.id };
      // remember ids so "jump back" + detail pollers work even after a reload
      if (kind === "purple") PURPLE_ID = run.id; else MISSION_ID = run.id;
      showRunBar(kind, run);
    } else if (RUN_BAR_SEEN) {
      showRunBarDone(RUN_BAR_SEEN.kind);   // just finished this session
      RUN_BAR_SEEN = null;
    }
  } catch (e) { /* keep trying */ }
  // fast while a run is live, slow heartbeat when idle (catches runs from MCP/other tabs)
  ACTIVE_TIMER = setTimeout(trackActive, idle ? 4000 : 1200);
}

function onRunScreen(kind) {
  const id = kind === "purple" ? "screen-purple" : "screen-ai-mission";
  const s = $(id);
  return s && s.classList.contains("active");
}

function showRunBar(kind, run) {
  const bar = $("runBar");
  // if already looking at the full view, no need for the bar
  if (onRunScreen(kind)) { bar.classList.add("hidden"); return; }
  const isPurple = kind === "purple";
  $("runBar").className = "run-bar" + (isPurple ? " purple" : "");
  const phaseTxt = isPurple
    ? (run.phase === "blue" ? "🔵 צוות כחול מנתח" : run.phase === "done" ? "מסכם" : "🔴 צוות אדום תוקף")
    : "⚙️ המשימה רצה";
  $("runBarTitle").textContent = phaseTxt;
  const tool = run.tool ? `כרגע: ${run.tool}` : "מתכונן...";
  $("runBarSub").textContent = `${tool} · ${escapeHtml(run.intent || "")} → ${escapeHtml(run.target || "")}`;
  const total = run.total || 0, done = run.done || 0;
  $("runBarFill").style.width = total ? Math.round((done / total) * 100) + "%" : "8%";
  $("runBarCount").textContent = total ? `${done}/${total}` : "";
  bar.classList.remove("hidden");
}

function showRunBarDone(kind) {
  const bar = $("runBar");
  if (onRunScreen(kind)) { bar.classList.add("hidden"); return; }
  bar.className = "run-bar done";
  $("runBarTitle").textContent = "✅ הבדיקה הושלמה";
  $("runBarSub").textContent = "לחץ לצפייה בדוח המלא";
  $("runBarFill").style.width = "100%";
  $("runBarCount").textContent = "";
  bar.classList.remove("hidden");
  setTimeout(() => { if (bar.classList.contains("done")) bar.classList.add("hidden"); }, 15000);
}

function runBarJump() {
  const seen = RUN_BAR_SEEN;
  const kind = seen ? seen.kind : ($("runBar").classList.contains("purple") ? "purple" : "mission");
  $("runBar").classList.add("hidden");
  if (kind === "purple") { showScreen("purple"); if (PURPLE_ID) pollPurple(); }
  else { showScreen("ai-mission"); if (MISSION_ID) pollMission(); }
}

/* ============================ AUDIT LOG ==================================== */
async function openAudit() {
  const body = $("auditBody");
  body.innerHTML = '<div class="audit-empty">טוען...</div>';
  $("auditModal").classList.remove("hidden");
  try {
    const d = await (await fetch("/api/audit")).json();
    const ents = d.entries || [];
    if (!ents.length) { body.innerHTML = '<div class="audit-empty">אין רשומות ביקורת עדיין.</div>'; return; }
    body.innerHTML = "";
    const actLabel = { "run-tool": "כלי", "mission": "משימה", "purple": "Purple", "install": "התקנה" };
    ents.forEach(e => {
      const row = el("div", "audit-row");
      row.appendChild(el("span", "when", e.ts));
      const right = el("div");
      const who = el("span", "who", "👤 " + e.user + "  ");
      const act = el("span", "act " + e.action, actLabel[e.action] || e.action);
      right.appendChild(who); right.appendChild(act);
      if (e.detail) right.appendChild(el("div", "det", e.detail));
      row.appendChild(right);
      body.appendChild(row);
    });
  } catch (err) { body.innerHTML = '<div class="audit-empty">שגיאה בטעינת היומן.</div>'; }
}

/* ===================== AGENT BRAIN — futuristic capability map ============= */
const SVGNS = "http://www.w3.org/2000/svg";
const svgEl = (t, attrs) => { const e = document.createElementNS(SVGNS, t); for (const k in (attrs||{})) e.setAttribute(k, attrs[k]); return e; };
function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`;
}
let BRAIN_DATA = null;
const BRAIN = { agent: null, k: 1, panX: 0, panY: 0, nodes: [], conns: [],
  raf: null, target: null, dragging: false, lx: 0, ly: 0, root: null, coreGlow: null };

async function openBrain(agentId) {
  if (!BRAIN_DATA) {
    try { BRAIN_DATA = await (await fetch("/api/brain")).json(); }
    catch (e) { return; }
  }
  const agent = BRAIN_DATA[agentId];
  if (!agent) return;
  BRAIN.agent = agent;
  BRAIN.k = 1; BRAIN.panX = 0; BRAIN.panY = 0; BRAIN.target = null;
  $("brainOverlay").classList.remove("hidden");
  $("brainIcon").textContent = agent.icon;
  $("brainName").textContent = agent.name;
  $("brainName").parentElement.style.color = agent.color;
  $("brainCore").textContent = "◈ " + agent.core + " · " + agent.tagline;
  const live = $("brainLive"); live.innerHTML = "";
  Object.entries(agent.live || {}).forEach(([kk, vv]) =>
    live.appendChild(Object.assign(document.createElement("div"), { className: "lv", innerHTML: `<b>${vv}</b> ${kk}` })));
  buildBrainScene(agent);
  if (BRAIN.raf) cancelAnimationFrame(BRAIN.raf);
  BRAIN.raf = requestAnimationFrame(brainFrame);
}

function buildBrainScene(agent) {
  const svg = $("brainSvg");
  svg.innerHTML = "";
  const defs = svgEl("defs");
  const g = svgEl("radialGradient", { id: "coreGrad" });
  g.appendChild(svgEl("stop", { offset: "0%", "stop-color": agent.color, "stop-opacity": "0.95" }));
  g.appendChild(svgEl("stop", { offset: "60%", "stop-color": agent.color, "stop-opacity": "0.25" }));
  g.appendChild(svgEl("stop", { offset: "100%", "stop-color": agent.color, "stop-opacity": "0" }));
  defs.appendChild(g);
  const f = svgEl("filter", { id: "glow", x: "-60%", y: "-60%", width: "220%", height: "220%" });
  f.appendChild(svgEl("feGaussianBlur", { stdDeviation: "4", result: "b" }));
  const m = svgEl("feMerge"); m.appendChild(svgEl("feMergeNode", { in: "b" })); m.appendChild(svgEl("feMergeNode", { in: "SourceGraphic" }));
  f.appendChild(m); defs.appendChild(f);
  svg.appendChild(defs);

  const root = svgEl("g", { id: "brainRoot" });
  svg.appendChild(root);
  BRAIN.root = root;

  // decorative concentric rings
  const deco = svgEl("g", { opacity: "0.5" });
  [140, 280, 440].forEach(r => deco.appendChild(svgEl("circle", { cx: 0, cy: 0, r, fill: "none",
    stroke: hexA(agent.color, 0.10), "stroke-width": 1, "stroke-dasharray": "3 9" })));
  root.appendChild(deco);

  const connG = svgEl("g"); const partG = svgEl("g"); const nodeG = svgEl("g");
  root.appendChild(connG); root.appendChild(partG); root.appendChild(nodeG);

  const nodes = [], conns = [];
  const R1 = 300, R2 = 168, R3 = 96;
  const core = { x: 0, y: 0, depth: 0, r: 46, name: agent.core };
  nodes.push(core);

  const caps = agent.caps || [];
  caps.forEach((cap, i) => {
    const a = (-90 + i * 360 / caps.length) * Math.PI / 180;
    const cx = Math.cos(a) * R1, cy = Math.sin(a) * R1;
    const cnode = { x: cx, y: cy, depth: 1, r: 30, name: cap.name, desc: cap.desc };
    nodes.push(cnode); conns.push({ from: core, to: cnode });
    const kids = cap.children || [];
    kids.forEach((kid, j) => {
      const ka = a + ((j - (kids.length - 1) / 2) * 26) * Math.PI / 180;
      const kx = cx + Math.cos(ka) * R2, ky = cy + Math.sin(ka) * R2;
      const knode = { x: kx, y: ky, depth: 2, r: 19, name: kid.name, desc: kid.desc };
      nodes.push(knode); conns.push({ from: cnode, to: knode });
      (kid.leaves || []).forEach((lf, l) => {
        const la = ka + ((l - ((kid.leaves.length) - 1) / 2) * 22) * Math.PI / 180;
        const lx = kx + Math.cos(la) * R3, ly = ky + Math.sin(la) * R3;
        const lnode = { x: lx, y: ly, depth: 3, r: 9, name: lf };
        nodes.push(lnode); conns.push({ from: knode, to: lnode });
      });
    });
  });

  // build connection + particle elements
  conns.forEach(c => {
    c.line = svgEl("line", { x1: c.from.x, y1: c.from.y, x2: c.to.x, y2: c.to.y,
      stroke: hexA(agent.color, 0.5), "stroke-width": c.to.depth === 1 ? 1.6 : 1 });
    connG.appendChild(c.line);
    c.p = svgEl("circle", { r: c.to.depth === 1 ? 3 : 2, fill: "#fff" });
    c.pt = Math.random(); partG.appendChild(c.p);
  });

  // build node elements
  nodes.forEach(n => {
    n.g = svgEl("g");
    if (n.depth === 0) {
      n.glow = svgEl("circle", { cx: 0, cy: 0, r: 120, fill: "url(#coreGrad)" });
      n.g.appendChild(n.glow); BRAIN.coreGlow = n.glow;
      n.g.appendChild(svgEl("circle", { cx: 0, cy: 0, r: n.r, fill: hexA(agent.color, 0.22),
        stroke: agent.color, "stroke-width": 2, filter: "url(#glow)" }));
      const gl = svgEl("text", { x: 0, y: 0, "font-size": 34, class: "brain-core-glyph" }); gl.textContent = agent.icon;
      n.g.appendChild(gl);
      const lbl = svgEl("text", { x: 0, y: n.r + 20, "font-size": 15, class: "brain-node-label", "font-weight": 700 });
      lbl.textContent = n.name; n.g.appendChild(lbl);
    } else {
      n.circle = svgEl("circle", { cx: 0, cy: 0, r: n.r, fill: hexA(agent.color, 0.16),
        stroke: agent.color, "stroke-width": n.depth === 1 ? 1.8 : 1.2 });
      n.g.appendChild(n.circle);
      const fs = n.depth === 1 ? 13 : n.depth === 2 ? 11 : 9;
      const lbl = svgEl("text", { x: 0, y: n.r + fs + 2, "font-size": fs, class: "brain-node-label" });
      lbl.textContent = n.name; n.g.appendChild(lbl);
      if (n.desc && n.depth <= 2) {
        const d = svgEl("text", { x: 0, y: n.r + fs * 2 + 4, "font-size": fs - 2, class: "brain-node-label brain-node-sub" });
        d.textContent = n.desc; n.g.appendChild(d);
      }
      if (n.depth <= 2) { n.g.style.cursor = "pointer"; n.g.addEventListener("click", (e) => { e.stopPropagation(); focusNode(n); }); }
    }
    n.g.setAttribute("transform", `translate(${n.x},${n.y})`);
    nodeG.appendChild(n.g);
  });

  BRAIN.nodes = nodes; BRAIN.conns = conns;
}

function lodOpacity(depth, k) {
  if (depth === 0) return 1;
  if (depth === 1) return Math.max(0, Math.min(1, (k - 0.5) / 0.3));
  if (depth === 2) return Math.max(0, Math.min(1, (k - 1.35) / 0.5));
  return Math.max(0, Math.min(1, (k - 2.7) / 0.5));
}

function brainRender() {
  const svg = $("brainSvg"); const w = svg.clientWidth, h = svg.clientHeight;
  const cx = w / 2, cy = h / 2;
  BRAIN.root.setAttribute("transform", `translate(${cx + BRAIN.panX},${cy + BRAIN.panY}) scale(${BRAIN.k})`);
  BRAIN.nodes.forEach(n => {
    const o = lodOpacity(n.depth, BRAIN.k);
    n.g.setAttribute("opacity", o);
    n.g.style.pointerEvents = o > 0.05 ? "auto" : "none";
  });
  BRAIN.conns.forEach(c => {
    const o = Math.min(lodOpacity(c.from.depth, BRAIN.k), lodOpacity(c.to.depth, BRAIN.k));
    c.line.setAttribute("opacity", o * 0.55);
    c.p.setAttribute("opacity", o);
  });
  $("brainZoom").textContent = "×" + BRAIN.k.toFixed(1);
}

function brainFrame(ts) {
  // focus lerp
  if (BRAIN.target) {
    const t = BRAIN.target, s = 0.12;
    BRAIN.k += (t.k - BRAIN.k) * s;
    BRAIN.panX += (t.panX - BRAIN.panX) * s;
    BRAIN.panY += (t.panY - BRAIN.panY) * s;
    if (Math.abs(t.k - BRAIN.k) < 0.01 && Math.abs(t.panX - BRAIN.panX) < 0.5) BRAIN.target = null;
  }
  // particles flow inner -> outer
  const spd = 0.006;
  BRAIN.conns.forEach(c => {
    c.pt = (c.pt + spd) % 1;
    const x = c.from.x + (c.to.x - c.from.x) * c.pt;
    const y = c.from.y + (c.to.y - c.from.y) * c.pt;
    c.p.setAttribute("cx", x); c.p.setAttribute("cy", y);
  });
  // core breathing
  if (BRAIN.coreGlow) {
    const r = 110 + Math.sin(ts / 700) * 22;
    BRAIN.coreGlow.setAttribute("r", r);
  }
  brainRender();
  BRAIN.raf = requestAnimationFrame(brainFrame);
}

function focusNode(n) {
  const svg = $("brainSvg");
  const targetK = n.depth === 1 ? 1.7 : n.depth === 2 ? 3.0 : BRAIN.k;
  BRAIN.target = { k: targetK, panX: -n.x * targetK, panY: -n.y * targetK };
}

function brainZoomAt(mx, my, factor) {
  const svg = $("brainSvg"); const cx = svg.clientWidth / 2, cy = svg.clientHeight / 2;
  const wx = (mx - cx - BRAIN.panX) / BRAIN.k, wy = (my - cy - BRAIN.panY) / BRAIN.k;
  BRAIN.k = Math.max(0.4, Math.min(6, BRAIN.k * factor));
  BRAIN.panX = mx - cx - wx * BRAIN.k;
  BRAIN.panY = my - cy - wy * BRAIN.k;
  BRAIN.target = null;
}

function closeBrain() {
  $("brainOverlay").classList.add("hidden");
  if (BRAIN.raf) { cancelAnimationFrame(BRAIN.raf); BRAIN.raf = null; }
}

function initBrain() {
  const svg = $("brainSvg"), ov = $("brainOverlay");
  $("brainClose").onclick = closeBrain;
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    brainZoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.12 : 1 / 1.12);
  }, { passive: false });
  svg.addEventListener("pointerdown", (e) => { BRAIN.dragging = true; BRAIN.lx = e.clientX; BRAIN.ly = e.clientY; ov.classList.add("dragging"); svg.setPointerCapture(e.pointerId); });
  svg.addEventListener("pointermove", (e) => { if (!BRAIN.dragging) return; BRAIN.panX += e.clientX - BRAIN.lx; BRAIN.panY += e.clientY - BRAIN.ly; BRAIN.lx = e.clientX; BRAIN.ly = e.clientY; BRAIN.target = null; });
  svg.addEventListener("pointerup", () => { BRAIN.dragging = false; ov.classList.remove("dragging"); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !ov.classList.contains("hidden")) closeBrain(); });
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

  const anim = DASH_ANIMATE; DASH_ANIMATE = false;   // animate only on first entry
  // agents
  DASH_AGENTS = d.agents || [];
  if (AGENTS3D_ON) { buildAgents3d(); }   // keep the 3D constellation live
  const ag = $("dashAgents");
  ag.innerHTML = "";
  d.agents.forEach((a, i) => {
    const card = el("div", "agent-card hud tilt " + a.status + (anim ? " reveal" : ""));
    if (anim) card.style.animationDelay = i * 0.06 + "s";
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
    if (a.id) {
      card.classList.add("clickable-agent");
      card.appendChild(el("div", "agent-brain-hint", "🧠 לחץ לתצוגת מוח"));
      card.onclick = () => openBrain(a.id);
    }
    ag.appendChild(card);
  });

  // stats
  const k = d.knowledge;
  const stats = $("dashStats");
  stats.innerHTML = "";
  const mk = (n, lbl, num) => {
    const c = el("div", "stat-card hud" + (anim ? " reveal" : ""));
    c.innerHTML = `<b>${anim && num ? 0 : n}</b><span>${lbl}</span>`;
    if (anim && num) countUp(c.querySelector("b"), n, 900);
    return c;
  };
  stats.appendChild(mk(k.runs, "הרצות", true));
  stats.appendChild(mk(k.total_signatures, "סוגי ממצאים", true));
  stats.appendChild(mk(`${d.tools.installed}/${d.tools.total}`, "כלים מותקנים", false));

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
    const card = el("div", "feed-card" + (a.type === "purple" ? " purple" : a.type === "login" ? " login" : ""));
    const head = el("div", "feed-head");
    const icon = a.type === "purple" ? "🟣" : a.type === "login" ? "🔑" : "🤖";
    head.appendChild(el("span", null, `${icon} ${a.intent || "משימה"}`));
    head.appendChild(el("span", "feed-when", relTime(a.ts) || a.when));
    card.appendChild(head);
    const body = el("div", "feed-body");
    if (a.type === "login") {
      body.innerHTML = `<span class="tag">👤 ${escapeHtml(a.target || a.user || "")}</span>`;
    } else if (a.type === "purple") {
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
    if (a.type !== "login") {
      const actions = el("div", "feed-actions");
      if (a.id) {
        const rep = el("button", "feed-btn", "📄 דוח");
        rep.onclick = (e) => { e.stopPropagation(); openSavedReport(a.id); };
        actions.appendChild(rep);
      }
      const rerun = el("button", "feed-btn run", "▶ הרץ שוב");
      rerun.onclick = (e) => { e.stopPropagation(); rerunActivity(a); };
      actions.appendChild(rerun);
      card.appendChild(actions);
    }
    feed.appendChild(card);
  });
}

async function openSavedReport(id) {
  try {
    const res = await fetch("/api/report/" + encodeURIComponent(id));
    const d = await res.json();
    if (!res.ok || !d.report) return;
    REPORT_MD = d.report;
    const meta = d.meta || {};
    REPORT_META = { intent: meta.intent, target: meta.target, type: meta.kind || "mission" };
    showReport();
  } catch (e) { /* ignore */ }
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
  if (t.sigma) html += `<h4>🔎 חוק Sigma (SIEM / לוגים)</h4><pre>${escapeHtml(t.sigma)}</pre>`;
  if (t.suricata) html += `<h4>🔎 חוק Suricata (IDS רשת)</h4><pre>${escapeHtml(t.suricata)}</pre>`;

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

  // 🔧 remediation (fixer agent) — offer an automated fix if one exists
  try {
    const fx = await (await fetch("/api/fix/" + encodeURIComponent(sig))).json();
    if (fx.available && CAN.fix) {
      const box = el("div", "fix-box");
      box.appendChild(el("h4", null, "🔧 תיקון אוטומטי (סוכן מתקן)"));
      const riskLabel = { safe: "🟢 בטוח", caution: "🟠 זהירות" }[fx.risk] || fx.risk;
      box.appendChild(el("div", "fix-meta", `${fx.title} · ${riskLabel}`));
      if (fx.note) box.appendChild(el("div", "fix-note", fx.note));
      const btn = el("button", "run-btn", "🔧 החל תיקון (דורש אישור)");
      btn.onclick = () => applyFix(sig, fx);
      box.appendChild(btn);
      body.appendChild(box);
    }
  } catch (e) { /* ignore */ }
}

async function applyFix(sig, fx) {
  const cmds = (fx.commands || []).map(c => escapeHtml(c)).join("\n");
  const ok = await askConfirm(
    "אישור תיקון",
    `להחיל את התיקון <b>${escapeHtml(fx.title)}</b> על השרת הזה?<br>` +
    `רמת סיכון: ${fx.risk === "safe" ? "🟢 בטוח" : "🟠 זהירות"}<br>` +
    `<pre style="text-align:left;direction:ltr;white-space:pre-wrap">${cmds}</pre>` +
    `⚠️ הפעולה תרוץ על המערכת (עם גיבוי אוטומטי של קונפיגים).`,
    "🔧 החל תיקון");
  if (!ok) return;
  const r = await fetch("/api/fix", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ signature: sig, confirm: true })
  });
  const d = await r.json();
  if (!r.ok) { alert(d.error || "שגיאה"); return; }
  const out = el("pre", "mstep-out");
  out.textContent = "מריץ תיקון...";
  $("threatBody").appendChild(out);
  const jid = d.job_id;
  const poll = async () => {
    const j = await (await fetch("/api/job/" + jid)).json();
    out.textContent = stripAnsi(j.output || "") || "מריץ...";
    if (j.status === "running" || j.status === "starting") { setTimeout(poll, 1000); }
    else { out.textContent += "\n\n" + (j.status === "done" ? "✅ התיקון הושלם" : "⚠️ הסתיים: " + j.status); }
  };
  poll();
}

/* ================= PURPLE TEAM (Red -> Broker -> Blue -> Orchestrator) ===== */
let PURPLE_ID = null;
let PURPLE_TIMER = null;

async function runPurple(intent, target, steps) {
  const res = await fetch("/api/purple", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ intent, target, steps })
  });
  const data = await res.json();
  if (!res.ok) { alert(data.error || "שגיאה"); return false; }
  PURPLE_ID = data.purple_id;
  $("purpleMeta").innerHTML =
    `<span class="pill">${escapeHtml(intent)}</span><span class="pill">${escapeHtml(target)}</span>`;
  $("purpleReportBtn").classList.add("hidden");
  $("purpleStopBtn").classList.remove("hidden");
  $("purpleBlue").innerHTML = '<div class="threats-empty">⏳ ממתין לממצאי הצוות האדום...</div>';
  $("purpleLearn").innerHTML = "";
  showScreen("purple");
  pollPurple();
  trackActive();
  return true;
}

async function startPurple() {
  if (!requireRun()) return;
  if (!PLAN) return;
  const included = [];
  document.querySelectorAll("#planSteps input[type=checkbox]").forEach(cb => {
    if (cb.checked) included.push(PLAN.steps[parseInt(cb.dataset.idx, 10)]);
  });
  if (!included.length) return;
  $("purpleBtn").disabled = true;
  try { await runPurple(PLAN.intent, PLAN.target, included); }
  finally { $("purpleBtn").disabled = false; }
}

// ---- reusable confirmation dialog (returns a Promise<bool>) ----
function askConfirm(title, msg, okLabel) {
  return new Promise(resolve => {
    $("confirmTitle").textContent = title;
    $("confirmMsg").innerHTML = msg;
    $("confirmOk").textContent = okLabel || "הרץ";
    const modal = $("confirmModal");
    modal.classList.remove("hidden");
    const done = (v) => { modal.classList.add("hidden"); $("confirmOk").onclick = null; $("confirmCancel").onclick = null; resolve(v); };
    $("confirmOk").onclick = () => done(true);
    $("confirmCancel").onclick = () => done(false);
    modal.onclick = (e) => { if (e.target === modal) done(false); };
  });
}

// Re-run an intent/target as mission or purple, with a confirmation first.
async function rerunRun(intent, target, type) {
  const kind = type === "purple" ? "משימת Purple (אדום+כחול)" : "משימה";
  const ok = await askConfirm(
    "הרצה חוזרת",
    `להריץ שוב ${kind}?<br><br>` +
    `<span class="pill">🎯 ${escapeHtml(target)}</span> <span class="pill">${escapeHtml(intent)}</span><br><br>` +
    `⚠️ פעולה זו מריצה <b>כלים אמיתיים</b> על המטרה ועשויה להימשך מספר דקות.`,
    "▶ הרץ שוב");
  if (!ok) return;
  try {
    const res = await fetch("/api/plan", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent, target })
    });
    const plan = await res.json();
    if (!res.ok || !plan.steps || !plan.steps.length) { alert(plan.error || "לא ניתן לתכנן מחדש"); return; }
    PLAN = plan;
    if (type === "purple") await runPurple(intent, target, plan.steps);
    else await runMission(intent, target, plan.steps);
  } catch (e) { alert("שגיאה: " + e); }
}

function rerunActivity(a) { return rerunRun(a.intent, a.target, a.type); }

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
      if (p.report) { REPORT_MD = p.report; REPORT_META = { intent: p.intent, target: p.target, type: "purple" }; $("purpleReportBtn").classList.remove("hidden"); }
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
  const box = $("reportAiSummary"); if (box) { box.classList.add("hidden"); box.innerHTML = ""; }
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
  $("reportEnhanceBtn").onclick = enhanceReport;
  $("reportCopyBtn").onclick = () => navigator.clipboard.writeText(REPORT_MD);
  $("reportDownloadBtn").onclick = downloadReport;
  $("reportRerunBtn").onclick = () => { if (REPORT_META && REPORT_META.target) rerunRun(REPORT_META.intent, REPORT_META.target, REPORT_META.type); };
  $("newMissionBtn").onclick = () => { showScreen("ai-prompt"); };
}

function init() {
  $("homeBtn").onclick = () => showScreen("picker");
  $("search").oninput = (e) => { searchTerm = e.target.value; renderGrid(); };
  document.querySelectorAll("[data-goto]").forEach(b => b.onclick = () => showScreen(b.dataset.goto));
  $("runBtn").onclick = runTool;
  $("runBarGo").onclick = runBarJump;
  $("stopBtn").onclick = stopJob;
  $("copyBtn").onclick = () => navigator.clipboard.writeText($("output").textContent);
  $("downloadBtn").onclick = download;
  $("rerunBtn").onclick = () => { if (CURRENT_TOOL) { showScreen("form"); } };
  initBrain();
  $("auditBtn").onclick = openAudit;
  $("obsidianBtn").onclick = async () => {
    const btn = $("obsidianBtn"); btn.disabled = true; btn.textContent = "📓 מייצא...";
    try {
      const d = await (await fetch("/api/obsidian/export", { method: "POST" })).json();
      if (d.ok) alert(`✅ יוצא לכספת Obsidian:\n${d.reports} דוחות · ${d.threats} איומים\n\nמיקום: ${d.vault}`);
      else alert("שגיאה: " + (d.error || "לא ידוע"));
    } catch (e) { alert("שגיאת רשת: " + e); }
    finally { btn.disabled = false; btn.textContent = "📓 ייצא ל‑Obsidian"; }
  };
  $("userAddBtn").onclick = addUser;
  $("userEmail").onkeydown = (e) => { if (e.key === "Enter") addUser(); };
  $("pbNewBtn").onclick = () => pbOpenEditor(null);
  $("learnReload").onclick = () => loadLearning();
  $("learnSearch").oninput = (e) => renderLearnList(e.target.value);
  $("histReload").onclick = () => loadHistory();
  $("histTarget").onchange = () => { HIST_SEL = []; renderHistory(); $("histCompare").classList.add("hidden"); };
  $("histCompareBtn").onclick = runCompare;
  $("histClearBtn").onclick = () => { HIST_SEL = []; renderHistory(); $("histCompare").classList.add("hidden"); };
  $("agents3dBtn").onclick = agents3dToggle;
  $("agentPanelClose").onclick = () => $("agentPanel").classList.add("hidden");
  $("vaultReloadBtn").onclick = () => loadVault();
  $("vaultMode3d").onclick = vaultToggle3d;
  $("vaultSearch").oninput = (e) => vaultSearch(e.target.value);
  window.addEventListener("resize", () => { if (GAL && !$("galaxyCanvas").classList.contains("hidden")) galaxyResize(); });
  $("vaultPanelClose").onclick = () => {
    $("vaultPanel").classList.add("hidden");
    VAULT.nodes.forEach(x => x._g.classList.remove("v-active", "v-linked"));
  };
  $("vaultExportBtn").onclick = async () => {
    const btn = $("vaultExportBtn"); btn.disabled = true; btn.textContent = "📓 מייצא...";
    try {
      const d = await (await fetch("/api/obsidian/export", { method: "POST" })).json();
      if (d.ok) alert(`✅ יוצא לכספת Obsidian:\n${d.reports} דוחות · ${d.threats} איומים\n\nמיקום: ${d.vault}`);
      else alert("שגיאה: " + (d.error || "לא ידוע"));
    } catch (e) { alert("שגיאת רשת: " + e); }
    finally { btn.disabled = false; btn.textContent = "📓 ייצא כספת"; }
  };
  $("auditClose").onclick = () => $("auditModal").classList.add("hidden");
  $("auditModal").onclick = (e) => { if (e.target === $("auditModal")) $("auditModal").classList.add("hidden"); };
  $("threatClose").onclick = () => $("threatModal").classList.add("hidden");
  $("threatModal").onclick = (e) => { if (e.target === $("threatModal")) $("threatModal").classList.add("hidden"); };
  $("installCancel").onclick = () => $("installModal").classList.add("hidden");
  $("installGo").onclick = doInstall;
  $("sudoPass").onkeydown = (e) => { if (e.key === "Enter") doInstall(); };
  initAI();
  loadCatalog();
  loadWhoami();
  loadLlmStatus();
  trackActive();   // global running-bar: re-attaches to any run already in progress
  window.addEventListener("hashchange", applyHash);
  applyHash();
}

let IS_ADMIN = false;
async function loadWhoami() {
  try {
    const d = await (await fetch("/api/whoami")).json();
    IS_ADMIN = !!d.is_admin;
    CURRENT_ROLE = d.role || "operator";
    CAN = { run: (d.can || []).includes("run"), fix: (d.can || []).includes("fix") };
    if (d.user && d.user !== "local") $("userLine").textContent = "👤 " + d.user + " · " + roleLabel(CURRENT_ROLE);
    $("modeUsers").classList.toggle("hidden", !IS_ADMIN);
    $("modePlaybooks").classList.toggle("hidden", !IS_ADMIN);
    applyPermissions();
  } catch (e) { /* ignore */ }
}

let CURRENT_ROLE = "operator";
let CAN = { run: true, fix: true };
function roleLabel(r) { return { admin: "🛡️ מנהל", operator: "⚙️ מפעיל", viewer: "👁️ צופה" }[r] || r; }
function requireRun() {
  if (CAN.run) return true;
  alert(`אין לך הרשאת הרצה (תפקיד: ${roleLabel(CURRENT_ROLE)}). פנה למנהל לשדרוג ההרשאה.`);
  return false;
}
function applyPermissions() {
  // read-only banner for viewers on the tool/AI screens; buttons still gated in JS + server
  const ban = $("roBanner");
  if (ban) ban.classList.toggle("hidden", CAN.run);
  ["runBtn", "planBtn", "missionBtn", "purpleBtn"].forEach(id => {
    const b = $(id);
    if (b && !CAN.run) { b.disabled = true; b.title = "נדרשת הרשאת הרצה"; }
  });
}

/* ============================================================ LOCAL LLM (Ollama)
   Optional: if a local model is configured & reachable, reports get an AI prose
   summary. Shows status on the AI screen and an on-demand "enhance" button. */
let LLM_ON = false;
async function loadLlmStatus() {
  try {
    const d = await (await fetch("/api/llm")).json();
    LLM_ON = !!(d.configured && d.reachable);
    const badge = $("llmBadge");
    if (LLM_ON) {
      badge.textContent = `🧠 מנוע AI: ${d.model} · פעיל`;
      badge.className = "llm-badge on";
      badge.title = "דוחות ינוסחו אוטומטית ע\"י המודל המקומי";
    } else if (d.configured) {
      badge.textContent = "🧠 מנוע AI מוגדר אך לא נגיש — מבוסס חוקים";
      badge.className = "llm-badge warn";
      badge.title = "שרת Ollama לא מגיב ב‑" + (d.url || "");
    } else {
      badge.textContent = "⚙️ מבוסס חוקים · לניסוח AI חכם הגדר Ollama";
      badge.className = "llm-badge off";
      badge.title = "הגדר OLLAMA_URL + OLLAMA_MODEL לשדרוג ניסוח הדוחות";
    }
    // AI-planning checkbox — only usable when the LLM is actually available
    const cb = $("aiPlanLLM"), st = $("aiPlanStatus");
    if (cb) {
      cb.disabled = !LLM_ON;
      if (!LLM_ON) cb.checked = false;
    }
    if (st) st.textContent = LLM_ON ? "· זמין" : "· דורש Ollama פעיל";
  } catch (e) { /* ignore */ }
}

async function enhanceReport() {
  const box = $("reportAiSummary"), btn = $("reportEnhanceBtn");
  btn.disabled = true; btn.textContent = "🧠 מנסח...";
  try {
    const meta = REPORT_META || {};
    const d = await (await fetch("/api/llm/enhance", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report: REPORT_MD, intent: meta.intent, target: meta.target })
    })).json();
    if (d.error) { alert(d.error); return; }
    box.innerHTML = `<div class="ai-summary-head">🧠 תקציר AI · ${escapeHtml(d.model || "")}</div>` + mdToHtml(d.summary);
    box.classList.remove("hidden");
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) { alert("שגיאת רשת: " + e); }
  finally { btn.disabled = false; btn.textContent = "🧠 שפר עם AI"; }
}

/* ============================================================ LEARNING MATERIALS
   What the system learned + how it handles each threat, as an educational Q&A. */
let LEARN_ITEMS = [];

async function loadLearning() {
  const list = $("learnList");
  list.innerHTML = '<div class="audit-empty">טוען...</div>';
  try {
    const d = await (await fetch("/api/learning")).json();
    LEARN_ITEMS = d.items || [];
    renderLearnStats(d);
    renderLearnList("");
  } catch (e) { list.innerHTML = '<div class="audit-empty">שגיאה בטעינה.</div>'; }
}

function renderLearnStats(d) {
  const sc = d.severity || {};
  $("learnStats").innerHTML =
    `<div class="lstat"><b>${d.runs || 0}</b><span>הרצות</span></div>` +
    `<div class="lstat"><b>${d.learned || 0}/${d.total_types || 0}</b><span>סוגי איומים שנלמדו</span></div>` +
    `<div class="lstat crit"><b>${sc.critical || 0}</b><span>קריטי</span></div>` +
    `<div class="lstat high"><b>${sc.high || 0}</b><span>גבוה</span></div>` +
    `<div class="lstat med"><b>${sc.medium || 0}</b><span>בינוני</span></div>` +
    `<div class="lstat low"><b>${sc.low || 0}</b><span>נמוך</span></div>`;
}

function renderLearnList(term) {
  term = (term || "").trim().toLowerCase();
  const list = $("learnList");
  list.innerHTML = "";
  const items = LEARN_ITEMS.filter(it => !term ||
    it.name.toLowerCase().includes(term) || (it.threat || "").toLowerCase().includes(term) ||
    (it.mitre || "").toLowerCase().includes(term));
  if (!items.length) { list.innerHTML = '<div class="audit-empty">לא נמצאו איומים תואמים.</div>'; return; }
  items.forEach(it => list.appendChild(learnCard(it)));
}

function learnCard(it) {
  const card = el("div", "learn-card " + it.severity);
  const head = el("button", "learn-head");
  head.innerHTML =
    `<span class="learn-sev">${SEV_ICON[it.severity] || ""}</span>` +
    `<span class="learn-name">${escapeHtml(it.name)}</span>` +
    (it.learned
      ? `<span class="learn-badge learned">נלמד · נצפה ${it.seen}×</span>`
      : `<span class="learn-badge new">טרם נצפה</span>`) +
    `<span class="learn-toggle">▾</span>`;
  const body = el("div", "learn-body hidden");
  const list = (arr) => "<ul>" + (arr || []).map(x => `<li>${escapeHtml(x)}</li>`).join("") + "</ul>";
  let html = "";
  html += `<div class="qa"><div class="q">❓ מה זה ולמה זה מסוכן?</div><div class="a">${escapeHtml(it.threat)}</div></div>`;
  html += `<div class="qa"><div class="q">🛡️ איך מתגוננים?</div><div class="a">${list(it.defenses)}</div></div>`;
  html += `<div class="qa"><div class="q">👁️ איך מזהים?</div><div class="a">${list(it.detections)}`;
  if (it.sigma) html += `<div class="qa-sub">חוק Sigma (SIEM):</div><pre>${escapeHtml(it.sigma)}</pre>`;
  if (it.suricata) html += `<div class="qa-sub">חוק Suricata (IDS):</div><pre>${escapeHtml(it.suricata)}</pre>`;
  html += `</div></div>`;
  if (it.config) html += `<div class="qa"><div class="q">⚙️ תצורה לדוגמה</div><div class="a"><pre>${escapeHtml(it.config)}</pre></div></div>`;
  html += `<div class="qa"><div class="q">🔧 יש תיקון אוטומטי?</div><div class="a">` +
    (it.fix && it.fix.available
      ? `כן — <b>${escapeHtml(it.fix.title)}</b> (${it.fix.risk === "safe" ? "🟢 בטוח" : "🟠 זהירות"}). ${escapeHtml(it.fix.note || "")}`
      : `לא — נדרש טיפול ידני (ראה הגנות ותצורה למעלה).`) + `</div></div>`;
  if (it.mitre) html += `<div class="qa"><div class="q">🎯 MITRE ATT&CK</div><div class="a"><span class="mitre">${escapeHtml(it.mitre)}</span></div></div>`;
  html += `<div class="qa"><div class="q">📊 מה המערכת למדה על זה?</div><div class="a">` +
    (it.learned
      ? `נצפה <b>${it.seen}</b> פעמים · ראשון: ${escapeHtml(it.first_seen || "?")} · אחרון: ${escapeHtml(it.last_seen || "?")}`
      : `טרם נצפה בהרצות. כשיופיע בבדיקה — המערכת תלמד אותו אוטומטית ותתחיל לספור.`) + `</div></div>`;
  body.innerHTML = html;
  head.onclick = () => { body.classList.toggle("hidden"); head.classList.toggle("open"); };
  card.appendChild(head); card.appendChild(body);
  return card;
}

/* ============================================================ PLAYBOOK EDITOR
   Admin-only: add/edit data-driven playbooks (agent rules) without touching code. */
let PB_LIST = [];

async function loadPlaybooks() {
  const list = $("pbList");
  list.innerHTML = '<div class="audit-empty">טוען...</div>';
  $("pbEditor").classList.add("hidden");
  try {
    const d = await (await fetch("/api/playbooks")).json();
    PB_LIST = d.playbooks || [];
    renderPbList();
  } catch (e) { list.innerHTML = '<div class="audit-empty">שגיאה בטעינה.</div>'; }
}

function renderPbList() {
  const list = $("pbList");
  list.innerHTML = "";
  PB_LIST.forEach(pb => {
    const card = el("div", "pb-card" + (pb.builtin ? " builtin" : ""));
    const head = el("div", "pb-head");
    head.innerHTML = `<span class="pb-name">${escapeHtml(pb.name)}</span>` +
      `<span class="pb-badge ${pb.builtin ? "b" : "c"}">${pb.builtin ? "מובנה" : "מותאם"}</span>` +
      `<code class="pb-id">${escapeHtml(pb.id)}</code>`;
    card.appendChild(head);
    const kw = el("div", "pb-kw");
    kw.innerHTML = (pb.keywords || []).map(k => `<span class="tag">${escapeHtml(k)}</span>`).join("");
    card.appendChild(kw);
    const steps = el("div", "pb-steps-preview");
    steps.innerHTML = (pb.steps || []).map((s, i) =>
      `<span class="pb-step-chip">${i + 1}. ${escapeHtml(s.tool_id)}</span>`).join(" ← ");
    card.appendChild(steps);
    if (!pb.builtin) {
      const actions = el("div", "pb-actions");
      const ed = el("button", "ghost-btn", "✏️ ערוך"); ed.onclick = () => pbOpenEditor(pb);
      const del = el("button", "ghost-btn danger-btn", "🗑️ מחק"); del.onclick = () => pbDelete(pb);
      actions.appendChild(ed); actions.appendChild(del);
      card.appendChild(actions);
    }
    list.appendChild(card);
  });
}

function pbOpenEditor(pb) {
  const ed = $("pbEditor");
  ed.classList.remove("hidden");
  const editing = !!pb;
  pb = pb || { id: "", name: "", keywords: [], steps: [] };
  ed.innerHTML =
    `<h3>${editing ? "✏️ עריכת Playbook" : "➕ Playbook חדש"}</h3>` +
    `<div class="pb-field"><label>מזהה (id — אנגלית/ספרות/מקף)</label><input id="pbId" class="vault-search" placeholder="my_recon" value="${escapeHtml(pb.id)}" ${editing ? "readonly" : ""}></div>` +
    `<div class="pb-field"><label>שם</label><input id="pbName" class="vault-search" placeholder="הסריקה שלי" value="${escapeHtml(pb.name)}"></div>` +
    `<div class="pb-field"><label>מילות מפתח (מופרדות בפסיק) — הסוכן יבחר את ה‑playbook כשהן מופיעות בכוונה</label>` +
      `<input id="pbKw" class="vault-search" placeholder="recon, סריקה, my scan" value="${escapeHtml((pb.keywords || []).join(", "))}"></div>` +
    `<label class="pb-steps-label">שלבים (הסוכן יריץ בסדר זה):</label>` +
    `<div id="pbSteps" class="pb-steps"></div>` +
    `<button id="pbAddStep" class="ghost-btn">➕ הוסף שלב</button>` +
    `<div class="pb-ph-hint">מצייני מקום זמינים בערכים: <code>{target}</code> <code>{host}</code> <code>{url}</code> <code>{domain}</code> — יוחלפו במטרה בזמן הריצה.</div>` +
    `<div class="modal-actions"><button id="pbCancel" class="ghost-btn">ביטול</button><button id="pbSave" class="run-btn">💾 שמור</button></div>`;
  const list = (pb.steps && pb.steps.length) ? pb.steps : [{}];
  list.forEach(s => pbAddStepRow(s));
  $("pbAddStep").onclick = () => pbAddStepRow({});
  $("pbCancel").onclick = () => ed.classList.add("hidden");
  $("pbSave").onclick = pbSave;
  ed.scrollIntoView({ behavior: "smooth", block: "start" });
}

function pbAddStepRow(s) {
  s = s || {};
  const box = $("pbSteps");
  const row = el("div", "pb-step-row");
  const toolSel = el("select", "vault-search pb-tool");
  toolSel.innerHTML = (CATALOG ? CATALOG.tools : []).map(t =>
    `<option value="${t.id}">${escapeHtml(t.name)} (${t.id})</option>`).join("");
  if (s.tool_id) toolSel.value = s.tool_id;
  const why = el("input", "vault-search pb-why"); why.placeholder = "למה השלב (הסבר קצר)"; why.value = s.why || "";
  const vals = el("input", "vault-search pb-vals"); vals.placeholder = "ערכים: target={host}; sv=true"; vals.value = valuesToStr(s.values);
  const rm = el("button", "ghost-btn danger-btn", "🗑️"); rm.onclick = () => row.remove();
  row.appendChild(toolSel); row.appendChild(why); row.appendChild(vals); row.appendChild(rm);
  box.appendChild(row);
}

function valuesToStr(o) {
  return Object.entries(o || {}).map(([k, v]) => `${k}=${v}`).join("; ");
}
function parseValues(str) {
  const o = {};
  (str || "").split(";").forEach(part => {
    const i = part.indexOf("=");
    if (i < 0) return;
    const k = part.slice(0, i).trim(); let v = part.slice(i + 1).trim();
    if (!k) return;
    if (v === "true") v = true; else if (v === "false") v = false;
    o[k] = v;
  });
  return o;
}

async function pbSave() {
  const steps = [...document.querySelectorAll("#pbSteps .pb-step-row")].map(r => ({
    tool_id: r.querySelector(".pb-tool").value,
    why: r.querySelector(".pb-why").value.trim(),
    values: parseValues(r.querySelector(".pb-vals").value),
  }));
  const pb = {
    id: $("pbId").value.trim(),
    name: $("pbName").value.trim(),
    keywords: $("pbKw").value.split(",").map(s => s.trim()).filter(Boolean),
    steps,
  };
  try {
    const d = await (await fetch("/api/playbooks/save", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(pb)
    })).json();
    if (d.error) { pbMsg(d.error, false); return; }
    pbMsg("✅ נשמר. הסוכן ישתמש ב‑playbook הזה בתכנון הבא.", true);
    $("pbEditor").classList.add("hidden");
    loadPlaybooks();
  } catch (e) { pbMsg("שגיאת רשת: " + e, false); }
}

async function pbDelete(pb) {
  if (!confirm(`למחוק את ה‑playbook "${pb.name}"?`)) return;
  try {
    const d = await (await fetch("/api/playbooks/delete", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: pb.id })
    })).json();
    if (d.error) { pbMsg(d.error, false); return; }
    pbMsg("🗑️ נמחק.", true);
    loadPlaybooks();
  } catch (e) { pbMsg("שגיאת רשת: " + e, false); }
}

function pbMsg(text, ok) {
  const m = $("pbMsg"); m.textContent = text; m.className = "users-msg " + (ok ? "ok" : "err");
  setTimeout(() => { m.textContent = ""; m.className = "users-msg"; }, 4500);
}

/* ============================================================ HISTORY + COMPARE
   All past scans, with a two-scan comparison that shows the security-posture
   trend over time (what was resolved / added / still open). */
let HIST_RUNS = [];
let HIST_SEL = [];   // selected purple-run ids to compare (max 2)

async function loadHistory() {
  const list = $("histList");
  list.innerHTML = '<div class="audit-empty">טוען...</div>';
  $("histCompare").classList.add("hidden");
  try {
    const d = await (await fetch("/api/history")).json();
    HIST_RUNS = d.runs || [];
    HIST_SEL = [];
    renderHistory();
  } catch (e) { list.innerHTML = '<div class="audit-empty">שגיאה בטעינה.</div>'; }
}

function renderHistory() {
  const list = $("histList"), empty = $("histEmpty"), sel = $("histTarget");
  const targets = [...new Set(HIST_RUNS.map(r => r.target).filter(Boolean))];
  const cur = sel.value || "";
  sel.innerHTML = '<option value="">כל המטרות</option>' +
    targets.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("");
  sel.value = cur;
  const rows = HIST_RUNS.filter(r => !cur || r.target === cur);

  list.innerHTML = "";
  empty.classList.toggle("hidden", rows.length > 0);
  rows.forEach(r => {
    const isPurple = r.type === "purple";
    const row = el("div", "hist-row" + (isPurple ? " purple" : "") + (HIST_SEL.includes(r.id) ? " sel" : ""));
    if (isPurple) {
      const cb = el("input"); cb.type = "checkbox"; cb.className = "hist-cb";
      cb.checked = HIST_SEL.includes(r.id);
      cb.title = "בחר להשוואה";
      cb.onchange = () => toggleHistSel(r.id, cb.checked);
      row.appendChild(cb);
    } else {
      row.appendChild(el("span", "hist-cb-na", "·"));
    }
    const info = el("div", "hist-info");
    const icon = isPurple ? "🟣" : "🤖";
    const count = isPurple ? `🔵 ${r.threats || 0} איומים` : `🔎 ${r.findings || 0} ממצאים`;
    info.innerHTML = `<div class="hist-title">${icon} ${escapeHtml(r.intent || "בדיקה")}</div>` +
      `<div class="hist-meta"><span class="tag">🎯 ${escapeHtml(r.target || "")}</span>` +
      `<span class="tag">${count}</span>` +
      (r.severity ? `<span class="tag">${SEV_ICON[r.severity] || ""} ${SEV_HE[r.severity] || r.severity}</span>` : "") +
      `<span class="hist-when">${r.ts ? relTime(r.ts) : escapeHtml(r.when || "")}</span></div>`;
    row.appendChild(info);
    if (r.id) {
      const rep = el("button", "feed-btn", "📄 דוח");
      rep.onclick = () => openSavedReport(r.id);
      row.appendChild(rep);
    }
    list.appendChild(row);
  });
  updateHistBar();
}

function toggleHistSel(id, on) {
  if (on) {
    if (!HIST_SEL.includes(id)) HIST_SEL.push(id);
    while (HIST_SEL.length > 2) HIST_SEL.shift();  // keep the most recent 2
  } else {
    HIST_SEL = HIST_SEL.filter(x => x !== id);
  }
  renderHistory();
}

function updateHistBar() {
  const bar = $("histCompareBar"), info = $("histSelInfo"), btn = $("histCompareBtn");
  bar.classList.toggle("hidden", HIST_SEL.length === 0);
  info.textContent = `${HIST_SEL.length}/2 סריקות נבחרו להשוואה`;
  btn.disabled = HIST_SEL.length !== 2;
}

async function runCompare() {
  if (HIST_SEL.length !== 2) return;
  const [a, b] = HIST_SEL;
  const box = $("histCompare");
  box.classList.remove("hidden");
  box.innerHTML = '<p style="color:var(--text-dim)">משווה...</p>';
  try {
    const d = await (await fetch(`/api/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`)).json();
    if (d.error) { box.innerHTML = `<p>${escapeHtml(d.error)}</p>`; return; }
    renderCompare(d);
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) { box.innerHTML = "<p>שגיאת רשת</p>"; }
}

function renderCompare(d) {
  const box = $("histCompare");
  const chips = (arr) => arr.length
    ? arr.map(x => `<span class="cmp-chip ${x.severity}">${SEV_ICON[x.severity] || ""} ${escapeHtml(x.name)}</span>`).join("")
    : '<span class="cmp-none">אין</span>';
  const same = d.a.target === d.b.target;
  box.innerHTML =
    `<div class="cmp-head"><h2>🔀 השוואת סריקות${same ? " · 🎯 " + escapeHtml(d.a.target) : ""}</h2></div>` +
    (!same ? `<div class="cmp-warn">⚠️ הסריקות הן של מטרות שונות — ההשוואה פחות משמעותית.</div>` : "") +
    `<div class="cmp-ab">` +
      `<div class="cmp-col"><div class="cmp-lbl">בסיס (ישן)</div><div class="cmp-when">${escapeHtml(d.a.when || "")}</div><div class="cmp-cnt">${d.a.count} איומים</div></div>` +
      `<div class="cmp-arrow">→</div>` +
      `<div class="cmp-col"><div class="cmp-lbl">נוכחי (חדש)</div><div class="cmp-when">${escapeHtml(d.b.when || "")}</div><div class="cmp-cnt">${d.b.count} איומים</div></div>` +
    `</div>` +
    `<div class="cmp-grid">` +
      `<div class="cmp-cell resolved"><h4>✅ נפתרו (${d.resolved.length})</h4><div class="cmp-chips">${chips(d.resolved)}</div></div>` +
      `<div class="cmp-cell added"><h4>🆕 חדשים (${d.added.length})</h4><div class="cmp-chips">${chips(d.added)}</div></div>` +
      `<div class="cmp-cell persist"><h4>⚠️ עדיין פתוחים (${d.persisting.length})</h4><div class="cmp-chips">${chips(d.persisting)}</div></div>` +
    `</div>` +
    `<div class="cmp-verdict ${cmpTrend(d)}">${cmpVerdict(d)}</div>`;
}

function cmpTrend(d) {
  const net = d.resolved.length - d.added.length;
  return net > 0 ? "good" : net < 0 ? "bad" : "flat";
}
function cmpVerdict(d) {
  const net = d.resolved.length - d.added.length;
  if (net > 0) return `🟢 שיפור: נפתרו ${d.resolved.length} איומים ונוספו ${d.added.length}. מגמת אבטחה חיובית.`;
  if (net < 0) return `🔴 הרעה: נוספו ${d.added.length} איומים חדשים לעומת ${d.resolved.length} שנפתרו — דורש טיפול.`;
  return `🟡 יציב: ${d.persisting.length} איומים עדיין פתוחים; אין שינוי נטו.`;
}

/* ============================================================ USER MANAGEMENT
   Admin-only screen to manage the Google-login allowlist (oauth2-proxy). */
let ROLE_OPTS = ["admin", "operator", "viewer"];
async function loadUsers() {
  const list = $("usersList");
  list.innerHTML = '<div class="audit-empty">טוען...</div>';
  try {
    const [d, r] = await Promise.all([
      (await fetch("/api/users")).json(),
      (await fetch("/api/roles")).json(),
    ]);
    if (d.error) { list.innerHTML = `<div class="audit-empty">${d.error}</div>`; return; }
    const roleMap = {};
    (r.users || []).forEach(x => { roleMap[x.email] = x.role; });
    if (r.roles) ROLE_OPTS = r.roles;
    renderUsers(d, roleMap);
  } catch (e) { list.innerHTML = '<div class="audit-empty">שגיאה בטעינה.</div>'; }
}

function renderUsers(d, roleMap) {
  const emails = d.emails || [];
  $("usersCount").textContent = emails.length;
  $("usersSelf").textContent = d.self && d.self !== "local" ? "👤 " + d.self : "";
  const list = $("usersList");
  list.innerHTML = "";
  if (!emails.length) {
    list.innerHTML = '<div class="audit-empty">אין עדיין משתמשים מורשים.</div>';
    return;
  }
  emails.forEach(email => {
    const row = el("div", "user-row");
    const isAdmin = d.admin && email === d.admin;
    const left = el("div", "user-info");
    left.innerHTML = `<span class="user-mail">${email}</span>` +
      (isAdmin ? '<span class="user-badge admin">אדמין ראשי</span>' : '<span class="user-badge">מורשה</span>');
    row.appendChild(left);
    if (isAdmin) {
      row.appendChild(el("span", "user-locked", "🔒 מנהל (נעול)"));
    } else {
      // role selector
      const sel = el("select", "vault-search user-role");
      sel.innerHTML = ROLE_OPTS.map(r =>
        `<option value="${r}">${roleLabel(r)}</option>`).join("");
      sel.value = (roleMap && roleMap[email]) || "operator";
      sel.onchange = () => setUserRole(email, sel.value);
      row.appendChild(sel);
      const rm = el("button", "ghost-btn danger-btn", "🗑️ הסר");
      rm.onclick = () => removeUser(email);
      row.appendChild(rm);
    }
    list.appendChild(row);
  });
}

async function setUserRole(email, role) {
  try {
    const d = await (await fetch("/api/roles/set", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, role })
    })).json();
    if (d.error) { usersMsg(d.error, false); loadUsers(); return; }
    usersMsg(`✅ ${email} → ${roleLabel(role)}`, true);
  } catch (e) { usersMsg("שגיאת רשת: " + e, false); }
}

function usersMsg(text, ok) {
  const m = $("usersMsg");
  m.textContent = text;
  m.className = "users-msg " + (ok ? "ok" : "err");
  setTimeout(() => { m.textContent = ""; m.className = "users-msg"; }, 4000);
}

async function addUser() {
  const inp = $("userEmail");
  const email = (inp.value || "").trim().toLowerCase();
  if (!email) return;
  try {
    const d = await (await fetch("/api/users/add", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email })
    })).json();
    if (d.error) { usersMsg(d.error, false); return; }
    inp.value = "";
    usersMsg(`✅ ${email} — ${d.note || "נוסף"}. ייכנס לתוקף תוך שניות.`, true);
    renderUsers(d);
  } catch (e) { usersMsg("שגיאת רשת: " + e, false); }
}

async function removeUser(email) {
  if (!confirm(`להסיר את ${email} מרשימת המורשים?\nהוא לא יוכל להיכנס יותר.`)) return;
  try {
    const d = await (await fetch("/api/users/remove", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email })
    })).json();
    if (d.error) { usersMsg(d.error, false); return; }
    usersMsg(`🗑️ ${email} הוסר.`, true);
    renderUsers(d);
  } catch (e) { usersMsg("שגיאת רשת: " + e, false); }
}

// Deep-linking: #dashboard, #ai, #tools, #vault, #brain-<agentId>
async function applyHash() {
  const h = (location.hash || "").replace(/^#/, "");
  if (!h) return;
  if (h === "dashboard") { showScreen("dashboard"); }
  else if (h === "agents3d") {
    showScreen("dashboard");
    setTimeout(() => { if (!AGENTS3D_ON) agents3dToggle(); }, 500);
  }
  else if (h === "ai") { showScreen("ai-prompt"); }
  else if (h === "tools") { showScreen("picker"); }
  else if (h === "vault" || h === "obsidian") { showScreen("vault"); }
  else if (h === "galaxy") {
    VAULT_MODE = "3d";
    $("vaultMode3d").textContent = "🕸️ גרף 2D";
    $("vaultHint").textContent = "🖱️ גרור לסיבוב הגלקסיה · גלגל לטוס פנימה/החוצה · גרור כוכב להזזה · לחץ כוכב לפתיחת הפתק";
    showScreen("vault");
  }
  else if (h === "history") { showScreen("history"); }
  else if (h === "learning") { showScreen("learning"); }
  else if (h === "playbooks") { showScreen("playbooks"); }
  else if (h === "users") { showScreen("users"); }
  else if (h.startsWith("tool-")) {
    const id = h.slice(5);
    let tries = 0;
    const openIt = () => {
      const t = CATALOG && CATALOG.tools.find(x => x.id === id);
      if (t) { openForm(t); showScreen("form"); }
      else if (tries++ < 30) setTimeout(openIt, 150);
    };
    openIt();
  }
  else if (h.startsWith("brain-")) { await openBrain(h.slice(6)); }
}

/* ================================================================ OBSIDIAN
   In-app graphical "Graph View" of the Obsidian vault: a force-directed graph
   of reports <-> threats <-> MOC, drawn as SVG. No external libraries. */
const VNS = "http://www.w3.org/2000/svg";
const VW = 1000, VH = 700;
let VAULT = { nodes: [], edges: [] };
let vaultView = { scale: 1, tx: 0, ty: 0 };

function vEl(tag, attrs) {
  const e = document.createElementNS(VNS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

let VAULT_MODE = "2d";      // "2d" (SVG graph) | "3d" (canvas galaxy)
let VAULT_GRAPH = null;     // last-loaded {nodes, links}

async function loadVault() {
  $("vaultPanel").classList.add("hidden");
  try {
    const g = await (await fetch("/api/vault/graph")).json();
    VAULT_GRAPH = { nodes: g.nodes || [], links: g.links || [] };
    $("vlReports").textContent = g.counts ? g.counts.reports : 0;
    $("vlThreats").textContent = g.counts ? g.counts.threats : 0;
    renderVault();
  } catch (e) {
    $("vaultEmpty").textContent = "שגיאה בטעינת הגרף: " + e;
    $("vaultEmpty").classList.remove("hidden");
  }
}

function renderVault() {
  const empty = $("vaultEmpty"), svg = $("vaultSvg"), canvas = $("galaxyCanvas");
  const g = VAULT_GRAPH || { nodes: [], links: [] };
  const has = g.nodes.some(n => n.type !== "moc");
  if (!has) {
    empty.classList.remove("hidden");
    svg.classList.add("hidden"); canvas.classList.add("hidden");
    galaxyStop();
    return;
  }
  empty.classList.add("hidden");
  if (VAULT_MODE === "3d") {
    galaxyStop();
    svg.classList.add("hidden"); svg.innerHTML = "";
    canvas.classList.remove("hidden");
    galaxyBuild(g.nodes, g.links);
  } else {
    galaxyStop();
    canvas.classList.add("hidden");
    svg.classList.remove("hidden");
    vaultLayout(g.nodes, g.links);
    vaultRender(g.nodes, g.links);
  }
}

function vaultToggle3d() {
  VAULT_MODE = VAULT_MODE === "3d" ? "2d" : "3d";
  $("vaultMode3d").textContent = VAULT_MODE === "3d" ? "🕸️ גרף 2D" : "🌌 גלקסיה 3D";
  $("vaultHint").textContent = VAULT_MODE === "3d"
    ? "🖱️ גרור לסיבוב הגלקסיה · גלגל לטוס פנימה/החוצה · גרור כוכב להזזה · לחץ כוכב לפתיחת הפתק"
    : "🖱️ גרור צומת · גלגל להתקרב · לחץ צומת לפתיחת הפתק";
  $("vaultPanel").classList.add("hidden");
  renderVault();
}

/* ====================================================== 3D AGENTS CONSTELLATION
   The dashboard agents as a rotating 3D star constellation; click a star for an
   explanation. Reuses the pure-canvas 3D projection (galProject). */
let DASH_AGENTS = [];
let DASH_ANIMATE = false;
let AGENTS3D_ON = false;
let AGX = null;

const AGENT_INFO = {
  red:    { color: [248, 81, 73], title: "צוות אדום (Executor)",
    text: "מנוע התקיפה. מריץ את כלי ה‑Kali על המטרה ומפיק ממצאים גולמיים — פורטים פתוחים, שירותים, גרסאות וחולשות. זהו ה‑Executor שמזין את כל שאר הסוכנים בנתוני אמת." },
  broker: { color: [63, 185, 80], title: "מתווך (Broker)",
    text: "הגשר בין תקיפה להגנה. לוקח כל ממצא אדום, ממפה אותו לכלל הגנה מתוך בסיס הידע, מאחד כפילויות ומדרג את האיומים לפי חומרה." },
  blue:   { color: [47, 129, 247], title: "צוות כחול (Blue Team)",
    text: "מפיק לכל איום תוכנית הגנה מלאה: פעולות הקשחה, חוקי זיהוי מוכנים (Sigma ל‑SIEM + Suricata ל‑IDS), שיוך MITRE ATT&CK ותצורה לדוגמה." },
  learn:  { color: [210, 153, 34], title: "למידה מתמשכת (Learning)",
    text: "מנרמל כל ממצא לחתימה (signature) וצובר אותו במסד הנתונים עם מונה הופעות ותאריכים. כך הכיסוי ההגנתי גדל והמערכת 'לומדת' אילו איומים חוזרים לאורך זמן." },
  orch:   { color: [168, 85, 247], title: "מתזמר (Orchestrator)",
    text: "מנצח על כל הזרימה: מריץ את הצוות האדום, מפעיל את המתווך והכחול, מעדכן את הלמידה, ומפיק את דוח ה‑Purple המלא. אם מוגדר LLM — מוסיף תקציר AI." },
  fix:    { color: [124, 196, 255], title: "סוכן מתקן (Remediation)",
    text: "מיישם בפועל את הגנות הצוות הכחול (למשל fail2ban, עדכוני אבטחה) — רק לאחר אישור מפורש, עם גיבוי קונפיגים ורישום ביומן. תיקונים מסוכנים (SSH/firewall) ידניים בלבד." },
};

function agents3dToggle() {
  AGENTS3D_ON = !AGENTS3D_ON;
  $("agents3dBtn").textContent = AGENTS3D_ON ? "📇 כרטיסים" : "🌌 תלת‑מימד";
  $("dashAgents").classList.toggle("hidden", AGENTS3D_ON);
  $("agentsStage").classList.toggle("hidden", !AGENTS3D_ON);
  $("agentPanel").classList.add("hidden");
  if (AGENTS3D_ON) buildAgents3d(); else agents3dStop();
}

function agents3dStop() { if (AGX && AGX.raf) { cancelAnimationFrame(AGX.raf); AGX.raf = null; } }

function buildAgents3d() {
  const prevView = AGX && AGX.view;          // preserve rotation across dashboard polls
  agents3dStop();
  const canvas = $("agentsCanvas");
  const ctx = canvas.getContext("2d");
  const list = (DASH_AGENTS || []).filter(a => a.id);
  const n = list.length || 1;
  list.forEach((a, i) => {
    const ang = (i / n) * Math.PI * 2, R = 190;
    a.X = Math.cos(ang) * R; a.Z = Math.sin(ang) * R; a.Y = Math.sin(ang * 2) * 40;
    a._tw = Math.random() * 6.28;
  });
  const stars = [];
  for (let i = 0; i < 220; i++) {
    const th = Math.random() * 6.283, ph = Math.acos(2 * Math.random() - 1), Rr = 500 + Math.random() * 600;
    stars.push({ X: Rr * Math.sin(ph) * Math.cos(th), Y: Rr * Math.sin(ph) * Math.sin(th), Z: Rr * Math.cos(ph),
                 s: 0.4 + Math.random(), tw: Math.random() * 6.28 });
  }
  AGX = { canvas, ctx, agents: list, stars,
    view: prevView || { rotX: -0.45, rotY: 0.3, dist: 560, f: 560, autoSpin: true },
    drag: null, moved: 0, last: null, t: 0, proj: [], dpr: Math.min(window.devicePixelRatio || 1, 2), W: 0, H: 0 };
  agents3dResize();
  agents3dWire();
  agents3dLoop();
}

function agents3dResize() {
  if (!AGX) return;
  const r = AGX.canvas.getBoundingClientRect();
  AGX.W = r.width; AGX.H = r.height;
  AGX.canvas.width = r.width * AGX.dpr; AGX.canvas.height = r.height * AGX.dpr;
  AGX.ctx.setTransform(AGX.dpr, 0, 0, AGX.dpr, 0, 0);
}

function agentColor(a) { const info = AGENT_INFO[a.id]; return info ? info.color : [139, 152, 169]; }

function agents3dLoop() {
  if (!AGX) return;
  const { ctx, view: v } = AGX, W = AGX.W, H = AGX.H;
  AGX.t += 1;
  if (v.autoSpin && !AGX.drag) v.rotY += 0.003;
  ctx.clearRect(0, 0, W, H);
  const bg = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) / 1.2);
  bg.addColorStop(0, "rgba(30,20,60,0.4)"); bg.addColorStop(1, "rgba(5,8,18,0)");
  ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
  AGX.stars.forEach(s => {
    const p = galProject(s, v, W, H); if (!p) return;
    const tw = 0.5 + 0.5 * Math.sin(AGX.t * 0.03 + s.tw);
    ctx.globalAlpha = Math.min(1, (0.12 + 0.35 * tw) * (600 / p.depth));
    ctx.fillStyle = "#cdd9ff"; ctx.beginPath(); ctx.arc(p.x, p.y, Math.max(0.4, s.s * p.scale * 0.5), 0, 6.283); ctx.fill();
  });
  ctx.globalAlpha = 1;
  const core = galProject({ X: 0, Y: 0, Z: 0 }, v, W, H);
  const proj = [];
  AGX.agents.forEach(a => { const p = galProject(a, v, W, H); if (p) { p.a = a; proj.push(p); } });
  if (core) {
    proj.forEach(p => {
      ctx.strokeStyle = "rgba(139,152,169," + Math.min(0.3, 120 / p.depth) + ")";
      ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(core.x, core.y); ctx.lineTo(p.x, p.y); ctx.stroke();
    });
    const cg = ctx.createRadialGradient(core.x, core.y, 0, core.x, core.y, 26 * core.scale + 8);
    cg.addColorStop(0, "rgba(200,180,255,0.85)"); cg.addColorStop(1, "rgba(120,90,220,0)");
    ctx.fillStyle = cg; ctx.beginPath(); ctx.arc(core.x, core.y, 26 * core.scale + 8, 0, 6.283); ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,0.85)"; ctx.beginPath(); ctx.arc(core.x, core.y, 4 * core.scale + 2, 0, 6.283); ctx.fill();
  }
  proj.sort((p, q) => q.depth - p.depth);
  proj.forEach(p => {
    const a = p.a, c = agentColor(a), active = a.status === "active";
    const rad = Math.max(4, (active ? 12 : 9) * p.scale);
    const tw = (active ? 0.85 : 0.55) + 0.18 * Math.sin(AGX.t * 0.06 + a._tw);
    const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, rad * 3.5);
    grad.addColorStop(0, `rgba(${c[0]},${c[1]},${c[2]},${0.95 * tw})`);
    grad.addColorStop(0.4, `rgba(${c[0]},${c[1]},${c[2]},0.35)`);
    grad.addColorStop(1, `rgba(${c[0]},${c[1]},${c[2]},0)`);
    ctx.fillStyle = grad; ctx.beginPath(); ctx.arc(p.x, p.y, rad * 3.5, 0, 6.283); ctx.fill();
    ctx.fillStyle = `rgba(255,255,255,${0.9 * tw})`; ctx.beginPath(); ctx.arc(p.x, p.y, rad * 0.5, 0, 6.283); ctx.fill();
    p.rad = rad;
    ctx.textAlign = "center";
    ctx.font = (15 * Math.max(0.8, p.scale)) + "px sans-serif";
    ctx.fillText(a.icon, p.x, p.y - rad - 6);
    ctx.fillStyle = "rgba(230,237,243,0.9)"; ctx.font = "12px sans-serif";
    ctx.fillText(a.name, p.x, p.y + rad + 16);
  });
  AGX.proj = proj;
  AGX.raf = requestAnimationFrame(agents3dLoop);
}

function agents3dHit(e) {
  if (!AGX || !AGX.proj) return null;
  const r = AGX.canvas.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  let best = null, bd = 1e9;
  AGX.proj.forEach(p => { const d = Math.hypot(p.x - mx, p.y - my); if (d < Math.max(20, (p.rad || 6) * 3) && d < bd) { bd = d; best = p.a; } });
  return best;
}

function agents3dWire() {
  const c = AGX.canvas;
  c.onpointerdown = (e) => {
    c.setPointerCapture(e.pointerId); AGX.moved = 0; AGX.last = { x: e.clientX, y: e.clientY };
    const hit = agents3dHit(e); AGX.drag = hit ? { node: hit } : { orbit: true }; AGX.view.autoSpin = false;
  };
  c.onpointermove = (e) => {
    if (!AGX.drag) return;
    const dx = e.clientX - AGX.last.x, dy = e.clientY - AGX.last.y; AGX.last = { x: e.clientX, y: e.clientY }; AGX.moved += Math.abs(dx) + Math.abs(dy);
    if (AGX.drag.orbit) { AGX.view.rotY += dx * 0.006; AGX.view.rotX = Math.max(-1.4, Math.min(1.4, AGX.view.rotX + dy * 0.006)); }
  };
  c.onpointerup = (e) => {
    if (AGX.drag && AGX.drag.node && AGX.moved < 5) openAgentInfo(AGX.drag.node);
    AGX.drag = null; try { c.releasePointerCapture(e.pointerId); } catch (_) {}
    setTimeout(() => { if (AGX) AGX.view.autoSpin = true; }, 3000);
  };
  c.onwheel = (e) => { e.preventDefault(); AGX.view.dist = Math.max(220, Math.min(1200, AGX.view.dist * (e.deltaY < 0 ? 0.9 : 1.1))); };
}

function openAgentInfo(a) {
  const info = AGENT_INFO[a.id] || { title: a.name, text: a.role || "" };
  const st = { active: "🟢 פעיל", idle: "⚪ ממתין", done: "✅ סיים" }[a.status] || a.status;
  $("agentPanelBody").innerHTML =
    `<div class="agent-panel-tag">${a.icon} ${escapeHtml(info.title)}</div>` +
    `<div class="agent-panel-role">${escapeHtml(a.role || "")} · ${st}</div>` +
    `<p class="agent-panel-text">${escapeHtml(info.text)}</p>` +
    (a.detail ? `<div class="agent-panel-live"><b>מצב נוכחי:</b> ${escapeHtml(a.detail)}</div>` : "");
  $("agentPanel").classList.remove("hidden");
}

/* ============================================================ 3D GALAXY VIEW
   The Obsidian vault as a navigable 3D star field — pure canvas, no libraries.
   Each star is a data node (report/threat/MOC); spin, fly, and drag stars. */
let GAL = null;

function galaxyStop() {
  if (GAL && GAL.raf) { cancelAnimationFrame(GAL.raf); GAL.raf = null; }
}

function galaxyBuild(nodes, links) {
  galaxyStop();
  const canvas = $("galaxyCanvas");
  const ctx = canvas.getContext("2d");
  const idx = {}; nodes.forEach(n => idx[n.id] = n);
  let k = 0;
  nodes.forEach(n => {
    if (n.type === "moc") { n.X = 0; n.Y = 0; n.Z = 0; }
    else {
      const a = k * 0.5, r = 70 + k * 9 + (n.type === "threat" ? 0 : 45);
      n.X = Math.cos(a) * r; n.Z = Math.sin(a) * r; n.Y = (Math.random() - 0.5) * 60;
      k++;
    }
    n._tw = Math.random() * 6.28; n._dim = false;
  });
  const edges = links.map(l => ({ s: idx[l.source], t: idx[l.target] })).filter(e => e.s && e.t);
  const stars = [];
  for (let i = 0; i < 340; i++) {
    const th = Math.random() * 6.283, ph = Math.acos(2 * Math.random() - 1), R = 520 + Math.random() * 760;
    stars.push({ X: R * Math.sin(ph) * Math.cos(th), Y: R * Math.sin(ph) * Math.sin(th), Z: R * Math.cos(ph),
                 s: 0.4 + Math.random() * 1.1, tw: Math.random() * 6.283 });
  }
  GAL = {
    canvas, ctx, nodes, edges, stars,
    view: { rotX: -0.5, rotY: 0.4, dist: 640, f: 640, autoSpin: true },
    drag: null, moved: 0, last: null, t: 0, proj: [],
    dpr: Math.min(window.devicePixelRatio || 1, 2), W: 0, H: 0,
  };
  galaxyResize();
  galaxyWire();
  galaxyLoop();
}

function galaxyResize() {
  if (!GAL) return;
  const r = GAL.canvas.getBoundingClientRect();
  GAL.W = r.width; GAL.H = r.height;
  GAL.canvas.width = r.width * GAL.dpr; GAL.canvas.height = r.height * GAL.dpr;
  GAL.ctx.setTransform(GAL.dpr, 0, 0, GAL.dpr, 0, 0);
}

function galProject(p, v, W, H) {
  const cy = Math.cos(v.rotY), sy = Math.sin(v.rotY);
  const x1 = p.X * cy - p.Z * sy, z1 = p.X * sy + p.Z * cy;
  const cx = Math.cos(v.rotX), sx = Math.sin(v.rotX);
  const y1 = p.Y * cx - z1 * sx, z2 = p.Y * sx + z1 * cx;
  const zz = z2 + v.dist;
  if (zz <= 1) return null;
  const scale = v.f / zz;
  return { x: W / 2 + x1 * scale, y: H / 2 + y1 * scale, scale, depth: zz };
}

function galColor(n) {
  if (n.type === "moc") return [168, 85, 247];
  if (n.type === "report") return [47, 129, 247];
  const s = n.severity;
  if (s === "critical") return [255, 45, 45];
  if (s === "high") return [248, 81, 73];
  if (s === "medium") return [210, 153, 34];
  if (s === "low") return [63, 185, 80];
  return [248, 81, 73];
}
function galRadius(n) { return n.type === "moc" ? 9 : n.type === "threat" ? Math.min(7, 3 + (n.count || 1)) : 4.5; }

function galaxyLoop() {
  if (!GAL) return;
  const { ctx, view: v } = GAL, W = GAL.W, H = GAL.H;
  GAL.t += 1;
  if (v.autoSpin && !GAL.drag) v.rotY += 0.0016;

  ctx.clearRect(0, 0, W, H);
  const bg = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) / 1.2);
  bg.addColorStop(0, "rgba(35,22,66,0.40)"); bg.addColorStop(1, "rgba(5,8,18,0)");
  ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);

  GAL.stars.forEach(s => {
    const p = galProject(s, v, W, H); if (!p) return;
    const tw = 0.5 + 0.5 * Math.sin(GAL.t * 0.03 + s.tw);
    ctx.globalAlpha = Math.min(1, (0.12 + 0.4 * tw) * (600 / p.depth));
    ctx.fillStyle = "#cdd9ff";
    ctx.beginPath(); ctx.arc(p.x, p.y, Math.max(0.4, s.s * p.scale * 0.5), 0, 6.283); ctx.fill();
  });
  ctx.globalAlpha = 1;

  const proj = [];
  GAL.nodes.forEach(n => { const p = galProject(n, v, W, H); if (p) { p.n = n; proj.push(p); } });

  ctx.lineWidth = 1;
  GAL.edges.forEach(e => {
    const a = galProject(e.s, v, W, H), b = galProject(e.t, v, W, H);
    if (!a || !b) return;
    const al = Math.min(0.28, 130 / Math.max(a.depth, b.depth)) * ((e.s._dim || e.t._dim) ? 0.25 : 1);
    ctx.strokeStyle = "rgba(139,152,169," + al + ")";
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  });

  proj.sort((p, q) => q.depth - p.depth);
  proj.forEach(p => {
    const n = p.n, c = galColor(n), rad = Math.max(1.5, galRadius(n) * p.scale);
    const dimf = n._dim ? 0.18 : 1;
    const tw = (0.8 + 0.2 * Math.sin(GAL.t * 0.05 + n._tw)) * dimf;
    const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, rad * 4.2);
    grad.addColorStop(0, `rgba(${c[0]},${c[1]},${c[2]},${0.9 * tw})`);
    grad.addColorStop(0.4, `rgba(${c[0]},${c[1]},${c[2]},${0.35 * dimf})`);
    grad.addColorStop(1, `rgba(${c[0]},${c[1]},${c[2]},0)`);
    ctx.fillStyle = grad; ctx.beginPath(); ctx.arc(p.x, p.y, rad * 4.2, 0, 6.283); ctx.fill();
    ctx.fillStyle = `rgba(255,255,255,${0.9 * tw})`;
    ctx.beginPath(); ctx.arc(p.x, p.y, rad * 0.55, 0, 6.283); ctx.fill();
    p.rad = rad;
    if (!n._dim && (n.type === "moc" || p.scale > 1.05)) {
      const label = n.type === "moc" ? "מרכז הבקרה" : (n.label.length > 20 ? n.label.slice(0, 19) + "…" : n.label);
      ctx.fillStyle = "rgba(230,237,243,0.9)"; ctx.font = "12px sans-serif"; ctx.textAlign = "center";
      ctx.fillText(label, p.x, p.y - rad * 4.2 - 4);
    }
  });
  GAL.proj = proj;
  GAL.raf = requestAnimationFrame(galaxyLoop);
}

function galHit(e) {
  if (!GAL || !GAL.proj) return null;
  const r = GAL.canvas.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  let best = null, bd = 1e9;
  GAL.proj.forEach(p => {
    const d = Math.hypot(p.x - mx, p.y - my);
    if (d < Math.max(12, (p.rad || 3) * 4) && d < bd) { bd = d; best = p.n; }
  });
  return best;
}

function galMoveNode(n, dxs, dys) {
  const v = GAL.view, p = galProject(n, v, GAL.W, GAL.H), s = p ? p.scale : 1;
  const dx1 = dxs / s, dy1 = dys / s;
  const cx = Math.cos(v.rotX), sx = Math.sin(v.rotX);
  const y_after = dy1 * cx, z1_after = -dy1 * sx;   // inverse rotX (camera-plane vector, z=0)
  const cy = Math.cos(v.rotY), sy = Math.sin(v.rotY);
  n.X += dx1 * cy + z1_after * sy;
  n.Y += y_after;
  n.Z += -dx1 * sy + z1_after * cy;
}

function galaxyWire() {
  const c = GAL.canvas;
  c.onpointerdown = (e) => {
    c.setPointerCapture(e.pointerId);
    GAL.moved = 0; GAL.last = { x: e.clientX, y: e.clientY };
    const hit = galHit(e);
    GAL.drag = hit ? { node: hit } : { orbit: true };
    GAL.view.autoSpin = false;
  };
  c.onpointermove = (e) => {
    if (!GAL.drag) return;
    const dx = e.clientX - GAL.last.x, dy = e.clientY - GAL.last.y;
    GAL.last = { x: e.clientX, y: e.clientY };
    GAL.moved += Math.abs(dx) + Math.abs(dy);
    if (GAL.drag.orbit) {
      GAL.view.rotY += dx * 0.006;
      GAL.view.rotX = Math.max(-1.4, Math.min(1.4, GAL.view.rotX + dy * 0.006));
    } else if (GAL.drag.node) {
      galMoveNode(GAL.drag.node, dx, dy);
    }
  };
  c.onpointerup = (e) => {
    if (GAL.drag && GAL.drag.node && GAL.moved < 5) galaxyOpenNote(GAL.drag.node);
    GAL.drag = null;
    try { c.releasePointerCapture(e.pointerId); } catch (_) {}
    setTimeout(() => { if (GAL) GAL.view.autoSpin = true; }, 3500);
  };
  c.onwheel = (e) => {
    e.preventDefault();
    GAL.view.dist = Math.max(140, Math.min(1600, GAL.view.dist * (e.deltaY < 0 ? 0.9 : 1.1)));
  };
}

function galaxyOpenNote(n) {
  const tag = n.type === "moc" ? "🛡️ מרכז" : n.type === "threat" ? "🎯 איום" : "📄 דוח";
  $("vaultPanelTag").textContent = tag;
  $("vaultPanelBody").innerHTML = mdToHtml(n.body || "*(אין תוכן)*");
  $("vaultPanel").classList.remove("hidden");
}

function vaultRadius(n) {
  if (n.type === "moc") return 30;
  if (n.type === "threat") return Math.min(22, 9 + (n.count || 1) * 2);
  return 11;
}

function vaultLayout(nodes, links) {
  const idx = {}; nodes.forEach(n => idx[n.id] = n);
  nodes.forEach((n, i) => {
    if (n.type === "moc") { n.x = VW / 2; n.y = VH / 2; }
    else {
      const a = i * 2.399, r = n.type === "threat" ? 170 : 300;
      n.x = VW / 2 + Math.cos(a) * r; n.y = VH / 2 + Math.sin(a) * r;
    }
    n.vx = 0; n.vy = 0;
  });
  const L = links.map(l => ({ s: idx[l.source], t: idx[l.target] })).filter(l => l.s && l.t);
  const iters = nodes.length > 220 ? 160 : 300;
  for (let it = 0; it < iters; it++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy || 0.01, d = Math.sqrt(d2);
        const rep = 5000 / d2, fx = dx / d * rep, fy = dy / d * rep;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }
    }
    L.forEach(l => {
      let dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const k = (d - 115) * 0.02, fx = dx / d * k, fy = dy / d * k;
      l.s.vx += fx; l.s.vy += fy; l.t.vx -= fx; l.t.vy -= fy;
    });
    nodes.forEach(n => {
      if (n.type === "moc") { n.x = VW / 2; n.y = VH / 2; n.vx = n.vy = 0; return; }
      n.vx += (VW / 2 - n.x) * 0.002; n.vy += (VH / 2 - n.y) * 0.002;
      n.vx *= 0.85; n.vy *= 0.85;
      n.x += Math.max(-30, Math.min(30, n.vx)); n.y += Math.max(-30, Math.min(30, n.vy));
      n.x = Math.max(34, Math.min(VW - 34, n.x)); n.y = Math.max(34, Math.min(VH - 34, n.y));
    });
  }
}

function vaultRender(nodes, links) {
  const svg = $("vaultSvg");
  svg.setAttribute("viewBox", `0 0 ${VW} ${VH}`);
  svg.innerHTML = "";
  vaultView = { scale: 1, tx: 0, ty: 0 };
  const root = vEl("g", { id: "vaultRoot" });
  const eLayer = vEl("g", {}), nLayer = vEl("g", {});
  root.appendChild(eLayer); root.appendChild(nLayer);
  svg.appendChild(root);

  const idx = {}; nodes.forEach(n => idx[n.id] = n);
  const edges = links.map(l => ({ s: idx[l.source], t: idx[l.target] })).filter(l => l.s && l.t);
  edges.forEach(ed => {
    ed.line = vEl("line", { class: "v-edge", x1: ed.s.x, y1: ed.s.y, x2: ed.t.x, y2: ed.t.y });
    eLayer.appendChild(ed.line);
  });
  nodes.forEach(n => {
    const g = vEl("g", { class: "v-node v-" + n.type, "data-id": n.id });
    n._c = vEl("circle", { r: vaultRadius(n), cx: n.x, cy: n.y,
                           class: "v-circle" + (n.type === "threat" && n.severity ? " sev-" + n.severity : "") });
    const short = n.label.length > 22 ? n.label.slice(0, 21) + "…" : n.label;
    n._t = vEl("text", { x: n.x, y: n.y + vaultRadius(n) + 13, class: "v-label", "text-anchor": "middle" });
    n._t.textContent = n.type === "moc" ? "מרכז הבקרה" : short;
    g.appendChild(n._c); g.appendChild(n._t);
    nLayer.appendChild(g);
    n._g = g;
  });
  VAULT = { nodes, edges };
  vaultWire();
}

function vaultUpdatePositions() {
  VAULT.edges.forEach(ed => {
    ed.line.setAttribute("x1", ed.s.x); ed.line.setAttribute("y1", ed.s.y);
    ed.line.setAttribute("x2", ed.t.x); ed.line.setAttribute("y2", ed.t.y);
  });
  VAULT.nodes.forEach(n => {
    n._c.setAttribute("cx", n.x); n._c.setAttribute("cy", n.y);
    n._t.setAttribute("x", n.x); n._t.setAttribute("y", n.y + vaultRadius(n) + 13);
  });
}

function vaultApplyView() {
  const root = $("vaultRoot");
  if (root) root.setAttribute("transform",
    `translate(${vaultView.tx} ${vaultView.ty}) scale(${vaultView.scale})`);
}

function vaultToUser(evt) {
  const svg = $("vaultSvg"), root = $("vaultRoot");
  const pt = svg.createSVGPoint();
  pt.x = evt.clientX; pt.y = evt.clientY;
  return pt.matrixTransform(root.getScreenCTM().inverse());
}

function vaultWire() {
  const svg = $("vaultSvg");
  let drag = null, moved = 0, panning = null;

  svg.onpointerdown = (e) => {
    const g = e.target.closest(".v-node");
    if (g) {
      const n = VAULT.nodes.find(x => x._g === g);
      drag = n; moved = 0;
      svg.setPointerCapture(e.pointerId);
    } else {
      panning = { x: e.clientX, y: e.clientY, tx: vaultView.tx, ty: vaultView.ty };
      svg.setPointerCapture(e.pointerId);
    }
  };
  svg.onpointermove = (e) => {
    if (drag) {
      const p = vaultToUser(e);
      moved += Math.abs(p.x - drag.x) + Math.abs(p.y - drag.y);
      drag.x = p.x; drag.y = p.y;
      vaultUpdatePositions();
    } else if (panning) {
      vaultView.tx = panning.tx + (e.clientX - panning.x);
      vaultView.ty = panning.ty + (e.clientY - panning.y);
      vaultApplyView();
    }
  };
  svg.onpointerup = (e) => {
    if (drag && moved < 5) vaultOpenNote(drag);
    drag = null; panning = null;
    try { svg.releasePointerCapture(e.pointerId); } catch (_) {}
  };
  svg.onwheel = (e) => {
    e.preventDefault();
    const before = vaultToUser(e);
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    vaultView.scale = Math.max(0.3, Math.min(4, vaultView.scale * factor));
    vaultApplyView();
    const after = vaultToUser(e);
    vaultView.tx += (after.x - before.x) * vaultView.scale;
    vaultView.ty += (after.y - before.y) * vaultView.scale;
    vaultApplyView();
  };
}

function vaultOpenNote(n) {
  const panel = $("vaultPanel");
  const tag = n.type === "moc" ? "🛡️ מרכז" : n.type === "threat" ? "🎯 איום" : "📄 דוח";
  $("vaultPanelTag").textContent = tag;
  $("vaultPanelBody").innerHTML = mdToHtml(n.body || "*(אין תוכן)*");
  panel.classList.remove("hidden");
  VAULT.nodes.forEach(x => x._g.classList.toggle("v-active", x === n));
  const linked = new Set();
  VAULT.edges.forEach(ed => {
    if (ed.s === n) linked.add(ed.t); if (ed.t === n) linked.add(ed.s);
  });
  VAULT.nodes.forEach(x => x._g.classList.toggle("v-linked", linked.has(x)));
}

function vaultSearch(term) {
  term = (term || "").trim().toLowerCase();
  if (VAULT_MODE === "3d") {
    if (GAL) GAL.nodes.forEach(n => {
      n._dim = !(!term || n.type === "moc" || (n.label || "").toLowerCase().includes(term));
    });
    return;
  }
  VAULT.nodes.forEach(n => {
    const hit = !term || n.type === "moc" || (n.label || "").toLowerCase().includes(term);
    if (n._g) n._g.classList.toggle("v-dim", !hit);
  });
}

/* ============================================================ HYPERSPACE FX
   Star Wars-style hyperspace starfield — stars streak from a vanishing point.
   Nav changes trigger a brief "jump to lightspeed". Pure canvas, behind all. */
let HYPER = null;
function initFx() {
  if (location.search.indexOf("nofx") >= 0) return;
  const c = $("fxCanvas"); if (!c) return;
  const ctx = c.getContext("2d");
  const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const CHARS = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンｦｱｳｴｵｶｷｹｺ0123456789:.=*+-<>|╌ﾊﾐﾋｰｳｼﾅﾓﾆｻﾜ".split("");
  let W = 0, H = 0, cols = 0, drops = [], font = 16, speed = 1, target = 1;
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    c.width = W * dpr; c.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    font = Math.max(13, Math.round(W / 95));
    cols = Math.ceil(W / font);
    const rows = H / font;
    drops = Array.from({ length: cols }, () => Math.floor(Math.random() * (rows + 40)) - 40);  // spread across screen
    ctx.fillStyle = "#010603"; ctx.fillRect(0, 0, W, H);
  }
  function step() {
    speed += (target - speed) * 0.06;
    ctx.fillStyle = "rgba(1,7,3,0.075)"; ctx.fillRect(0, 0, W, H);   // fade → green-black trails
    ctx.font = font + "px 'Cascadia Code','Consolas',monospace";
    for (let i = 0; i < cols; i++) {
      const y = drops[i] * font;
      if (y > 0) {
        const ch = CHARS[(Math.random() * CHARS.length) | 0];
        if (Math.random() > 0.86) { ctx.fillStyle = "rgba(200,255,214,0.95)"; ctx.shadowColor = "#00ff70"; ctx.shadowBlur = 8; }
        else { ctx.fillStyle = "rgba(0,225,80,0.72)"; ctx.shadowBlur = 0; }
        ctx.fillText(ch, i * font, y);
        ctx.shadowBlur = 0;
      }
      drops[i] += 0.5 * speed;
      if (y > H && Math.random() > 0.975) drops[i] = Math.random() * -20;
    }
  }
  function frame() { step(); HYPER.raf = requestAnimationFrame(frame); }
  HYPER = { raf: null, jump: () => { target = 3.4; clearTimeout(HYPER._t); HYPER._t = setTimeout(() => { target = 1; }, 650); } };
  resize();
  window.addEventListener("resize", resize);
  for (let i = 0; i < 46; i++) step();   // prime the canvas so the rain is full on first paint
  if (!reduce) frame();
}
function hyperjump() { if (HYPER && HYPER.jump) HYPER.jump(); }   // "digital surge" on navigation

/* ==================================================== STAR WARS OPENING CRAWL */
function playCrawl() {
  const el = $("crawl"); if (!el) return;
  el.classList.remove("hidden");
  hyperjump();
  // restart the CSS animations
  ["crawl-intro", "crawl-content"].forEach(cls => {
    const n = el.querySelector("." + cls);
    if (n) { n.style.animation = "none"; void n.offsetHeight; n.style.animation = ""; }
  });
  const close = () => el.classList.add("hidden");
  $("crawlSkip").onclick = close;
  el.onclick = (e) => { if (e.target === el) close(); };
  const esc = (e) => { if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); } };
  document.addEventListener("keydown", esc);
  clearTimeout(el._t); el._t = setTimeout(close, 52000);
}
function maybeCrawl() {
  if (location.search.indexOf("nocrawl") >= 0) return;
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let seen = false; try { seen = localStorage.getItem("kg_crawl") === "1"; } catch (e) {}
  if (!seen && !reduce) { playCrawl(); try { localStorage.setItem("kg_crawl", "1"); } catch (e) {} }
}

/* ============================================================ I18N (EN / HE)
   Toggle language + text direction. Hebrew originals are captured from the DOM;
   English strings come from the dictionary below (extendable per element). */
const HE_ORIG = {};
const I18N_EN = {
  "brand.sub": "Graphical interface for Kali Linux tools · by Hareli Dudai",
  "nav.tools": "🧰 Tools", "nav.ai": "🤖 AI Assistant", "nav.dash": "📊 Dashboard",
  "nav.history": "🕓 History", "nav.learning": "📚 Learn", "nav.vault": "📓 Obsidian",
  "nav.users": "👥 Users", "nav.playbooks": "✏️ Playbooks",
  "ai.title": "The Smart Testing Assistant",
  "ai.sub": "Describe what you want to test — the agent will pick the right tools, plan, run, verify and report.",
  "ai.plan": "🧠 Create Plan", "ai.intentLabel": "What do you want to test?", "ai.targetLabel": "Target",
  "dash.title": "📊 Command Center", "dash.sub": "Live view of the agents, accumulated intelligence and activity log",
  "picker.search": "🔎 Search tool...",
};
let LANG = (function () { try { return localStorage.getItem("kg_lang") || "he"; } catch (e) { return "he"; } })();

function applyLang(lang) {
  LANG = lang;
  try { localStorage.setItem("kg_lang", lang); } catch (e) {}
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "he" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const k = el.getAttribute("data-i18n");
    const v = lang === "he" ? HE_ORIG[k] : (I18N_EN[k] != null ? I18N_EN[k] : HE_ORIG[k]);
    if (v != null) el.textContent = v;
  });
  document.querySelectorAll("[data-i18n-ph]").forEach(el => {
    const k = el.getAttribute("data-i18n-ph");
    el.placeholder = lang === "he" ? (HE_ORIG["ph:" + k] || el.placeholder) : (I18N_EN[k] || el.placeholder);
  });
  const btn = $("langToggle"); if (btn) btn.textContent = lang === "he" ? "EN" : "עב";
}
function initI18n() {
  document.querySelectorAll("[data-i18n]").forEach(el => { HE_ORIG[el.getAttribute("data-i18n")] = el.textContent; });
  document.querySelectorAll("[data-i18n-ph]").forEach(el => { HE_ORIG["ph:" + el.getAttribute("data-i18n-ph")] = el.placeholder; });
  const btn = $("langToggle"); if (btn) btn.onclick = () => applyLang(LANG === "he" ? "en" : "he");
  applyLang(LANG);
}

/* ============================================================ LIVING MOTION
   3D tilt on cards, count-up numbers, and staggered reveals — makes the whole
   interface feel alive and in motion. */
function initMotion() {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) return;
  // 3D tilt: cards with .tilt follow the cursor
  document.addEventListener("mousemove", (e) => {
    const card = e.target.closest && e.target.closest(".tilt");
    if (!card) return;
    const r = card.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    card.style.transform = `perspective(700px) rotateY(${px * 8}deg) rotateX(${-py * 8}deg) translateY(-4px)`;
    card.style.setProperty("--mx", (px * 100 + 50) + "%");
    card.style.setProperty("--my", (py * 100 + 50) + "%");
  }, { passive: true });
  document.addEventListener("mouseout", (e) => {
    const card = e.target.closest && e.target.closest(".tilt");
    if (card && !card.contains(e.relatedTarget)) card.style.transform = "";
  }, true);
}

// animate a number from 0 → target
function countUp(el, target, dur) {
  if (!el) return;
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target = Number(target) || 0;
  if (reduce || target === 0) { el.textContent = String(target); return; }
  const t0 = performance.now ? performance.now() : 0, D = dur || 800;
  function step(now) {
    const p = Math.min(1, (now - t0) / D);
    el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// stagger-reveal the children of a freshly-rendered container
function staggerReveal(container, sel) {
  if (!container) return;
  const items = container.querySelectorAll(sel);
  items.forEach((n, i) => {
    n.classList.remove("reveal"); void n.offsetWidth;
    n.style.animationDelay = Math.min(i, 20) * 0.05 + "s";
    n.classList.add("reveal");
  });
}

document.addEventListener("DOMContentLoaded", () => {
  init(); initFx(); initI18n(); initMotion();
  const rep = $("crawlReplay"); if (rep) rep.onclick = playCrawl;
  maybeCrawl();
});
