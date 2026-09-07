const nativeFetch = window.fetch.bind(window);
const nativeConfirm = window.confirm.bind(window);
const LIVE_PROOF_KEY = "amuye.latestLivePartnerProof";
let approvedPaidJob = false;

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
  } catch (_) {
    // Presentation persistence must never interfere with an assessment response.
  }
  return response;
};

window.confirm = (message) => {
  if (approvedPaidJob && String(message).startsWith("Create a real paid Virtuals ACP job?")) {
    approvedPaidJob = false;
    return true;
  }
  return nativeConfirm(message);
};

function closeModal() {
  document.querySelector(".acp-confirm-backdrop")?.remove();
}

function showPaidJobModal(form, config) {
  closeModal();
  const backdrop = document.createElement("div");
  backdrop.className = "acp-confirm-backdrop";
  backdrop.innerHTML = `<section class="acp-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="acp-confirm-title">
    <p class="eyebrow">Real paid specialist purchase</p>
    <h2 id="acp-confirm-title">Create a Virtuals ACP job?</h2>
    <p>This assessment will purchase <strong>${escapeHtml(config.offering || "riskSynthesis")}</strong> and settle it on <strong>${escapeHtml(config.network || "Base mainnet")}</strong>.</p>
    <div class="acp-confirm-facts">
      <div><span>Offering</span><strong>${escapeHtml(config.offering || "riskSynthesis")}</strong></div>
      <div><span>Network</span><strong>${escapeHtml(config.network || "Base mainnet")}</strong></div>
      <div><span>Expected job spend</span><strong>0.1 ${escapeHtml(config.asset || "USDC")}</strong></div>
    </div>
    <p class="acp-confirm-warning">This creates and funds a real paid job.</p>
    <div class="acp-confirm-actions"><button type="button" class="secondary" data-cancel>Cancel</button><button type="button" data-approve>Create paid job</button></div>
  </section>`;
  document.body.append(backdrop);
  backdrop.querySelector("[data-cancel]").addEventListener("click", closeModal);
  backdrop.addEventListener("click", (event) => { if (event.target === backdrop) closeModal(); });
  backdrop.querySelector("[data-approve]").addEventListener("click", () => {
    approvedPaidJob = true;
    form.dataset.paidJobApproved = "true";
    closeModal();
    form.requestSubmit();
  });
}

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.id !== "assessment-form") return;
  if (!form.querySelector('[name="liveAcpEnabled"]')?.checked) return;
  if (form.dataset.paidJobApproved === "true") {
    delete form.dataset.paidJobApproved;
    return;
  }
  event.preventDefault();
  event.stopImmediatePropagation();
  const errorBox = form.querySelector("#assessment-error");
  try {
    const response = await nativeFetch("/api/acp/config");
    const config = await response.json();
    if (!response.ok || !config.enabled) throw new Error(config.status || "Live ACP is not configured");
    showPaidJobModal(form, config);
  } catch (error) {
    if (errorBox) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    }
  }
}, true);

function renderLatestPartnerProof() {
  if (location.hash !== "#partner-proof") return;
  const raw = sessionStorage.getItem(LIVE_PROOF_KEY);
  if (!raw) return;
  let latest;
  try { latest = JSON.parse(raw); } catch (_) { return; }
  const { job, proof } = latest;
  const main = document.querySelector("main");
  const panel = main?.querySelector(".proof-panel");
  if (!main || !panel || panel.dataset.liveProof === String(job.acpJobId)) return;
  main.querySelector(".proof-hero .eyebrow").textContent = "Latest live partner execution";
  main.querySelector(".proof-hero h1").textContent = "This run purchased risk synthesis through Virtuals ACP and settled it on Base.";
  const orb = main.querySelector(".proof-hero .spend-orb");
  if (orb) orb.innerHTML = `<small>ACP job</small><strong>${escapeHtml(job.acpJobId)}</strong><span>${escapeHtml(proof.network || "Base mainnet")}</span>`;
  panel.dataset.liveProof = String(job.acpJobId);
  panel.innerHTML = `<div class="proof-heading"><div><p class="eyebrow">Virtuals ACP → Base</p><h2>Current live run</h2></div><span class="status"><i>✓</i>${escapeHtml(job.status || "completed")}</span></div>
    <div class="proof-grid"><div><span>ACP job</span><strong>${escapeHtml(job.acpJobId)}</strong></div><div><span>Provider</span><strong title="${escapeHtml(job.providerId)}">${escapeHtml(short(job.providerId))}</strong></div><div><span>Offering</span><strong>riskSynthesis</strong></div><div><span>Escrowed</span><strong>${amount(proof.escrowedAmount)} USDC</strong></div><div><span>Provider release</span><strong>${amount(proof.providerReleasedAmount)} USDC</strong></div><div><span>Network</span><strong>${escapeHtml(proof.network || "Base mainnet")}</strong></div></div>
    <div class="transactions"><a href="${escapeHtml(proof.funding?.explorerUrl)}" target="_blank" rel="noreferrer"><span>Funding transaction</span><code>${escapeHtml(proof.funding?.transactionHash)}</code><b>View on BaseScan ↗</b></a><a href="${escapeHtml(proof.completion?.explorerUrl)}" target="_blank" rel="noreferrer"><span>Completion transaction</span><code>${escapeHtml(proof.completion?.transactionHash)}</code><b>View on BaseScan ↗</b></a></div>
    <p class="accounting">Verified settlement from this live assessment. Historical checkpoint job 75660 remains preserved in the build artifact as corroborating proof.</p>`;
}

new MutationObserver(renderLatestPartnerProof).observe(document.querySelector("#app"), { childList: true, subtree: true });
addEventListener("hashchange", renderLatestPartnerProof);
renderLatestPartnerProof();
