const form = document.getElementById("chat-form");
const providerSelect = document.getElementById("provider");
const modelSelect = document.getElementById("model");
const modeSelect = document.getElementById("mode");
const sessionInput = document.getElementById("provider_session_ref");
const workspaceInput = document.getElementById("workspace_path");
const promptInput = document.getElementById("prompt");
const streamInput = document.getElementById("stream");
const consoleEl = document.getElementById("console");
const sessionRefEl = document.getElementById("session-ref");
const eventCountEl = document.getElementById("event-count");
const healthStatusEl = document.getElementById("health-status");
const shellPathEl = document.getElementById("shell-path");
const bashVersionEl = document.getElementById("bash-version");
const workerCountEl = document.getElementById("worker-count");
const workerListEl = document.getElementById("worker-list");
const requestMetaEl = document.getElementById("request-meta");
const sendButton = document.getElementById("send-button");
const refreshButton = document.getElementById("refresh-button");
const checkUpdatesButton = document.getElementById("check-updates-button");
const versionGridEl = document.getElementById("version-grid");
const versionMetaEl = document.getElementById("version-meta");

let workers = [];
let eventCount = 0;

function writeConsole(line = "") { consoleEl.textContent += `${line}\n`; consoleEl.scrollTop = consoleEl.scrollHeight; }
function resetConsole() { consoleEl.textContent = ""; eventCount = 0; eventCountEl.textContent = "0"; sessionRefEl.textContent = "none"; }
function setMeta(message, isError = false) { requestMetaEl.textContent = message; requestMetaEl.className = isError ? "meta error" : "meta"; }
function updateSessionVisibility() { sessionInput.disabled = modeSelect.value !== "resume"; }
function modelsForProvider(provider) { return workers.filter((w) => w.provider === provider).map((w) => w.model); }

function renderModelOptions() {
  const current = providerSelect.value;
  modelSelect.innerHTML = "";
  for (const model of modelsForProvider(current)) {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    modelSelect.appendChild(option);
  }
}

function renderWorkers() {
  workerListEl.innerHTML = "";
  const groups = {};
  for (const w of workers) {
    groups[w.provider] = groups[w.provider] || [];
    groups[w.provider].push(w);
  }
  for (const [provider, models] of Object.entries(groups)) {
    const group = document.createElement("div");
    group.className = "worker-group";
    group.innerHTML = `<div class="worker-group-header">${provider} <span class="worker-group-count">(${models.length})</span></div>`;
    const items = document.createElement("div");
    items.className = "worker-group-items";
    for (const w of models) {
      const chip = document.createElement("div");
      chip.className = "worker-chip";
      const statusClass = w.ready ? "ok" : "error";
      chip.innerHTML = `<strong>${w.model}</strong><span class="worker-status ${statusClass}">${w.ready ? "ready" : "down"} · ${w.busy ? "busy" : "idle"} · q=${w.queue_length}</span>`;
      items.appendChild(chip);
    }
    group.appendChild(items);
    workerListEl.appendChild(group);
  }
}

function parseSseChunk(buffer) {
  const packets = buffer.split("\n\n");
  return { packets: packets.slice(0, -1), remainder: packets[packets.length - 1] || "" };
}

async function sendStreaming(payload) {
  const response = await fetch("/v1/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (!response.ok || !response.body) throw new Error((await response.text()) || `HTTP ${response.status}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseChunk(buffer);
    buffer = parsed.remainder;
    for (const packet of parsed.packets) {
      const lines = packet.split("\n");
      const eventLine = lines.find((line) => line.startsWith("event: "));
      const dataLine = lines.find((line) => line.startsWith("data: "));
      if (!eventLine || !dataLine) continue;
      const payloadObj = JSON.parse(dataLine.slice(6));
      eventCount += 1;
      eventCountEl.textContent = String(eventCount);
      writeConsole(`[${eventLine.slice(7).trim()}] ${JSON.stringify(payloadObj, null, 2)}`);
      if (payloadObj.provider_session_ref) {
        sessionRefEl.textContent = payloadObj.provider_session_ref;
        sessionInput.value = payloadObj.provider_session_ref;
      }
    }
  }
}

async function sendJson(payload) {
  const response = await fetch("/v1/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || JSON.stringify(body));
  writeConsole(JSON.stringify(body, null, 2));
  if (body.provider_session_ref) { sessionRefEl.textContent = body.provider_session_ref; sessionInput.value = body.provider_session_ref; }
}

function buildVersionCard(v) {
  const card = document.createElement("div");
  card.className = "version-card";
  card.dataset.provider = v.provider;
  const btnDisabled = !v.needs_update;
  card.innerHTML = `<div class="version-row"><strong>${v.provider}</strong><span>${v.needs_update ? "update available" : "up to date"}</span></div>
<div class="version-row"><span>Installed</span><span>${v.current_version || "—"}</span></div>
<div class="version-row"><span>Latest</span><span>${v.latest_version || "—"}</span></div>
<div class="version-row"><span>Next check</span><span>${v.next_check_at ? new Date(v.next_check_at).toLocaleTimeString() : "—"}</span></div>
<button class="version-update-btn" data-provider="${v.provider}" ${btnDisabled ? "disabled" : ""}>Update</button>`;
  card.querySelector(".version-update-btn").addEventListener("click", () => updateProvider(v.provider));
  return card;
}

function renderVersions(versions) {
  versionGridEl.innerHTML = "";
  if (!versions.length) { versionGridEl.innerHTML = '<span class="meta">No version data yet.</span>'; return; }
  for (const v of versions) versionGridEl.appendChild(buildVersionCard(v));
}

async function fetchVersions() { const response = await fetch("/v1/cli-versions"); return await response.json(); }

async function updateProvider(provider) {
  const btn = versionGridEl.querySelector(`.version-update-btn[data-provider="${provider}"]`);
  if (btn) { btn.disabled = true; btn.textContent = "Updating…"; }
  try {
    const response = await fetch(`/v1/cli-versions/${provider}/update`, { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Update failed");
    // Replace just this provider's card with the updated result.
    const oldCard = versionGridEl.querySelector(`.version-card[data-provider="${provider}"]`);
    const newCard = buildVersionCard(result);
    if (oldCard) oldCard.replaceWith(newCard); else versionGridEl.appendChild(newCard);
    versionMetaEl.textContent = `${provider} updated to ${result.current_version || "latest"}.`;
  } catch (error) {
    if (btn) { btn.textContent = "Retry"; btn.disabled = false; }
    versionMetaEl.textContent = error.message;
  }
}

export async function refreshState() {
  const [healthResponse, workersResponse, providersResponse] = await Promise.all([fetch("/health"), fetch("/v1/workers"), fetch("/v1/providers")]);
  const health = await healthResponse.json();
  workers = await workersResponse.json();
  const providers = await providersResponse.json();

  healthStatusEl.textContent = health.status;
  shellPathEl.textContent = health.shell_path || "not detected";
  bashVersionEl.textContent = health.bash_version || "not detected";
  workerCountEl.textContent = String(health.worker_count);

  // Set workspace_path default to config file's parent directory (project root).
  if (!workspaceInput.value && health.config_path) {
    const parts = health.config_path.replace(/\\/g, "/").split("/");
    parts.pop(); // remove config filename
    workspaceInput.value = parts.join("/") || "/";
  }

  const savedProvider = providerSelect.value;
  const savedModel = modelSelect.value;
  providerSelect.innerHTML = "";
  for (const provider of providers.filter((item) => item.enabled && item.available)) {
    const option = document.createElement("option");
    option.value = provider.provider;
    option.textContent = provider.provider;
    providerSelect.appendChild(option);
  }
  if (savedProvider) providerSelect.value = savedProvider;
  renderModelOptions();
  if (savedModel) modelSelect.value = savedModel;
  renderWorkers();
  updateSessionVisibility();

  try {
    const versions = await fetchVersions();
    renderVersions(versions);
    versionMetaEl.textContent = versions.length && versions[0].last_checked ? `Last checked: ${new Date(versions[0].last_checked).toLocaleString()}` : "Checked.";
  } catch (_) { }
}

export function getWorkers() { return workers; }
export function getWorkspaceInput() { return workspaceInput; }

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  resetConsole();
  sendButton.disabled = true;
  setMeta("Sending request...");
  const payload = { provider: providerSelect.value, model: modelSelect.value, workspace_path: workspaceInput.value.trim(), mode: modeSelect.value, prompt: promptInput.value, stream: streamInput.checked };
  if (payload.mode === "resume") payload.provider_session_ref = sessionInput.value.trim();
  try {
    sessionStorage.setItem("workspace_path", payload.workspace_path);
    if (payload.stream) await sendStreaming(payload); else await sendJson(payload);
    setMeta("Request completed.");
    await refreshState();
  } catch (error) {
    writeConsole(`[failed] ${error.message}`);
    setMeta(error.message, true);
  } finally {
    sendButton.disabled = false;
  }
});

refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true;
  try { await refreshState(); setMeta("State refreshed."); } catch (error) { setMeta(error.message, true); } finally { refreshButton.disabled = false; }
});

checkUpdatesButton.addEventListener("click", async () => {
  checkUpdatesButton.disabled = true;
  versionMetaEl.textContent = "Checking providers...";
  try {
    const providers = await (await fetch("/v1/providers")).json();
    const enabled = providers.filter((p) => p.enabled).map((p) => p.provider);
    const results = await Promise.all(enabled.map(async (provider) => (await (await fetch(`/v1/cli-versions/${provider}/check`, { method: "POST" })).json())));
    renderVersions(results.filter(Boolean));
    versionMetaEl.textContent = "Done.";
  } catch (error) {
    versionMetaEl.textContent = error.message;
  } finally {
    checkUpdatesButton.disabled = false;
  }
});

providerSelect.addEventListener("change", renderModelOptions);
modeSelect.addEventListener("change", updateSessionVisibility);
