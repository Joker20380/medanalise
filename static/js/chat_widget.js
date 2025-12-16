/* =========================================================
   CHAT WIDGET — FINAL STABLE (guest-safe) + SEND FALLBACK + TIME
   ========================================================= */

(() => {
  const root = document.getElementById("chat-widget");
  if (!root) return;

  const fab       = document.getElementById("chat-fab");
  const panel     = root.querySelector(".chat-panel");
  const messages  = document.getElementById("chat-messages");
  const form      = document.getElementById("chat-form");
  const input     = document.getElementById("chat-input");
  const closeBtn  = root.querySelector(".chat-widget-toggle");

  if (!fab || !panel || !messages || !form || !input) return;

  const API = {
    bootstrap: root.dataset.bootstrapUrl || "/chat/api/bootstrap/",
    messages:  root.dataset.messagesUrl  || "/chat/api/messages/",
    send:      root.dataset.sendUrl      || "/chat/api/send/",
  };

  const POLL_TIMEOUT = 20;

  const isAuthed = () => root.dataset.auth === "1";

  let isOpen = false;
  let threadId = null;
  let lastMessageId = 0;
  let rendered = new Set();
  let pollAbort = null;

  const DRAFT_KEY = "chat_guest_draft";
  const saveDraft = text => { if (text) localStorage.setItem(DRAFT_KEY, text); };
  const loadDraft = () => localStorage.getItem(DRAFT_KEY) || "";
  const clearDraft = () => localStorage.removeItem(DRAFT_KEY);

  const esc = s =>
    String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  const scrollBottom = () => { messages.scrollTop = messages.scrollHeight; };

  function getCookie(name) {
    const m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return m ? m.pop() : "";
  }

  function csrfHeader() {
    const token = getCookie("csrftoken");
    return token ? { "X-CSRFToken": token } : {};
  }

  function fmtTime(value) {
    if (!value) return "";
    let d = null;
    if (value instanceof Date) d = value;
    else if (typeof value === "number") d = new Date(value);
    else if (typeof value === "string") {
      const t = Date.parse(value);
      if (!Number.isNaN(t)) d = new Date(t);
    }
    if (!d) return "";
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  }

  function mapRoleToSender(role) {
    const r = (role || "").toString().toLowerCase();
    if (r === "user") return "visitor";
    if (r === "assistant") return "operator";
    if (r === "system") return "system";
    return "";
  }

  function normalizeMessage(m) {
    if (!m) return null;

    const id = Number(m.id ?? m.message_id ?? m.pk ?? 0) || 0;

    const role = (m.role ?? "").toString();
    const senderRaw = (m.sender ?? "").toString();
    const sender =
      (senderRaw && senderRaw.toLowerCase()) ||
      mapRoleToSender(role) ||
      "operator"; // важно: не system по умолчанию

    const text = (m.text ?? m.content ?? m.message ?? "").toString();

    const author =
      (m.author ?? m.username ?? "").toString() ||
      (sender === "visitor" ? "Пользователь" :
       sender === "operator" ? "Оператор" : "Система");

    const createdAt = m.created_at ?? m.createdAt ?? m.created ?? null;

    return { id, sender, text, author, createdAt };
  }

  function renderMessage(raw, level = null) {
    const m = normalizeMessage(raw);
    if (!m || !m.text) return;

    if (m.id && rendered.has(m.id)) return;
    if (m.id) rendered.add(m.id);
    if (m.id > lastMessageId) lastMessageId = m.id;

    const timeStr = fmtTime(m.createdAt);

    const el = document.createElement("div");
    el.className =
      `chat-msg chat-msg--${m.sender}` +
      (level ? ` chat-msg--${level}` : "");

    el.innerHTML = `
      <div class="chat-msg__bubble">
        <div class="chat-msg__meta" style="display:flex; align-items:baseline; justify-content:space-between; gap:10px;">
          <span class="chat-msg__author">${esc(m.author)}</span>
          ${timeStr ? `<span class="chat-msg__time" style="font-size:10px; font-weight:600; opacity:.6;">${esc(timeStr)}</span>` : ""}
        </div>
        <div class="chat-msg__text">${esc(m.text).replace(/\n/g, "<br>")}</div>
      </div>
    `;

    messages.appendChild(el);
    scrollBottom();
  }

  const system = (text, lvl = "info") =>
    renderMessage({ text, sender: "system", author: "Система" }, lvl);

  async function bootstrapChat() {
    const r = await fetch(API.bootstrap, { credentials: "same-origin", cache: "no-store" });
    if (!r.ok) throw new Error(`bootstrap ${r.status}`);
    const d = await r.json();

    threadId = d.thread_id || d.threadId || null;

    messages.innerHTML = "";
    rendered.clear();
    lastMessageId = 0;

    (d.messages || []).forEach(m => renderMessage(m));
    (d.system_messages || []).forEach(m =>
      system(m.content || m.text || "", (m.level || "info"))
    );

    scrollBottom();
  }

  async function poll() {
    if (!isOpen || !isAuthed()) return;

    pollAbort = new AbortController();

    try {
      const url = new URL(API.messages, location.origin);
      url.searchParams.set("after_id", String(lastMessageId || 0));
      url.searchParams.set("timeout", String(POLL_TIMEOUT));

      const r = await fetch(url, {
        credentials: "same-origin",
        signal: pollAbort.signal,
        cache: "no-store",
      });

      if (!r.ok) throw new Error(`poll ${r.status}`);

      const d = await r.json();
      (d.messages || []).forEach(m => renderMessage(m));

      poll();
    } catch (_) {
      // тихо
    }
  }

  function openChat() {
    isOpen = true;
    panel.classList.add("open");

    if (isAuthed()) {
      bootstrapChat().then(poll).catch(() => {
        system("Не удалось загрузить чат. Обнови страницу или попробуй позже.", "error");
      });

      const draft = loadDraft();
      if (draft) {
        input.value = draft;
        clearDraft();
      }
      setTimeout(() => input.focus(), 0);
    } else {
      system("Чтобы написать — войдите или зарегистрируйтесь.", "info");
      setTimeout(() => input.focus(), 0);
    }
  }

  function closeChat() {
    isOpen = false;
    panel.classList.remove("open");
    if (pollAbort) {
      try { pollAbort.abort(); } catch (_) {}
      pollAbort = null;
    }
  }

  fab.onclick = () => (isOpen ? closeChat() : openChat());
  if (closeBtn) closeBtn.onclick = closeChat;

  // Enter => submit, Shift+Enter => newline
  input.addEventListener("keydown", e => {
    if (e.isComposing) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (form.requestSubmit) form.requestSubmit();
      else form.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });

  async function postJsonOrThrow(url, payload) {
    const r = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...csrfHeader(),
      },
      body: JSON.stringify(payload || {}),
    });
    if (!r.ok) {
      const txt = await r.text().catch(() => "");
      const err = new Error(`send(json) ${r.status}`);
      err.status = r.status;
      err.body = txt;
      throw err;
    }
    return r.json();
  }

  async function postFormOrThrow(url, fields) {
    const body = new URLSearchParams();
    Object.entries(fields || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null) body.set(k, String(v));
    });

    const r = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        ...csrfHeader(),
      },
      body: body.toString(),
    });

    if (!r.ok) {
      const txt = await r.text().catch(() => "");
      const err = new Error(`send(form) ${r.status}`);
      err.status = r.status;
      err.body = txt;
      throw err;
    }
    return r.json();
  }

  form.addEventListener("submit", async e => {
    e.preventDefault();

    const raw = input.value || "";
    const text = raw.trim();
    if (!text) return;

    if (!isAuthed()) {
      saveDraft(text);
      if (window.jQuery && document.getElementById("signupChoiceModal")) {
        window.jQuery("#signupChoiceModal").modal("show");
      } else {
        location.href = "/accounts/login/";
      }
      return;
    }

    input.value = "";

    // payload: поддержим оба ключа (твой бек мог ждать text или content)
    const payload = { text, content: text };
    if (threadId) payload.thread_id = threadId;

    try {
      let d;
      try {
        d = await postJsonOrThrow(API.send, payload);
      } catch (err) {
        // Если бек не принимает JSON (415/400) или CSRF/прочее — пробуем form
        console.warn("[chat] json send failed:", err.status, err.body);
        d = await postFormOrThrow(API.send, payload);
      }

      if (d.user_message) renderMessage(d.user_message);
      else if (d.message) renderMessage(d.message);
      else if (d.error) system(d.error, "error");

      (d.system_messages || []).forEach(m =>
        system(m.content || m.text || "", (m.level || "info"))
      );
    } catch (err2) {
      console.error("[chat] send failed окончательно:", err2.status, err2.body);
      system("Сообщение не отправлено", "error");
      input.value = raw; // вернуть текст, чтобы не потерять
    }
  });
})();
