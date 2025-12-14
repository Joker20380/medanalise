/* chat_widget.js — Glass chat widget (AUTH + GUEST MODE)
 *
 * AUTH:
 *  - Bootstrap: GET /chat/api/bootstrap/
 *  - Messages (heavy long-poll only when chat open): GET /chat/api/messages/?after_id=...&timeout=20
 *  - System (light long-poll even when closed): GET /chat/api/system/?timeout=20 -> {count:N}
 *  - Send: POST /chat/api/send/
 *
 * GUEST:
 *  - Chat UI is visible, but sending is blocked
 *  - On open / focus / submit -> opens #signupChoiceModal (Bootstrap modal)
 */

(() => {
  // ---------------------------
  // DOM
  // ---------------------------
  const root = document.getElementById("chat-widget");
  const fab = document.getElementById("chat-fab");
  const panel = root ? root.querySelector(".chat-panel") : null;
  const messagesEl = document.getElementById("chat-messages");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");

  if (!root || !fab || !panel || !messagesEl || !form || !input) return;

  // ---------------------------
  // Auth mode (from base.html)
  // ---------------------------
  const isAuth = root.getAttribute("data-auth") === "1";

  // ---------------------------
  // Config (URLs from data-attrs when auth; fallback defaults)
  // ---------------------------
  const API = {
    bootstrap: root.getAttribute("data-bootstrap-url") || "/chat/api/bootstrap/",
    messages: root.getAttribute("data-messages-url") || "/chat/api/messages/",
    send: root.getAttribute("data-send-url") || "/chat/api/send/",
    newThread: "/chat/api/new-thread/",
    system: "/chat/api/system/",
  };

  const LONGPOLL_TIMEOUT_SEC = 20;
  const MAX_BACKOFF_MS = 8000;

  // ---------------------------
  // State
  // ---------------------------
  let isOpen = false;
  let threadId = null;

  // heavy messages state
  let lastMessageId = 0;
  let renderedIds = new Set();
  let lpAbort = null;
  let lpRunning = false;
  let lpBackoffMs = 0;
  let lpTimer = null;

  // system notify state (light poll)
  let sysAbort = null;
  let sysRunning = false;
  let sysBackoffMs = 0;
  let sysTimer = null;

  // badge state (system-only)
  let unreadSysCount = 0;
  let badgeEl = null;

  // ---------------------------
  // Utils
  // ---------------------------
  function log() {
    // console.log("[chat]", ...arguments);
  }

  function openSignupModal() {
    // Bootstrap 4 (jQuery)
    if (window.jQuery && jQuery.fn && jQuery.fn.modal) {
      jQuery("#signupChoiceModal").modal("show");
      return true;
    }
    // fallback (если вдруг модалка не подхватилась)
    const el = document.getElementById("signupChoiceModal");
    if (el) {
      el.classList.add("show");
      el.style.display = "block";
    }
    return false;
  }

  function getCookie(name) {
    const m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return m ? m.pop() : "";
  }

  function csrfHeader() {
    const token = getCookie("csrftoken");
    return token ? { "X-CSRFToken": token } : {};
  }

  function escapeHtml(str) {
    return String(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function mapRoleToSender(role) {
    if (role === "user") return "visitor";
    if (role === "assistant") return "operator";
    if (role === "system") return "system";
    return "system";
  }

  function normalizeMessage(m) {
    const id = Number(m.id ?? m.message_id ?? m.pk ?? 0) || 0;

    const role = (m.role ?? "").toString();
    const senderRaw = (m.sender ?? "").toString();
    const sender = role ? mapRoleToSender(role) : (senderRaw || "system");

    const text = (m.content ?? m.text ?? m.message ?? "").toString();

    const author =
      (m.author ??
        (sender === "visitor" ? "Пользователь" : sender === "operator" ? "Оператор" : "Система")
      ).toString();

    const createdAt = m.created_at ?? m.createdAt ?? null;

    return { id, sender, text, author, createdAt };
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // ---------------------------
  // Badge (system-only)
  // ---------------------------
  function ensureBadge() {
    if (badgeEl) return badgeEl;
    badgeEl = document.createElement("span");
    badgeEl.className = "chat-fab-badge";
    badgeEl.style.display = "none";
    fab.appendChild(badgeEl);
    return badgeEl;
  }

  function setSysUnread(count) {
    unreadSysCount = Math.max(0, Number(count || 0));
    const b = ensureBadge();

    if (unreadSysCount > 0 && !isOpen) {
      b.style.display = "inline-flex";
      b.textContent = unreadSysCount > 99 ? "99+" : String(unreadSysCount);
      fab.classList.add("chat-fab--pulse");
    } else {
      b.style.display = "none";
      b.textContent = "";
      fab.classList.remove("chat-fab--pulse");
    }
  }

  function markSysRead() {
    setSysUnread(0);
  }

  // ---------------------------
  // Render
  // ---------------------------
  function clearMessagesUi() {
    messagesEl.innerHTML = "";
    renderedIds = new Set();
    lastMessageId = 0;
  }

  function renderSystemLine(text, level) {
    const lvl = (level || "info").toLowerCase();

    const item = document.createElement("div");
    item.className = `chat-msg chat-msg--system chat-msg--${lvl}`;

    const safe = escapeHtml(text).replaceAll("\n", "<br>");

    item.innerHTML = `
      <div class="chat-msg__bubble">
        <div class="chat-msg__author">Система</div>
        <div class="chat-msg__text">${safe}</div>
      </div>
    `;

    messagesEl.appendChild(item);
    if (isOpen) scrollToBottom();
  }

  function renderMessage(msg) {
    const m = normalizeMessage(msg);
    if (!m.text) return;

    if (m.id) {
      if (renderedIds.has(m.id)) return;
      renderedIds.add(m.id);
      if (m.id > lastMessageId) lastMessageId = m.id;
    }

    const item = document.createElement("div");
    item.className = `chat-msg chat-msg--${m.sender}`;

    const safeText = escapeHtml(m.text).replaceAll("\n", "<br>");
    const safeAuthor = escapeHtml(m.author);

    item.innerHTML = `
      <div class="chat-msg__bubble">
        <div class="chat-msg__author">${safeAuthor}</div>
        <div class="chat-msg__text">${safeText}</div>
      </div>
    `;

    messagesEl.appendChild(item);
    if (isOpen) scrollToBottom();
  }

  function renderMessages(list) {
    if (!Array.isArray(list)) return;
    for (const m of list) renderMessage(m);
  }

  // ---------------------------
  // Panel open/close
  // ---------------------------
  function setOpen(open) {
    isOpen = !!open;
    panel.classList.toggle("open", isOpen);
    root.classList.toggle("open", isOpen);

    if (isOpen) {
      markSysRead();
      setTimeout(() => input.focus(), 0);
      scrollToBottom();
    } else {
      stopLongPoll();
    }
  }

  // Close (×) button in header (if visible in CSS)
  const toggleBtn = root.querySelector(".chat-widget-toggle");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", (e) => {
      e.preventDefault();
      setOpen(false);
    });
  }

  // ---------------------------
  // API helpers
  // ---------------------------
  async function apiGet(url, signal) {
    const resp = await fetch(url, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      signal,
    });
    if (!resp.ok) throw new Error(`GET ${url} -> ${resp.status}`);
    return resp.json();
  }

  async function apiPostJson(url, payload) {
    const resp = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...csrfHeader(),
      },
      body: JSON.stringify(payload || {}),
    });
    return resp;
  }

  async function apiPostForm(url, fieldsObj) {
    const body = new URLSearchParams();
    for (const [k, v] of Object.entries(fieldsObj || {})) {
      if (v !== undefined && v !== null) body.set(k, String(v));
    }

    const resp = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        ...csrfHeader(),
      },
      body: body.toString(),
    });
    return resp;
  }

  // ---------------------------
  // Bootstrap (AUTH only)
  // ---------------------------
  async function bootstrap() {
    const data = await apiGet(API.bootstrap);

    threadId = data.thread_id ?? data.threadId ?? threadId;

    clearMessagesUi();

    if (Array.isArray(data.messages)) {
      renderMessages(data.messages);
    }

    if (Array.isArray(data.system_messages)) {
      for (const sm of data.system_messages) {
        const txt = sm.content ?? sm.text ?? "";
        if (txt) renderSystemLine(txt, sm.level || "");
      }
    }

    scrollToBottom();
    log("bootstrap ok", { threadId, lastMessageId });
  }

  // ---------------------------
  // Send message (AUTH only, JSON + fallback)
  // ---------------------------
  async function sendMessage(text) {
    const payload = { text: text, content: text };
    if (threadId) payload.thread_id = threadId;

    try {
      const resp = await apiPostJson(API.send, payload);

      if (resp.status === 415 || resp.status === 400) {
        throw new Error(`JSON not accepted: ${resp.status}`);
      }
      if (!resp.ok) throw new Error(`POST ${API.send} -> ${resp.status}`);

      const data = await resp.json();
      if (data?.system_message) renderSystemLine(data.system_message, "error");
      if (data?.message) renderMessage(data.message);
      if (data?.user_message) renderMessage(data.user_message);
      return data;
    } catch (e) {
      const resp2 = await apiPostForm(API.send, {
        text: text,
        content: text,
        thread_id: threadId || "",
      });
      if (!resp2.ok) throw new Error(`POST(form) ${API.send} -> ${resp2.status}`);

      const data2 = await resp2.json();
      if (data2?.system_message) renderSystemLine(data2.system_message, "error");
      if (data2?.message) renderMessage(data2.message);
      if (data2?.user_message) renderMessage(data2.user_message);
      return data2;
    }
  }

  // ---------------------------
  // Heavy long-poll (messages) — AUTH only, only when open
  // ---------------------------
  function scheduleNextLongPoll(delayMs) {
    if (!lpRunning) return;
    if (lpTimer) clearTimeout(lpTimer);
    lpTimer = setTimeout(() => {
      if (!lpRunning || document.hidden || !isOpen) return;
      longPollOnce();
    }, Math.max(0, delayMs || 0));
  }

  async function longPollOnce() {
    if (!lpRunning || document.hidden || !isOpen) return;

    if (lpAbort) {
      try { lpAbort.abort(); } catch (_) {}
    }
    lpAbort = new AbortController();

    try {
      const url = new URL(API.messages, window.location.origin);
      url.searchParams.set("after_id", String(lastMessageId || 0));
      url.searchParams.set("timeout", String(LONGPOLL_TIMEOUT_SEC));

      const data = await apiGet(url.toString(), lpAbort.signal);

      lpBackoffMs = 0;

      if (data && Array.isArray(data.messages) && data.messages.length) {
        renderMessages(data.messages);
      }

      scheduleNextLongPoll(0);
    } catch (err) {
      if (err && (err.name === "AbortError" || String(err).includes("AbortError"))) return;
      lpBackoffMs = Math.min(lpBackoffMs ? lpBackoffMs * 2 : 500, MAX_BACKOFF_MS);
      scheduleNextLongPoll(lpBackoffMs);
    }
  }

  function startLongPoll() {
    if (!isAuth) return;
    if (lpRunning) return;
    lpRunning = true;
    lpBackoffMs = 0;
    scheduleNextLongPoll(0);
    log("LP (messages) start");
  }

  function stopLongPoll() {
    lpRunning = false;
    if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
    if (lpAbort) { try { lpAbort.abort(); } catch (_) {} lpAbort = null; }
    log("LP (messages) stop");
  }

  // ---------------------------
  // Light long-poll (system count) — AUTH only, always when visible
  // ---------------------------
  function scheduleNextSysPoll(delayMs) {
    if (!sysRunning) return;
    if (sysTimer) clearTimeout(sysTimer);
    sysTimer = setTimeout(() => {
      if (!sysRunning || document.hidden) return;
      sysPollOnce();
    }, Math.max(0, delayMs || 0));
  }

  async function sysPollOnce() {
    if (!sysRunning || document.hidden) return;

    if (sysAbort) {
      try { sysAbort.abort(); } catch (_) {}
    }
    sysAbort = new AbortController();

    try {
      const url = new URL(API.system, window.location.origin);
      url.searchParams.set("timeout", String(LONGPOLL_TIMEOUT_SEC));

      const data = await apiGet(url.toString(), sysAbort.signal);

      sysBackoffMs = 0;

      const cnt = Number(data?.count || 0) || 0;

      if (!isOpen && cnt > 0) {
        setSysUnread(cnt);
      }

      scheduleNextSysPoll(0);
    } catch (err) {
      if (err && (err.name === "AbortError" || String(err).includes("AbortError"))) return;
      sysBackoffMs = Math.min(sysBackoffMs ? sysBackoffMs * 2 : 500, MAX_BACKOFF_MS);
      scheduleNextSysPoll(sysBackoffMs);
    }
  }

  function startSystemPoll() {
    if (!isAuth) return;
    if (sysRunning) return;
    sysRunning = true;
    sysBackoffMs = 0;
    scheduleNextSysPoll(0);
    log("LP (system) start");
  }

  function stopSystemPoll() {
    sysRunning = false;
    if (sysTimer) { clearTimeout(sysTimer); sysTimer = null; }
    if (sysAbort) { try { sysAbort.abort(); } catch (_) {} sysAbort = null; }
    log("LP (system) stop");
  }

  // ---------------------------
  // Events
  // ---------------------------
  fab.addEventListener("click", async () => {
    if (!isOpen) {
      setOpen(true);

      // GUEST MODE
      if (!isAuth) {
        clearMessagesUi();
        renderSystemLine("Чтобы написать в чат, нужно зарегистрироваться или войти.", "info");
        scrollToBottom();
        openSignupModal();
        return;
      }

      // AUTH MODE
      try {
        await bootstrap();
        if (!document.hidden) startLongPoll();
      } catch (e) {
        stopLongPoll();
        renderSystemLine("Не удалось загрузить чат. Обнови страницу или попробуй позже.", "error");
        log("bootstrap failed", e);
      }
    } else {
      setOpen(false);
    }
  });

  // Enter => send, Shift+Enter => newline
  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return;

    if (!isAuth && e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      openSignupModal();
      return;
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (form.requestSubmit) form.requestSubmit();
      else form.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });

  input.addEventListener("focus", () => {
    if (!isAuth) {
      input.blur();
      openSignupModal();
      return;
    }
    if (isOpen) markSysRead();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    // GUEST MODE: block sending + show signup
    if (!isAuth) {
      openSignupModal();
      renderSystemLine("Сначала зарегистрируйся или войди — затем сможешь отправлять сообщения.", "warning");
      return;
    }

    const raw = (input.value || "");
    const text = raw.trimEnd();
    if (!text.trim()) return;

    input.value = "";

    try {
      await sendMessage(text);
      scrollToBottom();
      if (isOpen && !document.hidden) startLongPoll();
    } catch (err) {
      input.value = raw;
      renderSystemLine("Сообщение не отправлено. Проверь соединение и повтори.", "error");
      log("send failed", err);
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (!isAuth) return;
    if (document.hidden) {
      stopSystemPoll();
      stopLongPoll();
    } else {
      startSystemPoll();
      if (isOpen) startLongPoll();
    }
  });

  window.addEventListener("beforeunload", () => {
    stopSystemPoll();
    stopLongPoll();
  });

  // Optional: кнопка "новый диалог" если есть [data-chat-new-thread] (AUTH only)
  const newThreadBtn = root.querySelector("[data-chat-new-thread]");
  if (newThreadBtn) {
    newThreadBtn.addEventListener("click", async () => {
      if (!isAuth) {
        openSignupModal();
        return;
      }
      try {
        const resp = await apiPostJson(API.newThread, {});
        if (!resp.ok) throw new Error(`POST ${API.newThread} -> ${resp.status}`);
        const data = await resp.json();

        threadId = data.thread_id ?? data.threadId ?? null;

        clearMessagesUi();
        if (Array.isArray(data.messages)) renderMessages(data.messages);

        renderSystemLine("Создан новый диалог.", "info");
        scrollToBottom();
      } catch (e) {
        renderSystemLine("Не удалось создать новый диалог.", "error");
        log("newThread failed", e);
      }
    });
  }

  // init
  setOpen(false);

  // Start lightweight system polling immediately (AUTH only)
  if (isAuth && !document.hidden) startSystemPoll();
})();
