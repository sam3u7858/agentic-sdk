const conversationListEl = document.getElementById("conversation-list");
const messageListEl = document.getElementById("message-list");
const eventStreamEl = document.getElementById("event-stream");
const conversationMetaEl = document.getElementById("conversation-meta");
const planningIndicatorEl = document.getElementById("planning-indicator");
const planningLabelEl = document.getElementById("planning-label");
const chatFormEl = document.getElementById("chat-form");
const promptInputEl = document.getElementById("prompt-input");
const maxStepsEl = document.getElementById("max-steps");
const enableGroundingEl = document.getElementById("enable-grounding");
const excludeDomainsEl = document.getElementById("exclude-domains");
const newConversationButtonEl = document.getElementById("new-conversation");
const refreshButtonEl = document.getElementById("refresh-conversations");
const todoListEl = document.getElementById("todo-list");

const messageTemplate = document.getElementById("message-template");
const eventTemplate = document.getElementById("event-template");

let currentConversationId = null;
let eventSource = null;
let awaitingUserReply = false;
let currentRuntimeMeta = null;

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return response.json();
}

function parseExcludeDomains(raw) {
  return String(raw || "")
    .split(",")
    .map((v) => v.trim())
    .filter((v) => v.length > 0);
}

function formatRuntimeMeta(meta) {
  if (!meta || !meta.model) {
    return "";
  }
  const provider = meta.provider ? `${meta.provider} · ` : "";
  return `${provider}${meta.model}`;
}

function createPreBlock(text) {
  const pre = document.createElement("pre");
  pre.className = "message-pre";
  pre.textContent = text || "";
  return pre;
}

function toPreviewText(value, maxLen = 180) {
  const oneLine = String(value || "").replace(/\s+/g, " ").trim();
  if (oneLine.length <= maxLen) {
    return oneLine || "(empty)";
  }
  return `${oneLine.slice(0, maxLen - 3)}...`;
}

function createToolUsageDetails({ title, subtitle, body, open = false, tone = "default" }) {
  const details = document.createElement("details");
  details.className = `tool-usage ${tone}`;
  details.open = open;

  const summary = document.createElement("summary");
  summary.className = "tool-usage-summary";

  const titleEl = document.createElement("span");
  titleEl.className = "tool-usage-title";
  titleEl.textContent = title;
  summary.appendChild(titleEl);

  if (subtitle) {
    const subtitleEl = document.createElement("span");
    subtitleEl.className = "tool-usage-subtitle";
    subtitleEl.textContent = subtitle;
    summary.appendChild(subtitleEl);
  }

  details.appendChild(summary);

  const bodyWrap = document.createElement("div");
  bodyWrap.className = "tool-usage-body";
  bodyWrap.appendChild(createPreBlock(body));
  details.appendChild(bodyWrap);
  return details;
}

function renderMessageContent(message, container) {
  container.innerHTML = "";
  const role = message.role || "unknown";

  if (role === "assistant" && Array.isArray(message.tool_calls) && message.tool_calls.length > 0) {
    const text = (message.content || "").trim();
    if (text) {
      container.appendChild(createPreBlock(text));
    }
    message.tool_calls.forEach((call, idx) => {
      const toolName = call?.function?.name || `tool_${idx + 1}`;
      const args = call?.function?.arguments || "{}";
      container.appendChild(
        createToolUsageDetails({
          title: `Tool Call · ${toolName}`,
          subtitle: `id: ${call?.id || "unknown"}`,
          body: args,
          open: false,
          tone: "request",
        }),
      );
    });
    return;
  }

  if (role === "tool") {
    const toolName = message.name || "unknown_tool";
    const content = message.content || "";
    const isError = String(content).startsWith("Error:");
    container.appendChild(
      createToolUsageDetails({
        title: `Tool Result · ${toolName}`,
        subtitle: isError ? "status: error" : `preview: ${toPreviewText(content, 90)}`,
        body: content,
        open: false,
        tone: isError ? "error" : "result",
      }),
    );
    return;
  }

  container.appendChild(createPreBlock(message.content || ""));
}

function renderEventContent(event, container) {
  container.innerHTML = "";
  const type = event.type || "";

  if (type === "tool_requested") {
    container.appendChild(
      createToolUsageDetails({
        title: `Tool Requested · ${event.tool_name || "unknown"}`,
        subtitle: `step: ${event.step ?? "?"}`,
        body: event.arguments_json || "{}",
        open: false,
        tone: "request",
      }),
    );
    return;
  }

  if (type === "tool_result") {
    const raw = event.content || event.preview || "";
    container.appendChild(
      createToolUsageDetails({
        title: `Tool Result · ${event.tool_name || "unknown"}`,
        subtitle: `step: ${event.step ?? "?"} · ${toPreviewText(raw, 90)}`,
        body: raw,
        open: false,
        tone: String(raw).startsWith("Error:") ? "error" : "result",
      }),
    );
    return;
  }

  if (type === "todo_updated") {
    const snap = event.todo_snapshot || { items: [] };
    const body = JSON.stringify(snap, null, 2);
    container.appendChild(
      createToolUsageDetails({
        title: "TODO updated",
        subtitle: `${Array.isArray(snap.items) ? snap.items.length : 0} items`,
        body,
        open: false,
        tone: "result",
      }),
    );
    return;
  }

  if (type === "tool_progress") {
    const debugBody = JSON.stringify(event, null, 2);
    const summaryText = event.message || toPreviewText(debugBody, 90);
    container.appendChild(
      createToolUsageDetails({
        title: `Tool Progress · ${event.tool_name || "unknown"}`,
        subtitle: `step: ${event.step ?? "?"} · ${summaryText}`,
        body: debugBody,
        open: false,
        tone: "result",
      }),
    );
    return;
  }

  if (type === "tool_result_compressed") {
    container.appendChild(
      createToolUsageDetails({
        title: `Tool Compression · ${event.tool_name || "unknown"}`,
        subtitle: `step: ${event.step ?? "?"} · ${event.estimated_tokens_before ?? "?"} -> ${event.estimated_tokens_after ?? "?"}`,
        body: JSON.stringify(event, null, 2),
        open: false,
        tone: "result",
      }),
    );
    return;
  }

  if (type === "assistant_content_compressed") {
    container.appendChild(
      createToolUsageDetails({
        title: "Assistant Compression",
        subtitle: `step: ${event.step ?? "?"} · ${event.estimated_tokens_before ?? "?"} -> ${event.estimated_tokens_after ?? "?"}`,
        body: JSON.stringify(event, null, 2),
        open: false,
        tone: "result",
      }),
    );
    return;
  }

  container.appendChild(createPreBlock(JSON.stringify(event, null, 2)));
}

function renderConversations(items) {
  conversationListEl.innerHTML = "";
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "conversation-item";
    if (item.conversation_id === currentConversationId) {
      button.classList.add("active");
    }
    button.innerHTML = `
      <div class="conversation-id">${item.conversation_id}</div>
      <div class="conversation-preview">${item.preview || "No preview"}</div>
    `;
    button.addEventListener("click", () => loadConversation(item.conversation_id));
    conversationListEl.appendChild(button);
  }
}

function renderTodoSnapshot(snapshot) {
  if (!todoListEl) {
    return;
  }
  todoListEl.innerHTML = "";
  const items = Array.isArray(snapshot?.items) ? snapshot.items : [];
  if (items.length === 0) {
    const li = document.createElement("li");
    li.className = "todo-item";
    li.textContent = "（尚無項目）";
    todoListEl.appendChild(li);
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    li.className = `todo-item${item.done ? " done" : ""}`;
    const idSpan = document.createElement("span");
    idSpan.className = "todo-id";
    idSpan.textContent = item.id || "?";
    const textSpan = document.createElement("span");
    textSpan.className = "todo-text";
    textSpan.textContent = item.text || "";
    li.appendChild(idSpan);
    li.appendChild(textSpan);
    todoListEl.appendChild(li);
  }
}

async function loadTodosForConversation(conversationId) {
  if (!conversationId || !todoListEl) {
    return;
  }
  try {
    const data = await fetchJson(`/api/conversations/${encodeURIComponent(conversationId)}/todos`);
    renderTodoSnapshot(data);
  } catch {
    renderTodoSnapshot({ items: [] });
  }
}

function renderMessages(messages) {
  messageListEl.innerHTML = "";
  for (const message of messages) {
    const fragment = messageTemplate.content.cloneNode(true);
    const article = fragment.querySelector(".message");
    const roleEl = fragment.querySelector(".message-role");
    const contentEl = fragment.querySelector(".message-content");
    const role = message.role || "unknown";
    article.classList.add(role);
    roleEl.textContent = role;
    renderMessageContent(message, contentEl);
    messageListEl.appendChild(fragment);
  }
  messageListEl.scrollTop = messageListEl.scrollHeight;
}

function appendEvent(event) {
  const fragment = eventTemplate.content.cloneNode(true);
  fragment.querySelector(".event-type").textContent = event.type;
  const contentEl = fragment.querySelector(".event-content");
  renderEventContent(event, contentEl);
  eventStreamEl.appendChild(fragment);
  eventStreamEl.scrollTop = eventStreamEl.scrollHeight;
}

function appendGroundingCitations(event) {
  const citations = Array.isArray(event.citations) ? event.citations : [];
  const queries = Array.isArray(event.web_search_queries) ? event.web_search_queries : [];
  const lines = [];
  if (queries.length > 0) {
    lines.push(`queries: ${queries.join(" | ")}`);
  }
  if (citations.length > 0) {
    lines.push("citations:");
    citations.forEach((item, idx) => {
      lines.push(`${idx + 1}. ${item.title || item.uri}`);
      lines.push(`   ${item.uri || ""}`);
    });
  } else {
    lines.push("citations: none");
  }
  appendEvent({
    type: "grounding_citations_view",
    content: lines.join("\n"),
    step: event.step,
  });
}

async function loadConversations() {
  const items = await fetchJson("/api/conversations");
  renderConversations(items);
}

async function loadConversation(conversationId, options = {}) {
  const { preserveStream = false, preserveAwaitingState = false } = options;
  if (!preserveStream) {
    closeStream();
  }
  if (!preserveAwaitingState) {
    setAwaitingUserState(false);
  }
  currentConversationId = conversationId;
  const conversation = await fetchJson(`/api/conversations/${conversationId}`);
  currentRuntimeMeta = conversation.runtime_meta || null;
  const runtimeText = formatRuntimeMeta(currentRuntimeMeta);
  conversationMetaEl.textContent = runtimeText
    ? `${conversationId} | ${conversation.messages.length} messages | ${runtimeText}`
    : `${conversationId} | ${conversation.messages.length} messages`;
  renderMessages(conversation.messages || []);
  await loadTodosForConversation(conversationId);
  await loadConversations();
}

function closeStream() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  if (!awaitingUserReply) {
    setPlanningState(false);
  }
}

function setPlanningState(isPlanning, label = "Planning Next Step") {
  planningLabelEl.textContent = label;
  planningIndicatorEl.classList.toggle("hidden", !isPlanning);
}

function setAwaitingUserState(isAwaiting) {
  awaitingUserReply = isAwaiting;
  promptInputEl.classList.toggle("awaiting-user", isAwaiting);
  const runtimeText = formatRuntimeMeta(currentRuntimeMeta);
  if (isAwaiting) {
    setPlanningState(true, "Waiting For Your Reply");
    conversationMetaEl.textContent = runtimeText
      ? `${currentConversationId} | waiting for your reply | ${runtimeText}`
      : `${currentConversationId} | waiting for your reply`;
    promptInputEl.focus();
    return;
  }
  setPlanningState(false);
}

function resetConversationView() {
  closeStream();
  currentConversationId = null;
  currentRuntimeMeta = null;
  setAwaitingUserState(false);
  conversationMetaEl.textContent = "新對話";
  messageListEl.innerHTML = "";
  eventStreamEl.innerHTML = "";
  renderTodoSnapshot({ items: [] });
  promptInputEl.focus();
}

function openStream(conversationId) {
  closeStream();
  eventStreamEl.innerHTML = "";
  setAwaitingUserState(false);
  setPlanningState(true, "Planning Next Step");
  eventSource = new EventSource(`/api/stream/${conversationId}`);
  eventSource.onmessage = async (event) => {
    const payload = JSON.parse(event.data);
    appendEvent(payload);
    if (payload.type === "run_started") {
      currentRuntimeMeta = {
        provider: payload.provider || "",
        model: payload.model || "",
      };
      const runtimeText = formatRuntimeMeta(currentRuntimeMeta);
      if (runtimeText && currentConversationId) {
        conversationMetaEl.textContent = `${currentConversationId} | running... | ${runtimeText}`;
      }
    }
    if (payload.type === "grounding_citations") {
      appendGroundingCitations(payload);
    }
    if (payload.type === "awaiting_user") {
      setAwaitingUserState(true);
    } else if (payload.type === "final_answer" || payload.type === "run_finished" || payload.type === "error") {
      setAwaitingUserState(false);
    }
    if (payload.type === "todo_updated" && payload.todo_snapshot) {
      renderTodoSnapshot(payload.todo_snapshot);
    }
    if (payload.type === "tool_progress") {
      return;
    }
    await loadConversation(conversationId, {
      preserveStream: true,
      preserveAwaitingState: true,
    });
  };
  eventSource.addEventListener("done", () => {
    closeStream();
  });
  eventSource.onerror = () => {
    closeStream();
  };
}

chatFormEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = promptInputEl.value.trim();
  if (!prompt) {
    return;
  }

  const payload = {
    prompt,
    max_steps: Number(maxStepsEl.value) || 12,
  };
  const enableGrounding = Boolean(enableGroundingEl?.checked);
  const excludeDomains = parseExcludeDomains(excludeDomainsEl?.value);
  if (enableGrounding) {
    payload.enable_google_search_grounding = true;
    // Avoid duplicate search channels by default when grounding is enabled.
    payload.enable_web_search_tool = false;
  }
  if (excludeDomains.length > 0) {
    payload.google_search_exclude_domains = excludeDomains;
  }
  if (currentConversationId) {
    payload.conversation_id = currentConversationId;
  }
  const data = await fetchJson("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  promptInputEl.value = "";
  currentConversationId = data.conversation_id;
  currentRuntimeMeta = data.runtime_meta || null;
  setAwaitingUserState(false);
  const runtimeText = formatRuntimeMeta(currentRuntimeMeta);
  conversationMetaEl.textContent = runtimeText
    ? `${currentConversationId} | running... | ${runtimeText}`
    : `${currentConversationId} | running...`;
  await loadConversations();
  openStream(currentConversationId);
});

refreshButtonEl.addEventListener("click", async () => {
  await loadConversations();
  if (currentConversationId) {
    await loadConversation(currentConversationId);
  }
});

newConversationButtonEl.addEventListener("click", async () => {
  resetConversationView();
  await loadConversations();
});

loadConversations().catch((error) => {
  appendEvent({ type: "ui_error", message: error.message });
});
