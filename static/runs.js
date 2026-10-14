// 分段執行檢視：Sessions｜分段｜段落詳情（思考、工具）｜進度與分派。每 2 秒輪詢 chat_history，CLI 跑的流程也能即時看。
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fileUrl = (p) => `/api/file?path=${encodeURIComponent(p)}`;
const STATE = { pass: "通過", warn: "有問題", fallback: "保底", running: "進行中", queued: "等待中" };
const COLOR = { pass: "#23a55a", warn: "#f0b232", fallback: "#e67e22", running: "#5865f2", queued: "#4e5058" };

const st = { run: null, seg: null, data: null, openKeys: new Set(), lastDetail: "" };

async function getJSON(url) { const r = await fetch(url); return r.json(); }

// ---------- 1. Sessions ----------
async function loadSessions() {
  const runs = await getJSON("/api/seg-runs");
  $("#sessions").innerHTML = runs.map((r) => `
    <div class="sess ${r.id === st.run ? "sel" : ""}" data-id="${esc(r.id)}">
      <div class="t"><span class="dot ${r.live ? "live" : r.error ? "err" : r.done ? "ok" : ""}"></span>${esc(r.topic)}</div>
      <div class="m">${esc(r.when)} · ${esc(shortModel(r.model))}${r.seconds ? ` · ${Math.round(r.seconds / 60)} 分` : r.live ? " · 執行中" : ""}</div>
    </div>`).join("") || '<div class="empty">還沒有分段執行</div>';
  if (!st.run && runs.length) selectRun(runs[0].id);
}
const shortModel = (m) => String(m || "").replace(/^.*\//, "");

function selectRun(id) {
  st.run = id; st.seg = null; st.lastDetail = ""; st.lastSegs = ""; st.lastOverview = ""; st.openKeys.clear();
  document.querySelectorAll(".sess").forEach((e) => e.classList.toggle("sel", e.dataset.id === id));
  loadRun();
}

// ---------- 2. 分段 ----------
async function loadRun() {
  if (!st.run) return;
  const d = await getJSON(`/api/seg-runs/${encodeURIComponent(st.run)}`);
  st.data = d;
  $("#runTitle").textContent = d.id.replace(/^\d{8}-\d{6}_seg_/, "");
  $("#runMeta").textContent = `${shortModel(d.model)}${d.theme ? " · " + d.theme : ""}`;
  const segsHtml = planCard(d) + (d.segments.map(segCard).join("") || '<div class="empty">企劃中，分段還沒建立</div>');
  if (segsHtml !== st.lastSegs) { $("#segs").innerHTML = segsHtml; st.lastSegs = segsHtml; }  // 沒變不重畫，縮圖不會閃
  renderOverview(d);
  if (st.seg) loadDetail(); else renderPlanDetail(d);
}

function planCard(d) {
  const p = d.plan || {};
  const state = d.stages.find((s) => s.key === "plan")?.state;
  return `<div class="seg ${st.seg === null ? "sel" : ""} ${state === "done" ? "pass" : state === "running" ? "running" : ""}" data-seg="">
    <div class="bar"></div><div class="body">
      <div class="row"><span class="id">企劃</span><span class="blk">planner</span><span class="grow"></span>
        <span class="badge ${state === "done" ? "pass" : "running"}">${state === "done" ? `${p.attempts || 1} 次通過` : "進行中"}</span></div>
      <div class="kt">${esc(d.theme_reason || "選風格、排分鏡、分配素材")}</div>
    </div></div>`;
}

function segCard(s) {
  return `<div class="seg ${s.state} ${s.id === st.seg ? "sel" : ""}" data-seg="${esc(s.id)}">
    <div class="bar"></div><div class="body">
      <div class="row"><span class="id">${esc(s.id)}</span><span class="blk">${esc(s.block || "")}</span><span class="grow"></span>
        ${s.seconds ? `<span class="badge">${s.seconds}s</span>` : ""}
        <span class="badge ${s.state}">${STATE[s.state] || s.state}</span></div>
      <div class="txt">${esc(s.summary || s.script || "")}</div>
      ${s.key_text ? `<div class="kt">重點字：${esc(s.key_text.join("、"))}　素材：${esc(Object.values(s.media || {}).join("、") || "—")}</div>` : ""}
      ${s.sheet ? `<img src="${fileUrl(s.sheet)}&t=${s.seconds || Date.now() >> 14}" loading="lazy" data-full="${esc(s.sheet)}" alt="" />` : ""}
    </div></div>`;
}

// ---------- 3. 段落詳情 ----------
function fold(key, cls, head, body) {
  return `<div class="fold ${cls} ${st.openKeys.has(key) ? "open" : ""}" data-key="${esc(key)}">
    <div class="h">${head}<span class="chev">›</span></div><div class="b">${body}</div></div>`;
}

function renderPlanDetail(d) {
  $("#detailTitle").textContent = "企劃 Agent";
  const p = d.plan || {};
  $("#detailMeta").textContent = p.usage ? `prompt ${p.usage.prompt} · 輸出 ${p.usage.completion}（思考 ${p.usage.reasoning ?? 0}）` : "";
  let html = "";
  if (p.reasoning) html += fold("plan:think", "think", `💭 思考過程 <span class="badge">${p.usage?.reasoning ?? p.reasoning.length} tokens</span>`, esc(p.reasoning));
  (p.problems || []).forEach((probs, i) => {
    if (probs && probs.length) html += `<div class="sec-title">第 ${i + 1} 次企劃被退回</div><div class="bubble">${esc(probs.join("\n"))}</div>`;
  });
  (p.repairs || []).forEach((fx) => { if (fx && fx.length) html += `<div class="sec-title">程式自動修正</div><div class="bubble">${esc(fx.join("\n"))}</div>`; });
  if (d.segments.length) {
    html += `<div class="sec-title">分鏡（${d.segments.length} 段）</div>`;
    html += d.segments.map((s) => `<div class="bubble" style="margin-bottom:6px"><b>${esc(s.id)}</b>　<span style="font-family:var(--mono);color:#c9cdfb">${esc(s.block)}</span>
      <div>${esc(s.script || "")}</div><div style="color:var(--muted);font-size:12px">重點字：${esc((s.key_text || []).join("、"))}　素材：${esc(Object.values(s.media || {}).join("、") || "—")}</div></div>`).join("");
  }
  setDetail(html || '<div class="empty">企劃中…</div>');
}

async function loadDetail() {
  const s = st.data?.segments.find((x) => x.id === st.seg);
  if (!s) return;
  $("#detailTitle").textContent = `${s.id} · ${s.block || ""}`;
  $("#detailMeta").textContent = `${STATE[s.state] || s.state}${s.shots ? ` · 截圖 ${s.shots} 次` : ""}${s.seconds ? ` · ${s.seconds} 秒` : ""}`;
  if (!s.sub) { setDetail('<div class="empty">這段的 Agent 還沒開始</div>'); return; }
  const conv = await getJSON(`/api/conversations/${encodeURIComponent(s.sub)}`);
  setDetail(checkPanel(s) + renderConversation(conv.messages || [], s));
}

// 自我檢查表（只看畫面就能判斷的固定項目）＋待真人確認（需要背景知識的項目，勾選記在這台瀏覽器）
const CHECK_LABEL = { text_cut: "文字超出／被切", overlap: "文字或圖片重疊", empty_slot: "空的素材框", tiny_text: "字太小",
  person_cropped: "人物被切到臉", edge_artifact: "去背白邊／色塊", comma_year: "年份有逗號", leftover_words: "範本禁用字" };
function humanKey(s, i) { return `hc:${st.run}:${s.id}:${i}`; }
function isChecked(k) { try { return localStorage.getItem(k) === "1"; } catch { return false; } }
function checkPanel(s) {
  let html = "";
  if (s.checks) {
    html += `<div class="sec-title" style="margin-top:0">自我檢查表（模型看截圖回答）</div><div class="checks">` +
      Object.entries(CHECK_LABEL).map(([k, v]) => {
        const bad = s.checks[k] === true, na = typeof s.checks[k] !== "boolean";
        return `<span class="chk ${na ? "na" : bad ? "bad" : "ok"}">${na ? "？" : bad ? "✗" : "✓"} ${v}</span>`;
      }).join("") + "</div>";
  }
  if (s.human_check && s.human_check.length) {
    html += `<div class="sec-title">待真人確認（需要背景知識，模型不判斷）</div><div class="human">` +
      s.human_check.map((t, i) => `<label class="hc"><input type="checkbox" data-hc="${esc(humanKey(s, i))}" ${isChecked(humanKey(s, i)) ? "checked" : ""}/> ${esc(t)}</label>`).join("") + "</div>";
  }
  return html;
}

function renderConversation(msgs, s) {
  const results = {};
  msgs.filter((m) => m.role === "tool").forEach((m) => { results[m.tool_call_id] = m; });
  let html = "";
  msgs.forEach((m, i) => {
    if (m.role === "tool") return;
    if (m.role === "user") {
      html += `<div class="msg"><div class="who"><b>程式</b> 交給這段 Agent 的任務</div>
        <div class="bubble prompt ${st.openKeys.has("p" + i) ? "open" : ""}" data-key="p${i}">${esc(m.content)}</div></div>`;
      return;
    }
    let body = "";
    if (m.reasoning) body += fold(`t${i}`, "think", `💭 思考過程 <span class="badge">${m.usage?.reasoning ?? m.reasoning.length} tokens</span>`, esc(m.reasoning));
    const text = String(m.content || "").replace(/<\?final>/g, "").trim();
    if (text) body += `<div class="bubble ${/<\?final>/.test(m.content || "") ? "final" : ""}">${esc(text)}</div>`;
    (m.tool_calls || []).forEach((tc) => {
      const r = results[tc.id];
      let parsed = null;
      try { parsed = JSON.parse(r?.content || "null"); } catch { parsed = null; }
      const ok = !r ? "" : parsed && parsed.ok === false ? "fail" : "ok";
      const shot = parsed && parsed.attach_image;
      body += fold(`c${tc.id}`, `tool ${ok}`,
        `<span class="st"></span><span class="tn">${esc(tc.function.name)}</span><span class="ta">${esc(argText(tc.function.arguments))}</span>`,
        `<div class="lb">參數</div><pre>${esc(pretty(tc.function.arguments))}</pre>
         <div class="lb">結果${r ? "" : "（執行中…）"}</div><pre>${esc(r ? pretty(r.content) : "")}</pre>`)
        + (shot ? `<img class="shot" src="${fileUrl(shot)}" data-full="${esc(shot)}" alt="截圖" />` : "");
    });
    if (body) html += `<div class="msg"><div class="who"><b>${esc(s.id)} Agent</b>${m.usage ? ` · 輸出 ${m.usage.completion} tokens` : ""}</div>${body}</div>`;
  });
  return html;
}
const pretty = (t) => { try { return JSON.stringify(JSON.parse(t), null, 1); } catch { return String(t ?? ""); } };
function argText(a) {
  try { const o = JSON.parse(a || "{}"); return o.args ? o.args.join(" ") : Object.entries(o).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(" "); }
  catch { return a; }
}
function setDetail(html) {
  if (html === st.lastDetail) return;  // 沒變就不重畫，避免捲動位置跳掉
  const feed = $("#detail");
  const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
  feed.innerHTML = html; st.lastDetail = html;
  if (atBottom) feed.scrollTop = feed.scrollHeight;
}

// ---------- 4. 進度與分派 ----------
function renderOverview(d) {
  const segs = d.segments;
  const done = segs.filter((s) => !["running", "queued"].includes(s.state)).length;
  const pct = segs.length ? Math.round((done / segs.length) * 100) : 0;
  const icon = { done: "✓", running: "…", todo: "", error: "!" };
  let html = `<div class="sec-title" style="margin-top:0">段落進度</div>
    <div class="progress"><div style="width:${pct}%"></div></div>
    <div class="pmeta"><span>${done} / ${segs.length || "?"} 段</span><span>${pct}%</span></div>
    <ul class="stages">${d.stages.map((s) => `<li class="${s.state}"><span class="ic">${icon[s.state] || ""}</span>${esc(s.label)}</li>`).join("")}</ul>
    <div class="sec-title">分派</div><div class="tree">${treeSvg(segs)}</div>
    <div class="legend">${Object.entries(STATE).map(([k, v]) => `<span><i style="background:${COLOR[k]}"></i>${v}</span>`).join("")}</div>
    <dl class="kv"><dt>模型</dt><dd>${esc(shortModel(d.model))}</dd><dt>風格</dt><dd>${esc(d.theme || "—")}</dd>
      <dt>run</dt><dd title="${esc(d.run_id || "")}">${esc(d.run_id || "—")}</dd>
      <dt>總時間</dt><dd>${d.seconds ? `${Math.floor(d.seconds / 60)} 分 ${d.seconds % 60} 秒` : "執行中"}</dd></dl>`;
  if (d.error) html += `<div class="bubble" style="margin-top:10px;border-left:3px solid var(--red)">${esc(d.error)}</div>`;
  // 狀態區有變才重畫；影片放在獨立的容器，路徑沒變就不動它，播放不會被每 2 秒的更新打斷
  if (html !== st.lastOverview) { $("#ovMain").innerHTML = html; st.lastOverview = html; }
  const box = $("#ovVideo");
  if ((d.video || "") !== (box.dataset.src || "")) {
    box.dataset.src = d.video || "";
    box.innerHTML = d.video ? `<video class="final-video" src="${fileUrl(d.video)}" controls preload="metadata"></video>` : "";
  }
}

function treeSvg(segs) {
  const n = Math.max(segs.length, 1), cols = Math.min(n, 4), rows = Math.ceil(n / cols);
  const W = 300, cw = W / cols, top = 44, rh = 62, H = top + rows * rh + 6, cx = W / 2;
  let lines = "", nodes = "";
  segs.forEach((s, i) => {
    const x = cw * (i % cols) + cw / 2, y = top + Math.floor(i / cols) * rh + 22;
    lines += `<path d="M${cx} 30 C ${cx} ${y - 18}, ${x} ${y - 30}, ${x} ${y - 14}" stroke="#4e5058" fill="none" stroke-width="1.2"/>`;
    nodes += `<g class="tn" data-seg="${esc(s.id)}" style="cursor:pointer">
      <rect x="${x - cw / 2 + 5}" y="${y - 14}" width="${cw - 10}" height="40" rx="6" fill="${COLOR[s.state] || COLOR.queued}" opacity="${s.id === st.seg ? 1 : 0.85}"
        stroke="${s.id === st.seg ? "#fff" : "none"}" stroke-width="1.5"/>
      <text class="node-label" x="${x}" y="${y + 2}" text-anchor="middle">${esc(s.id.replace("seg_", "第 ") + " 段")}</text>
      <text class="node-sub" x="${x}" y="${y + 16}" text-anchor="middle" fill="#1e1f22">${esc(String(s.block || "").replace("pk-", "").slice(0, 12))}</text></g>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="企劃分派到各段">
    ${lines}<g class="tn" data-seg="" style="cursor:pointer"><rect x="${cx - 52}" y="4" width="104" height="26" rx="6" fill="#5865f2"/>
    <text class="node-label" x="${cx}" y="21" text-anchor="middle">企劃 Agent</text></g>${nodes}</svg>`;
}

// ---------- 事件 ----------
$("#sessions").addEventListener("click", (e) => { const it = e.target.closest(".sess"); if (it) selectRun(it.dataset.id); });
function pickSeg(id) { st.seg = id || null; st.lastDetail = ""; loadRun(); }
$("#segs").addEventListener("click", (e) => {
  const img = e.target.closest("img[data-full]");
  if (img) { e.stopPropagation(); return lightbox(img.dataset.full); }
  const c = e.target.closest(".seg"); if (c) pickSeg(c.dataset.seg);
});
$("#overview").addEventListener("click", (e) => { const g = e.target.closest(".tn"); if (g) pickSeg(g.dataset.seg); });
$("#detail").addEventListener("change", (e) => {
  const cb = e.target.closest("input[data-hc]");
  if (!cb) return;
  try { cb.checked ? localStorage.setItem(cb.dataset.hc, "1") : localStorage.removeItem(cb.dataset.hc); } catch { /* 無痕模式 */ }
  st.lastDetail = "";
});
$("#detail").addEventListener("click", (e) => {
  const img = e.target.closest("img[data-full]");
  if (img) return lightbox(img.dataset.full);
  const h = e.target.closest(".fold > .h, .prompt");
  if (!h) return;
  const box = h.classList.contains("prompt") ? h : h.parentElement;
  const now = box.classList.toggle("open");
  now ? st.openKeys.add(box.dataset.key) : st.openKeys.delete(box.dataset.key);
  st.lastDetail = "";
});
function lightbox(p) {
  const lb = $("#lightbox"), vid = /\.(mp4|webm)$/i.test(p);
  lb.className = "lightbox on " + (vid ? "vid" : "img");
  if (vid) $("#lbVid").src = fileUrl(p); else $("#lbImg").src = fileUrl(p);
}
$("#lightbox").addEventListener("click", () => { $("#lightbox").className = "lightbox"; $("#lbVid").pause(); });

loadSessions();
setInterval(loadSessions, 5000);
setInterval(loadRun, 2000);
