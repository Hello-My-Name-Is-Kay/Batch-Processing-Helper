"use strict";

const state = {
  token: "",
  page: "overview",
  providers: [],
  selectedProvider: "anthropic",
  overview: null,
  batchRows: [],
  currentBatchDetail: null,
  batchSearchTimer: null,
  refreshTimer: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(number);
}

function formatCurrency(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number) ? `$${number.toFixed(4)}` : "—";
}

function formatTime(value) {
  if (!value) return "—";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function statusBadge(status) {
  const safe = escapeHtml(status || "unknown");
  return `<span class="status-badge ${escapeHtml(status || "")}">${safe}</span>`;
}

function toast(message, kind = "") {
  const region = $("#toast-region");
  const item = document.createElement("div");
  item.className = `toast ${kind}`.trim();
  item.textContent = message;
  region.appendChild(item);
  window.setTimeout(() => item.remove(), 4200);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Batch-Console-Token", state.token);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers, cache: "no-store" });
  let data = {};
  try { data = await response.json(); } catch (_) { /* empty response */ }
  if (response.status === 401) {
    showLogin();
    throw new Error("Console token required");
  }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function setMessage(selector, message, kind = "") {
  const node = $(selector);
  node.textContent = message;
  node.className = `form-message ${kind}`.trim();
}

function showLogin() {
  $("#console").hidden = true;
  $("#login").hidden = false;
  $("#login-token").focus();
}

function showConsole() {
  $("#login").hidden = true;
  $("#console").hidden = false;
}

async function boot() {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const fragmentToken = fragment.get("token");
  if (fragmentToken) {
    state.token = fragmentToken;
    sessionStorage.setItem("batch-console-token", fragmentToken);
    history.replaceState(null, "", window.location.pathname);
  } else {
    state.token = sessionStorage.getItem("batch-console-token") || "";
  }
  if (!state.token) {
    showLogin();
    return;
  }
  try {
    showConsole();
    await refreshAll();
    state.refreshTimer = window.setInterval(refreshOverview, 8000);
  } catch (error) {
    showLogin();
    if (!String(error.message).includes("token")) toast(error.message, "error");
  }
}

async function refreshAll() {
  await Promise.all([refreshOverview(), refreshSetup()]);
}

async function refreshOverview() {
  if (!state.token) return;
  try {
    const data = await api("/api/overview");
    state.overview = data;
    state.selectedProvider = data.selected_provider || state.selectedProvider;
    renderOverview(data);
    updateHeader(data);
  } catch (error) {
    if (!String(error.message).includes("token")) toast(error.message, "error");
  }
}

function updateHeader(data) {
  const counts = data.counts || {};
  const needsAttention = (counts.escalations || 0) + (counts.failed || 0);
  const pill = $("#pipeline-status");
  const dot = pill.querySelector("i");
  dot.className = `dot ${needsAttention ? "warn" : counts.running ? "running" : "secure"}`;
  pill.querySelector("span").textContent = needsAttention ? "Attention required" : counts.running ? "Running" : "Ready";
  $("#provider-chip").textContent = `Provider ${data.selected_provider || "—"}`;
}

function renderOverview(data) {
  const counts = data.counts || {};
  const cards = [
    ["Running", counts.running || 0, "At provider"],
    ["Completed", counts.completed || 0, `${counts.archived || 0} archived`],
    ["Escalations", counts.escalations || 0, "Needs review"],
    ["Failed", (counts.failed || 0) + (counts.cancelled || 0), `${counts.awaiting_routing || 0} awaiting routing`],
  ];
  $("#overview-cards").innerHTML = cards.map(([label, value, sub]) => `
    <article class="metric-card"><span class="label">${escapeHtml(label)}</span><strong class="value">${formatNumber(value)}</strong><span class="sub">${escapeHtml(sub)}</span></article>
  `).join("");

  const active = (data.batches || []).filter(batch => ["running", "submitted"].includes(batch.status));
  $("#active-batches").innerHTML = batchTable(active.length ? active : (data.batches || []).slice(0, 8), true);
  $("#overview-history").innerHTML = historyTable(data.history || []);
  $("#overview-escalations").innerHTML = escalationList((data.escalations || []).slice(0, 4));
  $("#overview-gateway").innerHTML = gatewaySummary(data.gateway || {});
}

function batchTable(rows, compact = false) {
  if (!rows.length) return '<div class="empty">No batches to show.</div>';
  return `<table><thead><tr><th>Batch</th><th>Provider</th><th>Model</th><th>Status</th><th>Age</th>${compact ? "" : "<th>Requests</th><th>Actions</th>"}</tr></thead><tbody>${
    rows.map(row => `<tr>
      <td class="mono" title="${escapeHtml(row.batch_id)}">${escapeHtml((row.batch_id || "").slice(0, 13))}…</td>
      <td>${escapeHtml(row.provider || "—")}</td>
      <td title="${escapeHtml(row.model || "")}">${escapeHtml((row.model || "—").slice(0, 28))}</td>
      <td>${statusBadge(row.status)}</td>
      <td>${escapeHtml(row.age || "—")}</td>
      ${compact ? "" : `<td>${formatNumber(row.request_counts?.total || row.custom_ids?.length || 0)}</td><td><button class="secondary small manage-batch" data-batch-id="${escapeHtml(row.batch_id)}">Manage</button></td>`}
    </tr>`).join("")
  }</tbody></table>`;
}

function historyTable(rows) {
  if (!rows.length) return '<div class="empty">No completed batches yet.</div>';
  return `<table><thead><tr><th>Batch</th><th>Provider</th><th>Model</th><th>Latency</th><th>Tokens</th><th>Cost</th></tr></thead><tbody>${
    rows.map(row => `<tr>
      <td class="mono" title="${escapeHtml(row.batch_id)}">${escapeHtml((row.batch_id || "").slice(0, 12))}…</td>
      <td>${escapeHtml(row.provider || "—")}</td>
      <td>${escapeHtml((row.raw_model || row.model || "—").slice(0, 25))}</td>
      <td>${escapeHtml(row.latency_seconds ?? "—")}${row.latency_seconds ? "s" : ""}</td>
      <td>${formatNumber(row.total_tokens)}</td>
      <td>${formatCurrency(row.cost)}</td>
    </tr>`).join("")
  }</tbody></table>`;
}

function escalationList(rows) {
  if (!rows.length) return '<div class="empty">Nothing needs review.</div>';
  return rows.map(row => `<div class="list-item" data-escalation-file="${escapeHtml(row.file)}">
    <div class="list-item-head"><div><div class="list-item-title">${escapeHtml(row.request_id || row.file)}</div><div class="list-item-meta">${escapeHtml(row.provider || "unknown")} · ${escapeHtml(row.classification || "unclassified")} · ${escapeHtml(row.escalated_at || "")}</div></div><button class="ghost small review-escalation">Review</button></div>
    <div class="preview">${escapeHtml(row.reason || row.summary || row.response || "No preview available")}</div>
  </div>`).join("");
}

function gatewaySummary(gateway) {
  const running = Boolean(gateway.running);
  return `<div class="service-state">
    <div class="service-line"><span>Status</span><strong><i class="dot ${running ? "running" : "down"}"></i> ${running ? "Running" : "Stopped"}</strong></div>
    <div class="service-line"><span>Endpoint</span><code>${escapeHtml(gateway.url || "http://127.0.0.1:8787/health")}</code></div>
    ${running ? `<div class="service-line"><span>Health</span><strong>${escapeHtml(JSON.stringify(gateway.health || {}))}</strong></div>` : `<div class="service-line"><span>Last error</span><span>${escapeHtml(gateway.error || "Not running")}</span></div>`}
  </div>`;
}

async function refreshSetup() {
  const data = await api("/api/setup");
  state.providers = data.providers || [];
  state.selectedProvider = data.selected_provider || state.selectedProvider;
  renderProviders();
  populateProviderSelects();
}

function providerIcon(provider) {
  return provider === "anthropic" ? "A" : provider === "openrouter" ? "OR" : "G";
}

function renderProviders() {
  $("#provider-cards").innerHTML = state.providers.map(provider => {
    const configured = provider.configured;
    const selected = provider.id === state.selectedProvider;
    return `<article class="provider-card ${selected ? "selected" : ""}">
      <div class="provider-icon">${escapeHtml(providerIcon(provider.id))}</div>
      <h3>${escapeHtml(provider.name)}</h3>
      <p>Model: <span class="mono">${escapeHtml(provider.selected_model || provider.default_model)}</span></p>
      <p>Key: ${escapeHtml(provider.credential_source)}</p>
      <div class="provider-state"><i class="dot ${configured ? "secure" : "warn"}"></i>${configured ? "Configured" : "Needs setup"}</div>
      <div class="button-row"><button class="secondary configure-provider" data-provider="${escapeHtml(provider.id)}">Configure</button>${provider.credential_source === "private credential store" ? `<button class="ghost small remove-credential" data-provider="${escapeHtml(provider.id)}">Remove saved key</button>` : ""}</div>
    </article>`;
  }).join("");
}

function populateProviderSelects() {
  const options = state.providers.map(provider => `<option value="${escapeHtml(provider.id)}">${escapeHtml(provider.name)}</option>`).join("");
  ["#credential-provider", "#model-provider", "#submit-provider"].forEach(selector => {
    const node = $(selector);
    const previous = node.value;
    node.innerHTML = options;
    if ([...node.options].some(option => option.value === previous)) node.value = previous;
  });
  $("#submit-provider").value = state.selectedProvider;
}

function navigate(page) {
  state.page = page;
  $$(".page").forEach(section => section.classList.toggle("active", section.id === `page-${page}`));
  $$(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.page === page));
  const names = {
    overview: ["OPERATIONS", "Overview"], setup: ["CONFIGURATION", "Provider setup"],
    batches: ["PIPELINE", "Batches"], results: ["REVIEW QUEUE", "Results"],
    metrics: ["PERFORMANCE", "Metrics"], logs: ["OBSERVABILITY", "Logs"], gateway: ["SERVICE CONTROL", "Gateway"],
  };
  $("#page-eyebrow").textContent = names[page][0];
  $("#page-title").textContent = names[page][1];
  if (page === "batches") loadBatches();
  if (page === "results") loadResults();
  if (page === "metrics") loadMetrics();
  if (page === "logs") loadLogs();
  if (page === "gateway") loadGateway();
}

async function loadBatches() {
  const params = new URLSearchParams();
  const provider = $("#batch-provider-filter").value;
  const status = $("#batch-status-filter").value;
  const search = $("#batch-search").value.trim();
  if (provider) params.set("provider", provider);
  if (status) params.set("status", status);
  if (search) params.set("search", search);
  params.set("limit", "1000");
  const data = await api(`/api/batches?${params}`);
  state.batchRows = data.batches || [];
  $("#all-batches").innerHTML = batchTable(state.batchRows);
}

async function openBatchDetail(batchId) {
  try {
    const detail = await api(`/api/batches/detail?batch_id=${encodeURIComponent(batchId)}`);
    state.currentBatchDetail = detail;
    renderBatchDetail(detail);
    setMessage("#batch-message", "");
    const dialog = $("#batch-dialog");
    if (!dialog.open && typeof dialog.showModal === "function") dialog.showModal();
    else if (!dialog.open) dialog.setAttribute("open", "");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderBatchDetail(detail) {
  const history = detail.history || {};
  const requests = detail.request_counts || {};
  const caps = detail.capabilities || {};
  $("#batch-dialog-title").textContent = detail.batch_id || "Batch details";
  $("#batch-detail-content").innerHTML = `
    <div class="detail-grid">
      <div class="detail-stat"><span>Status</span><strong>${statusBadge(detail.status)}</strong></div>
      <div class="detail-stat"><span>Provider</span><strong>${escapeHtml(detail.provider || "—")}</strong></div>
      <div class="detail-stat"><span>Model</span><strong title="${escapeHtml(detail.model || "")}">${escapeHtml(detail.model || "—")}</strong></div>
      <div class="detail-stat"><span>Age</span><strong>${escapeHtml(detail.age || "—")}</strong></div>
      <div class="detail-stat"><span>Requests</span><strong>${formatNumber(requests.total || detail.custom_ids?.length || 0)}</strong></div>
      <div class="detail-stat"><span>Latency</span><strong>${detail.latency_seconds ?? history.latency_seconds ?? "—"}s</strong></div>
      <div class="detail-stat"><span>Tokens</span><strong>${formatNumber(history.total_tokens)}</strong></div>
      <div class="detail-stat"><span>Cost</span><strong>${formatCurrency(history.cost)}</strong></div>
    </div>
    <div class="detail-section"><h3>Request identifiers</h3><div class="preview">${escapeHtml((detail.custom_ids || []).join("\n") || detail.request_id || "—")}</div></div>
    ${detail.error ? `<div class="detail-section"><h3>Provider error</h3><div class="preview">${escapeHtml(detail.error)}</div></div>` : ""}
    ${detail.result_items?.length ? `<div class="detail-section"><h3>Result preview</h3>${detail.result_items.map(item => `<div class="list-item"><div class="list-item-head"><strong>${escapeHtml(item.custom_id)}</strong>${statusBadge(item.status)}</div>${item.error ? `<div class="preview">${escapeHtml(item.error)}</div>` : `<div class="preview">${escapeHtml(item.content_preview || "No text content")}</div>`}</div>`).join("")}</div>` : ""}
    <div class="detail-section"><h3>Local artifacts</h3><div class="detail-files">${(detail.files || []).map(file => `<div class="detail-file"><span>${escapeHtml(file.kind)}</span><code title="${escapeHtml(file.path)}">${escapeHtml(file.path)}</code></div>`).join("")}</div></div>
    <div class="detail-section"><h3>Capabilities</h3><div class="provider-state"><i class="dot ${caps.poll || caps.cancel || caps.archive ? "secure" : "warn"}"></i>${caps.poll ? "Can poll now" : "Polling complete"} · ${caps.cancel ? "Provider cancellation available" : "Provider cancellation unavailable"} · ${caps.archive ? "Can dismiss from active list" : "Must finish before dismissal"}</div></div>`;
  $("#batch-poll-one").disabled = !caps.poll;
  $("#batch-cancel").disabled = !caps.cancel;
  $("#batch-archive").disabled = !caps.archive;
}

async function loadResults() {
  const [escalations, results] = await Promise.all([api("/api/escalations"), api("/api/results")]);
  $("#all-escalations").innerHTML = escalationList(escalations.escalations || []);
  const rows = results.results || [];
  $("#result-files").innerHTML = rows.length ? rows.map(row => `<div class="list-item"><div class="list-item-head"><div><div class="list-item-title">${escapeHtml(row.file)}</div><div class="list-item-meta">${escapeHtml(row.status)} · ${formatNumber(row.size)} bytes</div></div></div></div>`).join("") : '<div class="empty">No result files yet.</div>';
}

async function loadMetrics() {
  const metrics = await api("/api/metrics");
  const cards = [
    ["Completed batches", metrics.completed_batches || 0, "Collected by poller"],
    ["Median latency", metrics.latency?.median ?? "—", metrics.latency?.median ? "seconds" : "No samples"],
    ["Archived results", metrics.archived_results || 0, "Routed plain text"],
    ["Throughput", metrics.throughput?.batches_per_hour ?? "—", metrics.throughput ? "batches / hour" : "Needs two batches"],
  ];
  $("#metric-cards").innerHTML = cards.map(([label, value, sub]) => `<article class="metric-card"><span class="label">${escapeHtml(label)}</span><strong class="value">${escapeHtml(value)}</strong><span class="sub">${escapeHtml(sub)}</span></article>`).join("");
  const providers = Object.entries(metrics.by_provider || {});
  $("#metric-providers").innerHTML = providers.length ? providers.map(([provider, data]) => `<div class="list-item"><div class="list-item-head"><div><div class="list-item-title">${escapeHtml(provider)}</div><div class="list-item-meta">${formatNumber(data.total_requests)} requests</div></div><strong>${formatNumber(data.latency?.mean)}s mean</strong></div></div>`).join("") : '<div class="empty">No provider metrics yet.</div>';
  $("#metric-throughput").innerHTML = `<div class="service-line"><span>Batches per hour</span><strong>${formatNumber(metrics.throughput?.batches_per_hour)}</strong></div><div class="service-line"><span>Window</span><strong>${formatNumber(metrics.throughput?.window_seconds)}s</strong></div>`;
}

async function loadLogs() {
  const name = $("#log-selector").value;
  const data = await api(`/api/logs?name=${encodeURIComponent(name)}`);
  $("#log-path").textContent = data.path || "LIVE LOG";
  $("#log-output").textContent = data.lines?.length ? data.lines.join("\n") : "No log entries yet.";
}

async function loadGateway() {
  const gateway = await api("/api/gateway");
  $("#gateway-detail").innerHTML = gatewaySummary(gateway);
}

function openSubmit() {
  $("#submit-message").textContent = "";
  $("#submit-confirm").checked = false;
  const dialog = $("#submit-dialog");
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

async function submitBatch(dryRun = false) {
  const prompts = $("#submit-prompts").value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  if (!prompts.length) { setMessage("#submit-message", "Enter at least one prompt.", "bad"); return; }
  const maxTokensRaw = $("#submit-max-tokens").value.trim();
  const body = {
    provider: $("#submit-provider").value,
    model: $("#submit-model").value.trim() || null,
    prompts,
    system: $("#submit-system").value.trim() || null,
    agent: $("#submit-agent").value.trim() || null,
    max_tokens: maxTokensRaw ? Number(maxTokensRaw) : null,
    dry_run: dryRun,
    confirm: dryRun ? false : $("#submit-confirm").checked,
  };
  setMessage("#submit-message", dryRun ? "Validating…" : "Submitting…");
  try {
    const result = await api(dryRun ? "/api/batches/submit" : "/api/batches/submit", {
      method: "POST", body: JSON.stringify(body),
    });
    if (dryRun) {
      setMessage("#submit-message", `Dry run passed: ${result.request_count} request(s), no batch was sent.`, "ok");
    } else {
      setMessage("#submit-message", `Submitted ${result.batch_id}. Track it in the Batches page.`, "ok");
      toast("Batch submitted successfully", "success");
      $("#submit-dialog").close();
      await refreshOverview();
      navigate("batches");
    }
  } catch (error) {
    setMessage("#submit-message", error.message, "bad");
  }
}

async function runPoll() {
  const button = $("#run-poll");
  button.disabled = true;
  button.textContent = "Polling…";
  try {
    const result = await api("/api/pipeline/poll", { method: "POST", body: "{}" });
    const failed = (result.steps || []).some(step => step.returncode !== 0);
    toast(failed ? "Poll finished with errors" : "Poll cycle complete", failed ? "error" : "success");
    await refreshOverview();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Run poll";
  }
}

async function gatewayAction(command) {
  setMessage("#gateway-message", `${command} requested…`);
  try {
    const result = await api(`/api/gateway/${command}`, { method: "POST", body: "{}" });
    setMessage("#gateway-message", result.output || `${command} complete`, "ok");
    toast(`Gateway ${command} complete`, "success");
    await loadGateway();
    await refreshOverview();
  } catch (error) {
    setMessage("#gateway-message", error.message, "bad");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#login-form").addEventListener("submit", async event => {
    event.preventDefault();
    state.token = $("#login-token").value.trim();
    sessionStorage.setItem("batch-console-token", state.token);
    $("#login-error").textContent = "";
    try {
      showConsole();
      await refreshAll();
      state.refreshTimer = window.setInterval(refreshOverview, 8000);
    } catch (error) {
      state.token = "";
      sessionStorage.removeItem("batch-console-token");
      $("#login-error").textContent = error.message;
      showLogin();
    }
  });

  $("#logout").addEventListener("click", () => {
    state.token = "";
    sessionStorage.removeItem("batch-console-token");
    if (state.refreshTimer) clearInterval(state.refreshTimer);
    showLogin();
  });

  $$(".nav-item").forEach(button => button.addEventListener("click", () => navigate(button.dataset.page)));
  $$('[data-page-link]').forEach(button => button.addEventListener("click", () => navigate(button.dataset.pageLink)));
  $("#run-poll").addEventListener("click", runPoll);
  $("#open-submit").addEventListener("click", openSubmit);
  $("#open-submit-2").addEventListener("click", openSubmit);
  $("#submit-form").addEventListener("submit", event => { event.preventDefault(); submitBatch(false); });
  $("#dry-run").addEventListener("click", () => submitBatch(true));

  $("#toggle-secret").addEventListener("click", () => {
    const input = $("#credential-key");
    input.type = input.type === "password" ? "text" : "password";
    $("#toggle-secret").textContent = input.type === "password" ? "Show" : "Hide";
  });

  $("#credential-form").addEventListener("submit", async event => {
    event.preventDefault();
    const provider = $("#credential-provider").value;
    const apiKey = $("#credential-key").value;
    setMessage("#credential-message", "Saving…");
    try {
      await api("/api/setup/credential", { method: "POST", body: JSON.stringify({ provider, api_key: apiKey }) });
      $("#credential-key").value = "";
      setMessage("#credential-message", "Credential saved in the owner-only private store.", "ok");
      toast("Credential saved", "success");
      await refreshSetup();
    } catch (error) {
      setMessage("#credential-message", error.message, "bad");
    }
  });

  $("#test-credential").addEventListener("click", async () => {
    const provider = $("#credential-provider").value;
    const apiKey = $("#credential-key").value;
    setMessage("#credential-message", "Testing connection…");
    try {
      const result = await api("/api/setup/test", { method: "POST", body: JSON.stringify({ provider, api_key: apiKey || null }) });
      setMessage("#credential-message", `Connection works. ${result.model_count} models are available.`, "ok");
    } catch (error) {
      setMessage("#credential-message", error.message, "bad");
    }
  });

  $("#model-form").addEventListener("submit", async event => {
    event.preventDefault();
    const provider = $("#model-provider").value;
    const model = $("#model-name").value.trim();
    if (!model) { setMessage("#model-message", "Enter a model ID.", "bad"); return; }
    try {
      await api("/api/setup/model", { method: "POST", body: JSON.stringify({ provider, model }) });
      setMessage("#model-message", "Model selection saved.", "ok");
      await refreshSetup();
    } catch (error) {
      setMessage("#model-message", error.message, "bad");
    }
  });

  $("#discover-models").addEventListener("click", async () => {
    const provider = $("#model-provider").value;
    setMessage("#model-message", "Loading models…");
    try {
      const result = await api("/api/setup/test", { method: "POST", body: JSON.stringify({ provider }) });
      $("#model-options").innerHTML = result.models.map(model => `<option value="${escapeHtml(model)}"></option>`).join("");
      if (result.models.length) $("#model-name").value = result.models[0];
      setMessage("#model-message", `${result.model_count} models discovered.`, "ok");
    } catch (error) {
      setMessage("#model-message", error.message, "bad");
    }
  });

  $("#provider-cards").addEventListener("click", async event => {
    const configure = event.target.closest(".configure-provider");
    const remove = event.target.closest(".remove-credential");
    if (configure) {
      const provider = configure.dataset.provider;
      $("#credential-provider").value = provider;
      $("#model-provider").value = provider;
      const item = state.providers.find(entry => entry.id === provider);
      $("#model-name").value = item?.selected_model || item?.default_model || "";
      try {
        await api("/api/setup/provider", { method: "POST", body: JSON.stringify({ provider }) });
        state.selectedProvider = provider;
        $("#submit-provider").value = provider;
        await refreshSetup();
        toast(`${provider} is now the console provider`, "success");
      } catch (error) { toast(error.message, "error"); }
    }
    if (remove) {
      const provider = remove.dataset.provider;
      if (!window.confirm(`Remove the saved ${provider} credential?`)) return;
      try {
        await api(`/api/setup/credential?provider=${encodeURIComponent(provider)}`, { method: "DELETE" });
        toast("Saved credential removed", "success");
        await refreshSetup();
      } catch (error) { toast(error.message, "error"); }
    }
  });

  $("#all-escalations").addEventListener("click", async event => {
    const button = event.target.closest(".review-escalation");
    if (!button) return;
    const item = button.closest("[data-escalation-file]");
    const file = item?.dataset.escalationFile;
    if (!file || !window.confirm("Mark this escalation as reviewed and remove it from the queue?")) return;
    try {
      await api("/api/escalations/review", { method: "POST", body: JSON.stringify({ file }) });
      toast("Escalation marked reviewed", "success");
      await loadResults();
      await refreshOverview();
    } catch (error) { toast(error.message, "error"); }
  });

  $("#log-selector").addEventListener("change", loadLogs);
  $("#refresh-logs").addEventListener("click", loadLogs);
  $$('[data-gateway]').forEach(button => button.addEventListener("click", () => gatewayAction(button.dataset.gateway)));

  $("#refresh-batches").addEventListener("click", loadBatches);
  $("#batch-provider-filter").addEventListener("change", loadBatches);
  $("#batch-status-filter").addEventListener("change", loadBatches);
  $("#batch-search").addEventListener("input", () => {
    window.clearTimeout(state.batchSearchTimer);
    state.batchSearchTimer = window.setTimeout(loadBatches, 220);
  });
  $("#all-batches").addEventListener("click", event => {
    const button = event.target.closest(".manage-batch");
    if (button) openBatchDetail(button.dataset.batchId);
  });
  $("#close-batch-dialog").addEventListener("click", () => $("#batch-dialog").close());
  $("#batch-poll-one").addEventListener("click", async () => {
    const detail = state.currentBatchDetail;
    if (!detail) return;
    setMessage("#batch-message", "Polling this batch…");
    $("#batch-poll-one").disabled = true;
    try {
      const result = await api("/api/batches/poll", { method: "POST", body: JSON.stringify({ batch_id: detail.batch_id }) });
      state.currentBatchDetail = result.detail;
      renderBatchDetail(result.detail);
      setMessage("#batch-message", "Batch poll complete.", "ok");
      await Promise.all([loadBatches(), refreshOverview()]);
    } catch (error) {
      setMessage("#batch-message", error.message, "bad");
    }
  });
  $("#batch-cancel").addEventListener("click", async () => {
    const detail = state.currentBatchDetail;
    if (!detail || !window.confirm(`Ask ${detail.provider} to cancel this batch?`)) return;
    setMessage("#batch-message", "Requesting cancellation…");
    try {
      await api("/api/batches/cancel", { method: "POST", body: JSON.stringify({ batch_id: detail.batch_id }) });
      setMessage("#batch-message", "Cancellation requested. The provider will confirm it asynchronously.", "ok");
      await Promise.all([loadBatches(), refreshOverview()]);
      await openBatchDetail(detail.batch_id);
    } catch (error) {
      setMessage("#batch-message", error.message, "bad");
    }
  });
  $("#batch-archive").addEventListener("click", async () => {
    const detail = state.currentBatchDetail;
    if (!detail || !window.confirm("Dismiss this batch from the active list? Results and history will be preserved.")) return;
    try {
      await api("/api/batches/archive", { method: "POST", body: JSON.stringify({ batch_id: detail.batch_id }) });
      $("#batch-dialog").close();
      toast("Batch dismissed from the active list", "success");
      await Promise.all([loadBatches(), refreshOverview()]);
    } catch (error) {
      setMessage("#batch-message", error.message, "bad");
    }
  });
  $("#batch-download").addEventListener("click", () => {
    if (!state.currentBatchDetail) return;
    const blob = new Blob([JSON.stringify(state.currentBatchDetail, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${state.currentBatchDetail.batch_id || "batch"}.json`;
    link.click();
    URL.revokeObjectURL(url);
  });

  boot();
});
