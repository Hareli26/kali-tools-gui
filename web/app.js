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
  return true;
}

async function startMission() {
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
  return true;
}

async function startPurple() {
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
  $("reportRerunBtn").onclick = () => { if (REPORT_META && REPORT_META.target) rerunRun(REPORT_META.intent, REPORT_META.target, REPORT_META.type); };
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
  initBrain();
  $("threatClose").onclick = () => $("threatModal").classList.add("hidden");
  $("threatModal").onclick = (e) => { if (e.target === $("threatModal")) $("threatModal").classList.add("hidden"); };
  $("installCancel").onclick = () => $("installModal").classList.add("hidden");
  $("installGo").onclick = doInstall;
  $("sudoPass").onkeydown = (e) => { if (e.key === "Enter") doInstall(); };
  initAI();
  loadCatalog();
  window.addEventListener("hashchange", applyHash);
  applyHash();
}

// Deep-linking: #dashboard, #ai, #tools, #brain-<agentId>
async function applyHash() {
  const h = (location.hash || "").replace(/^#/, "");
  if (!h) return;
  if (h === "dashboard") { showScreen("dashboard"); }
  else if (h === "ai") { showScreen("ai-prompt"); }
  else if (h === "tools") { showScreen("picker"); }
  else if (h.startsWith("brain-")) { await openBrain(h.slice(6)); }
}

document.addEventListener("DOMContentLoaded", init);
