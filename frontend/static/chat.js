// GlobeTrotter / Kribi Tour — chat client.
// Community room + private 1:1 conversations, realtime with Socket.IO.
const el = (id) => document.getElementById(id);
const authToken = localStorage.getItem("gt_token");
let socket = null;
let myUserId = null;
let activeConversationId = null;
let activePeerName = null;

function decodeJwtPayload(token) {
  try {
    const b64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(atob(b64).split("").map(c => "%" + c.charCodeAt(0).toString(16).padStart(2, "0")).join("")));
  } catch (_) { return null; }
}

async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const resp = await fetch(path, { ...options, headers });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || `Request failed (${resp.status})`);
  return data;
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : String(s);
  return div.innerHTML;
}

function appendMessage(msg, senderNameOverride) {
  const box = el("chat-messages");
  const mine = Number(msg.sender_id) === Number(myUserId);
  const label = senderNameOverride || (mine ? "Vous" : activePeerName || "Utilisateur");
  const div = document.createElement("div");
  div.className = `chat-msg ${mine ? "mine" : "theirs"}`;
  div.innerHTML = `${escapeHtml(msg.text)}<span class="chat-meta">${mine ? "" : escapeHtml(label)}</span>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function connectChat() {
  const payload = decodeJwtPayload(authToken);
  myUserId = payload ? Number(payload.sub ?? payload.user_id) : null;
  const socketUrl = window.GT_CHAT_SOCKET_URL || window.location.origin;
  socket = io(socketUrl, { path: "/socket.io/", query: { token: authToken }, transports: ["websocket", "polling"] });

  socket.on("connect", () => {
    el("chat-connection-label").className = "badge text-bg-success";
    el("chat-connection-label").textContent = "🟢 Connecté";
  });
  socket.on("disconnect", () => {
    el("chat-connection-label").className = "badge text-bg-danger";
    el("chat-connection-label").textContent = "🔴 Déconnecté";
  });
  socket.on("connect_error", () => {
    el("chat-connection-label").className = "badge text-bg-warning";
    el("chat-connection-label").textContent = "🟠 Chat indisponible";
  });
  socket.on("presence", (data) => { el("chat-presence").textContent = `${data.online_count || 0} utilisateur(s) en ligne`; });
  socket.on("community_message", (msg) => { if (activeConversationId === null) appendMessage(msg, msg.sender_name); });
  socket.on("new_message", (msg) => { if (Number(activeConversationId) === Number(msg.conversation_id)) appendMessage(msg); });
  socket.on("conversation_updated", loadConversations);
  socket.on("error", (e) => console.warn("chat error:", e && e.error));
}

async function openCommunity() {
  activeConversationId = null;
  activePeerName = null;
  el("chat-header-title").textContent = "🌍 Communauté";
  document.querySelectorAll(".chat-thread-item, .chat-tab-btn").forEach(x => x.classList.remove("active"));
  el("chat-tab-community").classList.add("active");
  const box = el("chat-messages");
  box.innerHTML = '<p class="text-muted">Chargement…</p>';
  try {
    const history = await apiFetch("/community/messages");
    box.innerHTML = "";
    history.forEach(m => appendMessage(m, m.sender_name));
  } catch (_) {
    box.innerHTML = '<p class="text-danger">Impossible de charger la discussion communautaire.</p>';
  }
}

async function openConversation(conversationId, peerName) {
  activeConversationId = conversationId;
  activePeerName = peerName;
  el("chat-header-title").textContent = `💬 ${peerName}`;
  document.querySelectorAll(".chat-thread-item, .chat-tab-btn").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(`[data-cid="${conversationId}"]`).forEach(x => x.classList.add("active"));
  if (socket) socket.emit("join_conversation", { conversation_id: conversationId });
  const box = el("chat-messages");
  box.innerHTML = '<p class="text-muted">Chargement…</p>';
  try {
    const history = await apiFetch(`/conversations/${conversationId}/messages`);
    box.innerHTML = "";
    history.forEach(m => appendMessage(m));
  } catch (_) {
    box.innerHTML = '<p class="text-danger">Impossible de charger les messages.</p>';
  }
}

async function loadConversations() {
  const list = el("chat-thread-list");
  try {
    const conversations = await apiFetch("/conversations");
    list.innerHTML = conversations.map(c => `
      <div class="chat-thread-item" data-cid="${c.id}">
        <span>${c.peer_online ? '<span class="chat-online-dot"></span>' : ''}${escapeHtml(c.peer_username)}</span>
      </div>
    `).join("") || '<p class="text-muted" style="font-size:.85rem;">Aucun message privé pour le moment.</p>';
    list.querySelectorAll(".chat-thread-item").forEach(item => {
      item.addEventListener("click", () => {
        const c = conversations.find(x => String(x.id) === String(item.dataset.cid));
        if (c) openConversation(c.id, c.peer_username);
      });
    });
  } catch (_) {
    list.innerHTML = '<p class="text-danger">Impossible de charger vos conversations.</p>';
  }
}

async function searchPeople() {
  const q = el("chat-people-search").value.trim();
  const results = el("chat-people-results");
  if (!q) { results.innerHTML = ""; return; }
  try {
    const people = await apiFetch(`/users/search?q=${encodeURIComponent(q)}`);
    results.innerHTML = people.map(p => `
      <div class="chat-thread-item" data-uid="${p.id}" data-uname="${escapeHtml(p.username)}">${escapeHtml(p.username)}</div>
    `).join("") || '<p class="text-muted" style="font-size:.8rem;">Aucun résultat.</p>';
    results.querySelectorAll(".chat-thread-item").forEach(item => {
      item.addEventListener("click", () => startConversation(Number(item.dataset.uid), item.dataset.uname));
    });
  } catch (_) { results.innerHTML = '<p class="text-danger">Recherche impossible.</p>'; }
}

async function startConversation(peerId, peerUsername) {
  try {
    const convo = await apiFetch("/conversations", { method: "POST", body: JSON.stringify({ peer_id: peerId }) });
    await loadConversations();
    openConversation(convo.id, peerUsername);
    el("chat-people-search").value = "";
    el("chat-people-results").innerHTML = "";
  } catch (e) { alert(e.message); }
}

function sendMessage() {
  const input = el("chat-input");
  const text = input.value.trim();
  if (!text || !socket || !socket.connected) return;
  if (activeConversationId === null) socket.emit("send_community", { text });
  else socket.emit("send_message", { conversation_id: activeConversationId, text });
  input.value = "";
}

if (!authToken) {
  el("chat-locked-state").classList.remove("hidden");
} else {
  el("chat-shell").classList.remove("hidden");
  el("chat-locked-state").classList.add("hidden");
  connectChat();
  loadConversations();
  openCommunity();
  el("chat-send-btn").addEventListener("click", sendMessage);
  el("chat-input").addEventListener("keydown", e => { if (e.key === "Enter") sendMessage(); });
  el("chat-tab-community").addEventListener("click", openCommunity);
  el("chat-people-search").addEventListener("input", () => {
    clearTimeout(window._searchDebounce);
    window._searchDebounce = setTimeout(searchPeople, 250);
  });
}
