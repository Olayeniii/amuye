const nativeFetch = window.fetch.bind(window);
const nativeConfirm = window.confirm.bind(window);
const LIVE_PROOF_KEY = "amuye.latestLivePartnerProof";
let approvedPaidJob = false;
let proofRenderInFlight = false;
let historyLoadInFlight = false;

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character]));
const short = (value) => value ? `${value.slice(0, 8)}...${value.slice(-6)}` : "Unavailable";
const amount = (value) => Number(value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 3 });

window.fetch = async (...args) => {
  const response = await nativeFetch(...args);
  try {
    const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
    if (url.includes("/api/assessments/") && response.ok) {
      const payload = await response.clone().json();
      const result = payload?.result;
      if (payload?.status === "completed" && result?.providerMode === "live Virtuals ACP risk purchase on Base mainnet") {
        const job = result.execution?.providerJobs?.find((item) => item.acpJobId);
        const proof = result.settlementProofs?.find((item) => String(item.jobId) === String(job?.acpJobId));
        if (job && proof) sessionStorage.setItem(LIVE_PROOF_KEY, JSON.stringify({ job, proof, capturedAt: new Date().toISOString() }));
      }
    }
  } catch (_) {}
  return response;
};

window.confirm = (message) => {
  if (approvedPaidJob && String(message).startsWith("Create a real paid Virtuals ACP job?")) {
    approvedPaidJob = false;
    return true;
  }
  return nativeConfirm(message);
};

function closeModal() { document.querySelector(".acp-confirm-backdrop")?.remove(); }

function showPaidJobModal(form, config) {
  closeModal();
  const backdrop = document.createElement("div");
  backdrop.className = "acp-confirm-backdrop";
  backdrop.innerHTML = `<section class="acp-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="acp-confirm-title"><p class="eyebrow">Real paid specialist purchase</p><h2 id="acp-confirm-title">Create a Virtuals ACP job?</h2><p>This assessment will purchase <strong>${escapeHtml(config.offering || "riskSynthesis")}</strong> and settle it on <strong>${escapeHtml(config.network || "Base mainnet")}</strong>.</p><div class="acp-confirm-facts"><div><span>Offering</span><strong>${escapeHtml(config.offering || "riskSynthesis")}</strong></div><div><span>Network</span><strong>${escapeHtml(config.network || "Base mainnet")}</strong></div><div><span>Maximum expected spend</span><strong>${amount(config.maxExpectedSpend)} ${escapeHtml(config.asset || "USDC")}</strong></div></div><p class="acp-confirm-warning">This creates and funds a real paid job.</p><div class="acp-confirm-actions"><button type="button" class="secondary" data-cancel>Cancel</button><button type="button" data-approve>Create paid job</button></div></section>`;
  document.body.append(backdrop);
  backdrop.querySelector("[data-cancel]").addEventListener("click", closeModal);
  backdrop.addEventListener("click", (event) => { if (event.target === backdrop) closeModal(); });
  backdrop.querySelector("[data-approve]").addEventListener("click", () => { approvedPaidJob = true; form.dataset.paidJobApproved = "true"; closeModal(); form.requestSubmit(); });
}

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.id !== "assessment-form") return;
  if (!form.querySelector('[name="liveAcpEnabled"]')?.checked) return;
  if (form.dataset.paidJobApproved === "true") { delete form.dataset.paidJobApproved; return; }
  event.preventDefault(); event.stopImmediatePropagation();
  const errorBox = form.querySelector("#assessment-error");
  try {
    const response = await nativeFetch("/api/acp/config");
    const config = await response.json();
    if (!response.ok || !config.enabled) throw new Error(config.status || "Live ACP is not configured");
    showPaidJobModal(form, config);
  } catch (error) { if (errorBox) { errorBox.textContent = error.message; errorBox.hidden = false; } }
}, true);

async function loadLatestPartnerProof() {
  try {
    const response = await nativeFetch("/api/partner-proof/latest", { cache: "no-store" });
    if (response.ok) {
      const latest = await response.json();
      if (latest?.job && latest?.proof) { sessionStorage.setItem(LIVE_PROOF_KEY, JSON.stringify(latest)); return latest; }
    }
  } catch (_) {}
  const raw = sessionStorage.getItem(LIVE_PROOF_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch (_) { return null; }
}

async function renderLatestPartnerProof() {
  if (location.hash !== "#partner-proof" || proofRenderInFlight) return;
  proofRenderInFlight = true;
  try {
    const latest = await loadLatestPartnerProof();
    if (!latest?.job || !latest?.proof) return;
    const { job, proof } = latest;
    const main = document.querySelector("main");
    const panel = main?.querySelector(".proof-panel");
    if (!main || !panel || panel.dataset.liveProof === String(job.acpJobId)) return;
    const eyebrow = main.querySelector(".proof-hero .eyebrow");
    const headline = main.querySelector(".proof-hero h1");
    if (eyebrow) eyebrow.textContent = "Latest live partner execution";
    if (headline) headline.textContent = "This run purchased risk synthesis through Virtuals ACP and settled it on Base.";
    const orb = main.querySelector(".proof-hero .spend-orb");
    if (orb) orb.innerHTML = `<small>ACP job</small><strong>${escapeHtml(job.acpJobId)}</strong><span>${escapeHtml(proof.network || "Base mainnet")}</span>`;
    panel.dataset.liveProof = String(job.acpJobId);
    panel.innerHTML = `<div class="proof-heading"><div><p class="eyebrow">Virtuals ACP → Base</p><h2>Current live run</h2></div><span class="status"><i>✓</i>${escapeHtml(job.status || "completed")}</span></div><div class="proof-grid"><div><span>ACP job</span><strong>${escapeHtml(job.acpJobId)}</strong></div><div><span>Provider</span><strong title="${escapeHtml(job.providerId)}">${escapeHtml(short(job.providerId))}</strong></div><div><span>Offering</span><strong>riskSynthesis</strong></div><div><span>Escrowed</span><strong>${amount(proof.escrowedAmount)} USDC</strong></div><div><span>Provider release</span><strong>${amount(proof.providerReleasedAmount)} USDC</strong></div><div><span>Network</span><strong>${escapeHtml(proof.network || "Base mainnet")}</strong></div></div><div class="transactions"><a href="${escapeHtml(proof.funding?.explorerUrl)}" target="_blank" rel="noreferrer"><span>Funding transaction</span><code>${escapeHtml(proof.funding?.transactionHash)}</code><b>View on BaseScan ↗</b></a><a href="${escapeHtml(proof.completion?.explorerUrl)}" target="_blank" rel="noreferrer"><span>Completion transaction</span><code>${escapeHtml(proof.completion?.transactionHash)}</code><b>View on BaseScan ↗</b></a></div><p class="accounting">Verified settlement from the latest live assessment. Historical checkpoint job 75660 remains preserved only as corroborating evidence.</p>`;
  } finally { proofRenderInFlight = false; }
}

function installRunsTab() {
  const nav = document.querySelector("header nav");
  if (!nav) return;
  let link = nav.querySelector('[href="#history"]');
  if (!link) {
    link = document.createElement("a");
    link.href = "#history";
    const partnerProof = nav.querySelector('[href="#partner-proof"]');
    nav.insertBefore(link, partnerProof || null);
  }
  link.textContent = "Runs";
}

function historyStatus(job) {
  const provider = job.providerMode === "live_acp" ? "Live ACP" : "Local";
  const memory = job.memoryEnabled ? "Sibyl ON" : "Sibyl OFF";
  return `${job.status || "unknown"} · ${memory} · ${provider}`;
}

function runSpend(job) {
  const value = job.result?.execution?.spent ?? job.result?.spent ?? job.spent;
  return Number.isFinite(Number(value)) ? `${amount(value)} spent` : "Spend unavailable";
}

async function renderHistoryPage() {
  if (location.hash !== "#history" || historyLoadInFlight) return;
  const main = document.querySelector("main");
  if (!main) return;
  historyLoadInFlight = true;
  main.innerHTML = `<section class="result-hero"><div><p class="eyebrow">Execution console</p><h1>Runs</h1><p class="verified">Loading persisted runs.</p></div></section>`;
  try {
    const response = await nativeFetch("/api/assessments?limit=50", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Runs could not be loaded");
    const jobs = Array.isArray(payload.assessments) ? payload.assessments : [];
    main.innerHTML = `<section class="result-hero"><div><p class="eyebrow">Execution console</p><h1>Runs</h1><p class="verified">Recent Amúyẹ executions, newest first. Open any run to inspect its persisted execution record.</p></div><div class="spend-orb"><small>Stored</small><strong>${jobs.length}</strong><span>recent runs</span></div></section><section class="panel timeline-panel"><div class="section-head"><div><p class="eyebrow">Recent executions</p><h2>Run list</h2></div><span>Latest 50</span></div><div class="timeline history-list">${jobs.length ? jobs.map((job) => `<div class="history-row"><i></i><strong>${escapeHtml(job.request?.objective || job.id)}</strong><span>${escapeHtml(historyStatus(job))}</span><small>${escapeHtml(runSpend(job))} · ${escapeHtml(job.createdAt ? new Date(job.createdAt).toLocaleString() : "")}</small><button type="button" data-history-job="${escapeHtml(job.id)}">Open run</button></div>`).join("") : `<p>No persisted runs yet. Your next New Assessment will appear here.</p>`}</div></section>`;
    main.querySelectorAll("[data-history-job]").forEach((button) => button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const jobResponse = await nativeFetch(`/api/assessments/${encodeURIComponent(button.dataset.historyJob)}`, { cache: "no-store" });
        const job = await jobResponse.json();
        if (!jobResponse.ok) throw new Error(job.error || "Run could not be loaded");
        main.innerHTML = `<section class="result-hero"><div><p class="eyebrow">Persisted run</p><h1>${escapeHtml(job.request?.objective || job.id)}</h1><p class="verified">${escapeHtml(historyStatus(job))}</p></div></section><section class="panel timeline-panel"><div class="section-head"><div><p class="eyebrow">Execution record</p><h2>Run ${escapeHtml(short(job.id))}</h2></div><a href="#history">Back to runs</a></div><div class="timeline">${(job.events || []).map((event) => `<div><i></i><strong>${escapeHtml(event.type || "event")}</strong><span>${escapeHtml(event.at ? new Date(event.at).toLocaleTimeString() : "")}</span></div>`).join("")}</div>${job.error ? `<p class="assessment-error">${escapeHtml(job.error)}</p>` : ""}</section>`;
      } catch (error) { button.disabled = false; main.insertAdjacentHTML("beforeend", `<p class="assessment-error">${escapeHtml(error.message)}</p>`); }
    }));
  } catch (error) {
    main.innerHTML = `<section class="result-hero"><div><p class="eyebrow">Execution console</p><h1>Runs</h1><p class="assessment-error">${escapeHtml(error.message)}</p></div></section>`;
  } finally { historyLoadInFlight = false; }
}

const appRoot = document.querySelector("#app");
new MutationObserver(() => { installRunsTab(); void renderLatestPartnerProof(); }).observe(appRoot, { childList: true, subtree: true });
addEventListener("hashchange", () => { installRunsTab(); void renderLatestPartnerProof(); void renderHistoryPage(); });
installRunsTab();
void renderLatestPartnerProof();
void renderHistoryPage();
