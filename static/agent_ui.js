// Agent Workbench：Discord 版面 × Codex 工具卡。
// 對話內容一律從 chat_history 讀（/api/conversations/<id>），所以 CLI 跑的任務（run_video_thin.py）也能即時看。
const $ = (s) => document.querySelector(s);
const state = { convs: [], filter: "all", sel: null, msgCount: -1, lastData: null, poll: null, defaults: {}, running: [] };
const cfg = JSON.parse(localStorage.getItem("agentCfg") || "{}");

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtTime = (iso) => { if (!iso) return ""; const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString("zh-TW", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }); };
// 影片任務顯示成「日期 時間 · 模式 · 題目」；新舊兩種 id 格式都支援
function displayName(id) {
  // 分段 Agent 的子對話：<主對話>__seg_03 → 「　└ 第 3 段」
  let m = /__seg_(\d+)$/.exec(id);
  if (m) return `${displayName(id.slice(0, m.index))} · 第 ${Number(m[1])} 段`;
  m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})_(thin|thick|seg)_(.+)$/.exec(id);
  if (m) return `${m[2]}/${m[3]} ${m[4]}:${m[5]} · ${m[7]} · ${m[8]}`;
  m = /^video_(thin|thick)_(.+)_(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(id);
  if (m) return `${m[3]}/${m[4]} ${m[5]}:${m[6]} · ${m[1]} · ${m[2]}`;
  return id;
}
const kindOf = (id) => /__seg_\d+$/.test(id) ? "sub" : /^video_th(in|ick)|^\d{8}-\d{6}_(thin|thick|seg)_/.test(id) ? "video" : id.startsWith("sub") || id.includes("subagent") ? "sub" : "chat";
const fileUrl = (p) => `/api/file?path=${encodeURIComponent(p)}`;
const MEDIA_RE = /([A-Za-z]:[\\/][^"'\s<>|]+?\.(?:jpg|jpeg|png|webp|gif|mp4|webm))/gi;

function md(text) {
  let s = esc(String(text || "").replace(/<\?final>|<\?ask_user>/g, "").trim());
  s = s.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, l, c) => `<pre><code>${c}</code></pre>`);
  s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>").replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
  return s.split(/\n{2,}/).map((p) => p.startsWith("<pre>") ? p : `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
}
function pretty(raw) {
  try { return JSON.stringify(typeof raw === "string" ? JSON.parse(raw) : raw, null, 2); } catch { return String(raw ?? ""); }
}
function argSummary(raw) {
  try { const o = typeof raw === "string" ? JSON.parse(raw) : raw; return Object.entries(o || {}).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(" ").slice(0, 140); }
  catch { return String(raw || "").slice(0, 140); }
}
function mediaIn(text) { return [...new Set((String(text || "").replace(/\\\\/g, "\\").match(MEDIA_RE) || []))]; }
function toolOk(content) {
  const t = String(content || "");
  if (/^Error:|"ok":\s*false|Traceback/.test(t)) return false;
  return true;
}

// ---------- 頻道列 ----------
async function loadConvs() {
  const [list, defs] = await Promise.all([fetch("/api/conversations").then((r) => r.json()), fetch("/api/runtime-defaults").then((r) => r.json()).catch(() => ({}))]);
  state.defaults = defs; state.running = defs.running || [];
  state.convs = list.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  $("#modelBadge").textContent = `${cfg.provider || defs.provider || "?"} · ${cfg.model || defs.model || "default"}`;
  renderChannels();
}
function renderChannels() {
  const q = $("#chSearch").value.trim().toLowerCase();
  const groups = { video: "🎬 影片任務", chat: "💬 對話", sub: "🧩 子代理" };
  let html = "";
  for (const [k, label] of Object.entries(groups)) {
    if (state.filter !== "all" && state.filter !== k) continue;
    const items = state.convs.filter((c) => kindOf(c.conversation_id) === k && (!q || (c.conversation_id + c.preview).toLowerCase().includes(q)));
    if (!items.length) continue;
    html += `<div class="ch-group">${label}</div>`;
    for (const c of items) {
      const live = state.running.includes(c.conversation_id) || isRecent(c);
      html += `<div class="ch-item ${c.conversation_id === state.sel ? "sel" : ""}" data-id="${esc(c.conversation_id)}" title="${esc(c.preview)}">
        <span class="h">#</span><span class="nm">${esc(displayName(c.conversation_id))}</span>${live ? '<span class="live"></span>' : ""}</div>`;
    }
  }
  $("#chList").innerHTML = html || '<div class="muted" style="padding:12px">沒有對話</div>';
}
const isRecent = (c) => false;  // 列表 API 沒有最後更新時間；選取後由 feed 判斷

// ---------- 對話 ----------
async function openConv(id) {
  state.sel = id; state.msgCount = -1; openKeys.clear();
  $("#chatTitle").textContent = displayName(id); $("#chatTitle").title = id; $("#emptyState")?.remove();
  renderChannels();
  await refresh(true);
  clearInterval(state.poll);
  state.poll = setInterval(() => refresh(false), 2000);
}
async function refresh(force) {
  if (!state.sel) return;
  const r = await fetch(`/api/conversations/${encodeURIComponent(state.sel)}`);
  if (!r.ok) return;
  const data = await r.json();
  const msgs = data.messages || [];
  const running = isRunning(data);
  setStatus(running ? "running" : finalOf(msgs) ? "done" : msgs.length ? "idle" : "idle");
  if (!force && msgs.length === state.msgCount) { toggleTyping(running); return; }
  const nearBottom = $("#feed").scrollHeight - $("#feed").scrollTop - $("#feed").clientHeight < 120;
  state.msgCount = msgs.length; state.lastData = data;
  renderFeed(data); renderPanel(data); toggleTyping(running);
  if (force || nearBottom) $("#feed").scrollTop = $("#feed").scrollHeight;
  fetch(`/api/conversations/${encodeURIComponent(state.sel)}/todos`).then((r) => r.json()).then(renderTodos).catch(() => {});
}
function finalOf(msgs) { const last = [...msgs].reverse().find((m) => m.role === "assistant"); return last && /<\?final>/.test(last.content || "") ? last : null; }
function isRunning(data) {
  const msgs = data.messages || []; if (!msgs.length) return state.running.includes(state.sel);
  const last = msgs[msgs.length - 1];
  if (finalOf(msgs) && last.role === "assistant") return false;
  const age = (Date.now() - new Date(last.timestamp || 0).getTime()) / 1000;
  // 最後一則是工具結果或還在等工具：代表 runtime 還在跑（本機模型一步可能好幾分鐘）
  const pending = last.role === "tool" || (last.tool_calls && last.tool_calls.length) || last.role === "user";
  return state.running.includes(state.sel) || (pending && age < 1800) || age < 180;
}
function setStatus(s) { const p = $("#statusPill"); p.className = `pill ${s}`; p.textContent = s; }
function toggleTyping(on) {
  let t = $("#typing");
  if (on && !t) { $("#feed").insertAdjacentHTML("beforeend", '<div class="typing" id="typing"><i></i><i></i><i></i> Agent 正在工作…</div>'); }
  if (!on && t) t.remove();
}

// 展開狀態跨輪詢重繪保留（工具卡、思考過程）
const openKeys = new Set();
const isOpen = (k) => (openKeys.has(k) ? "open" : "");

function thinkBlock(m, i) {
  if (!m.reasoning) return "";
  const key = `think:${i}`;
  const u = m.usage || {};
  const tok = u.reasoning != null ? `${u.reasoning} tokens` : `${m.reasoning.length} 字`;
  return `<div class="think ${isOpen(key)}" data-key="${key}">
    <div class="think-h"><span class="ic">💭</span><span>思考過程</span><span class="tk">${esc(tok)}</span><span class="chev">›</span></div>
    <pre class="think-b">${esc(m.reasoning)}</pre></div>`;
}

function renderFeed(data) {
  const msgs = data.messages || [];
  const results = {};
  msgs.filter((m) => m.role === "tool").forEach((m) => { results[m.tool_call_id] = m; });
  const model = (data.runtime_meta && data.runtime_meta.model) || "";
  let html = "", prevRole = "";
  for (const [i, m] of msgs.entries()) {
    if (m.role === "tool") continue;
    const role = m.role === "user" ? "user" : m.role === "assistant" ? "agent" : "sys";
    const head = role !== prevRole;
    prevRole = role;
    let body = thinkBlock(m, i) + (m.content ? md(m.content) : "");
    for (const tc of m.tool_calls || []) {
      const res = results[tc.id];
      const content = res ? res.content : null;
      const st = content == null ? "" : toolOk(content) ? "ok" : "fail";
      const media = mediaIn(content);
      body += `<div class="tool ${st} ${isOpen("call:" + tc.id)}" data-key="call:${esc(tc.id)}" data-call="${esc(tc.id)}">
        <div class="tool-h"><span class="st"></span><span class="tn">${esc(tc.function.name)}</span><span class="ta">${esc(argSummary(tc.function.arguments))}</span><span class="chev">›</span></div>
        <div class="tool-b">
          <div class="tool-sec"><div class="lb">arguments</div><pre>${esc(pretty(tc.function.arguments))}</pre></div>
          <div class="tool-sec"><div class="lb">result ${content == null ? "（執行中…）" : ""}</div><pre>${esc(content == null ? "" : pretty(content).slice(0, 12000))}</pre></div>
        </div>
        ${media.length ? `<div class="thumbs">${media.map(thumb).join("")}</div>` : ""}
      </div>`;
    }
    if (!body) continue;
    const name = role === "user" ? "You" : role === "agent" ? "Agent" : m.role;
    const avatar = role === "user" ? "🧑" : role === "agent" ? "✦" : "⚙";
    html += `<div class="msg ${head ? "head" : ""}">
      <div>${head ? `<div class="av ${role}">${avatar}</div>` : ""}</div>
      <div>${head ? `<div class="who"><span class="nm">${name}</span>${role === "agent" ? `<span class="tag">BOT</span>${model ? `<span class="ts">${esc(model)}</span>` : ""}` : ""}<span class="ts">${fmtTime(m.timestamp)}</span></div>` : ""}
      <div class="body">${body}</div></div></div>`;
  }
  $("#feed").innerHTML = html || '<div class="muted" style="padding:20px 72px">（還沒有訊息）</div>';
}
const thumb = (p) => /\.(mp4|webm)$/i.test(p) ? `<video src="${fileUrl(p)}" muted preload="metadata" data-full="${esc(p)}"></video>` : `<img src="${fileUrl(p)}" loading="lazy" data-full="${esc(p)}" />`;

function renderPanel(data) {
  const msgs = data.messages || [];
  const calls = msgs.flatMap((m) => (m.tool_calls || []).map((tc) => ({ tc, t: m.timestamp })));
  const results = Object.fromEntries(msgs.filter((m) => m.role === "tool").map((m) => [m.tool_call_id, m]));
  const fails = calls.filter(({ tc }) => results[tc.id] && !toolOk(results[tc.id].content)).length;
  const t0 = msgs[0]?.timestamp, t1 = msgs[msgs.length - 1]?.timestamp;
  const mins = t0 && t1 ? ((new Date(t1) - new Date(t0)) / 60000).toFixed(1) : "-";
  const rm = data.runtime_meta || {};
  $("#runMeta").innerHTML = [["model", rm.model || "—"], ["provider", rm.provider || "—"], ["messages", msgs.length],
    ["tool calls", `${calls.length}（失敗 ${fails}）`], ["elapsed", `${mins} 分`], ["started", fmtTime(t0)]]
    .map(([k, v]) => `<dt>${k}</dt><dd title="${esc(v)}">${esc(v)}</dd>`).join("");
  $("#timeline").innerHTML = calls.map(({ tc }, i) => {
    const r = results[tc.id]; const st = !r ? "" : toolOk(r.content) ? "ok" : "fail";
    return `<li class="${st}" data-call="${esc(tc.id)}"><span class="n">${i + 1}</span><span>${esc(tc.function.name)}</span></li>`;
  }).join("") || '<li class="muted">（無）</li>';
  const media = [...new Set(msgs.filter((m) => m.role === "tool").flatMap((m) => mediaIn(m.content)))];
  const vids = media.filter((p) => /\.(mp4|webm)$/i.test(p)), imgs = media.filter((p) => !/\.(mp4|webm)$/i.test(p)).slice(-12);
  $("#artifacts").innerHTML = (vids.map((p) => `<video class="vid" src="${fileUrl(p)}" controls preload="metadata"></video>`).join("") +
    imgs.map((p) => `<img src="${fileUrl(p)}" loading="lazy" data-full="${esc(p)}" title="${esc(p)}" />`).join("")) || '<span class="muted">（無）</span>';
}
function renderTodos(t) {
  const items = (t && t.items) || [];
  $("#todoCount").textContent = items.length ? `${items.filter((i) => i.status === "done").length}/${items.length}` : "";
  $("#todoList").innerHTML = items.map((i) => `<li class="${esc(i.status || "")}"><span class="ck"></span><span>${esc(i.title || i.content || i.text || "")}</span></li>`).join("") || '<li class="muted">（無）</li>';
}

// ---------- 送出 ----------
async function send(text) {
  const profile = $("#profileSel").value;
  const body = { prompt: text, max_steps: Number($("#maxSteps").value) || 40, profile,
    provider: cfg.provider || undefined, model: cfg.model || undefined, lm_api_url: cfg.url || undefined };
  if (state.sel) body.conversation_id = state.sel;
  $(".send").disabled = true;
  try {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json());
    if (r.error) { alert(r.error); return; }
    state.running.push(r.conversation_id);
    await loadConvs(); await openConv(r.conversation_id);
  } finally { $(".send").disabled = false; }
}

// ---------- 事件 ----------
$("#chList").addEventListener("click", (e) => { const it = e.target.closest(".ch-item"); if (it) openConv(it.dataset.id); });
$("#chSearch").addEventListener("input", renderChannels);
document.querySelectorAll(".rail-btn[data-filter]").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".rail-btn").forEach((x) => x.classList.remove("active")); b.classList.add("active");
  state.filter = b.dataset.filter; $("#filterTitle").textContent = b.title; renderChannels();
}));
$("#feed").addEventListener("click", (e) => {
  const h = e.target.closest(".tool-h, .think-h");
  if (h) {
    const box = h.parentElement, k = box.dataset.key;
    const now = box.classList.toggle("open");
    if (k) now ? openKeys.add(k) : openKeys.delete(k);
    return;
  }
  const m = e.target.closest("[data-full]"); if (m) lightbox(m.dataset.full);
});
$("#artifacts").addEventListener("click", (e) => { const m = e.target.closest("img[data-full]"); if (m) lightbox(m.dataset.full); });
$("#timeline").addEventListener("click", (e) => {
  const li = e.target.closest("li[data-call]"); if (!li) return;
  const card = document.querySelector(`.tool[data-call="${CSS.escape(li.dataset.call)}"]`);
  if (card) { card.classList.add("open"); if (card.dataset.key) openKeys.add(card.dataset.key); card.scrollIntoView({ behavior: "smooth", block: "center" }); }
});
function lightbox(p) {
  const v = /\.(mp4|webm)$/i.test(p);
  $("#lbImg").classList.toggle("on", !v); $("#lbVid").classList.toggle("on", v);
  if (v) $("#lbVid").src = fileUrl(p); else $("#lbImg").src = fileUrl(p);
  $("#lightbox").classList.add("on");
}
$("#lightbox").addEventListener("click", (e) => { if (e.target.id === "lightbox") { $("#lightbox").classList.remove("on"); $("#lbVid").pause(); } });
$("#newTaskBtn").addEventListener("click", () => { state.sel = null; clearInterval(state.poll); $("#chatTitle").textContent = "新任務"; setStatus("idle");
  $("#feed").innerHTML = ""; $("#runMeta").innerHTML = ""; $("#timeline").innerHTML = ""; $("#artifacts").innerHTML = '<span class="muted">（無）</span>'; renderChannels(); $("#prompt").focus(); });
$("#togglePanel").addEventListener("click", () => document.querySelector(".app").classList.toggle("no-panel"));
const ta = $("#prompt");
ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(200, ta.scrollHeight) + "px"; });
ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); } });
$("#composer").addEventListener("submit", (e) => { e.preventDefault(); const t = ta.value.trim(); if (!t) return; ta.value = ""; ta.style.height = "auto"; send(t); });
$("#settingsBtn").addEventListener("click", () => { $("#cfgProvider").value = cfg.provider || ""; $("#cfgModel").value = cfg.model || ""; $("#cfgUrl").value = cfg.url || ""; $("#settingsDlg").showModal(); });
$("#cfgSave").addEventListener("click", () => { cfg.provider = $("#cfgProvider").value; cfg.model = $("#cfgModel").value.trim(); cfg.url = $("#cfgUrl").value.trim();
  localStorage.setItem("agentCfg", JSON.stringify(cfg)); loadConvs(); });

const QUICK = [
  ["🎬 東方紅魔鄉角色速覽", "anim_thin", "請先用 lookup_skill 載入 anim_thin，然後照它做出影片。題目資料夾：temppad/haiku_test/t01_eosd。全程不要詢問我。"],
  ["🎬 魔物獵人配裝器三步驟", "anim_thin", "請先用 lookup_skill 載入 anim_thin，然後照它做出影片。題目資料夾：temppad/haiku_test/t05_wilds。全程不要詢問我。"],
  ["💬 列出可用技能", "general", "請用 scan_workspace 掃描 skills 目錄，列出可用技能並各用一句話說明。"],
];
$("#quickList").innerHTML = QUICK.map(([t], i) => `<button data-q="${i}">${esc(t)}</button>`).join("");
$("#quickList").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; const [, p, txt] = QUICK[b.dataset.q];
  $("#profileSel").value = p; $("#maxSteps").value = p === "anim_thin" ? 160 : 20; ta.value = txt; ta.focus(); });

loadConvs();
setInterval(loadConvs, 10000);
