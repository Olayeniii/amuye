const data = await fetch("./demo-data.json").then((response) => {
  if (!response.ok) throw new Error("Execution evidence could not be loaded");
  return response.json();
});

const app = document.querySelector("#app");
const labels = {
  viability_onchain: "Viability",
  risk_synthesis: "Risk synthesis",
  security_analysis: "Security analysis",
};
const safe = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character]));
const shortAddress = (value) => `${value.slice(0, 8)}...${value.slice(-6)}`;
const money = (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });

function statusIcon(status) {
  return status === "completed" ? "✓" : status === "skipped" ? "−" : status === "cancelled" ? "×" : "•";
}

function graph(mode) {
  const roleById = Object.fromEntries(mode.graph.map((node) => [node.id, labels[node.role]]));
  return mode.graph.map((node, index) => `
    <article class="node node-${safe(node.status)}">
      <div class="node-index">0${index + 1}</div>
      <div class="node-body">
        <div class="node-title">
          <h3>${safe(labels[node.role])}</h3>
          <span class="status"><i>${statusIcon(node.status)}</i>${safe(node.status)}</span>
        </div>
        <dl class="node-meta">
          <div><dt>Depends on</dt><dd>${node.dependencies.length ? node.dependencies.map((id) => safe(roleById[id] || id)).join(", ") : "None"}</dd></div>
          <div><dt>Gate</dt><dd>${safe(node.gate || "No continuation gate")}</dd></div>
          <div><dt>Cost</dt><dd>${money(node.cost)}</dd></div>
        </dl>
        <p class="reason">${safe(node.reason || "Baseline node, no graph mutation")}</p>
      </div>
    </article>`).join("");
}

function evidence(mode) {
  return mode.evidence.map((item) => {
    const facts = item.metrics
      ? [`TVL $${money(item.metrics.currentTvlUsd)}`, `${item.metrics.chainCount} chain`, `${item.metrics.auditCount} audits`]
      : item.identifiedRisks
        ? [`${item.identifiedRisks.length} material risks`, `Security gate: ${item.continueToSecurity}`]
        : [`Assessment: ${item.assessment}`, `${item.findings?.length || 0} findings`];
    return `<div class="evidence-row"><strong>${safe(labels[item.role])}</strong><span>${facts.map(safe).join(" · ")}</span></div>`;
  }).join("");
}

function jobSummary(mode) {
  return `<section class="job-strip">
    <div class="job-objective"><span>Objective</span><strong>${safe(mode.request.objective)}</strong></div>
    <div><span>Budget</span><strong>${money(mode.request.maxBudget)}</strong></div>
    <div><span>Deadline</span><strong>${safe(new Date(mode.request.deadline).toLocaleDateString())}</strong></div>
    <div><span>Priority</span><strong>${safe(mode.request.priority)}</strong></div>
    <div class="constraints"><span>Hard constraints</span><strong>${mode.request.hardConstraints.map((item) => `<em>${safe(item)}</em>`).join("")}</strong></div>
  </section>`;
}

function modePage(mode) {
  return `
    <main>
      <section class="result-hero">
        <div>
          <p class="eyebrow">${safe(mode.eyebrow)}</p>
          <h1>${safe(mode.result)}</h1>
          <p class="verified"><i>✓</i>${safe(mode.verification)}</p>
        </div>
        <div class="spend-orb"><small>Spent</small><strong>${money(mode.execution.spent)}</strong><span>${money(mode.execution.remaining)} remaining</span></div>
      </section>
      ${jobSummary(mode)}
      <div class="main-grid">
        <section class="panel graph-panel">
          <div class="section-head"><div><p class="eyebrow">Decision path</p><h2>Execution graph</h2></div><span>${mode.execution.order.length} purchases</span></div>
          <div class="graph">${graph(mode)}</div>
          <div class="order"><span>Execution order</span>${mode.execution.order.map((role, index) => `<b>${index + 1}. ${safe(labels[role])}</b>`).join("")}</div>
        </section>
        <aside class="side-stack">
          <section class="panel memory-panel">
            <div class="panel-label"><span class="signal ${mode.memory.enabled ? "on" : ""}"></span>Sibyl memory ${mode.memory.enabled ? "ON" : "OFF"}</div>
            <h2>${mode.memory.enabled ? "Experience applied" : "Cold strategy"}</h2>
            <dl class="stacked-list">
              <div><dt>Recalled lesson</dt><dd>${safe(mode.memory.lessonId || "None")}</dd></div>
              <div><dt>Applicability</dt><dd>${safe(mode.memory.applicability)}</dd></div>
              <div><dt>Rule influenced</dt><dd>${safe(mode.memory.influencedRule)}</dd></div>
              <div><dt>Adapted for constraints</dt><dd>${mode.memory.adapted ? "Yes" : "No"}${mode.memory.adaptationReason ? `<small>${safe(mode.memory.adaptationReason)}</small>` : ""}</dd></div>
            </dl>
          </section>
          <section class="panel summary-panel">
            <div class="panel-label">Execution summary</div>
            <div class="metric-row"><div><span>Spent</span><strong>${money(mode.execution.spent)}</strong></div><div><span>Unspent</span><strong>${money(mode.execution.remaining)}</strong></div></div>
            <p><span>Purchased</span>${mode.execution.purchased.map((item) => `<b>${safe(labels[item.role])}</b>`).join("")}</p>
            <p><span>Early stop</span><b>${mode.execution.stoppedEarly ? safe(mode.execution.stopReason) : "No"}</b></p>
          </section>
        </aside>
      </div>
      <div class="lower-grid">
        <section class="panel"><div class="section-head"><div><p class="eyebrow">Accepted outputs</p><h2>Evidence</h2></div></div>${evidence(mode)}</section>
        <section class="panel learning-panel"><div class="section-head"><div><p class="eyebrow">Outcome to memory</p><h2>Learning record</h2></div><span class="confirmed">${mode.learning.confirmed ? "Confirmed" : "Pending"}</span></div>
          <p>${safe(mode.learning.reflection)}</p><div class="learning-decision"><span>Lesson decision</span><strong>${safe(mode.learning.decision)}</strong></div>
          <div class="ref"><span>Sibyl lesson</span><code>${safe(mode.learning.lessonId)}</code></div>
          <div class="ref"><span>Evidence event</span><code>${safe(mode.learning.evidenceRefs.join(", "))}</code></div>
        </section>
      </div>
    </main>`;
}

function proofPage() {
  const proof = data.partnerProof;
  return `<main>
    <section class="result-hero proof-hero"><div><p class="eyebrow">Verified partner execution</p><h1>Risk synthesis was purchased through Virtuals ACP and settled on Base.</h1><p class="verified"><i>✓</i>Receipts successful, USDC movements verified</p></div><div class="spend-orb"><small>ACP job</small><strong>${safe(proof.jobId)}</strong><span>${safe(proof.network)}</span></div></section>
    <section class="panel proof-panel">
      <div class="proof-heading"><div><p class="eyebrow">Virtuals ACP</p><h2>riskSynthesis settlement</h2></div><span class="status"><i>✓</i>completed</span></div>
      <div class="proof-grid"><div><span>Provider</span><strong title="${safe(proof.provider)}">${safe(shortAddress(proof.provider))}</strong></div><div><span>Network</span><strong>${safe(proof.network)} · ${proof.chainId}</strong></div><div><span>Escrowed</span><strong>${money(proof.escrow)} USDC</strong></div><div><span>Provider release</span><strong>${money(proof.providerRelease)} USDC</strong></div><div><span>Evaluator fee</span><strong>${money(proof.evaluatorFee)} USDC</strong></div><div><span>Platform fee</span><strong>${money(proof.platformFee)} USDC</strong></div></div>
      <div class="transactions"><a href="${safe(proof.funding.explorerUrl)}" target="_blank" rel="noreferrer"><span>Funding transaction · block ${proof.funding.blockNumber}</span><code>${safe(proof.funding.transactionHash)}</code><b>View on BaseScan ↗</b></a><a href="${safe(proof.completion.explorerUrl)}" target="_blank" rel="noreferrer"><span>Completion transaction · block ${proof.completion.blockNumber}</span><code>${safe(proof.completion.transactionHash)}</code><b>View on BaseScan ↗</b></a></div>
      <p class="accounting">0.1 USDC entered ACP escrow. Completion released 0.09 USDC to the provider, 0.005 USDC to the evaluator, and 0.005 USDC to the platform treasury.</p>
    </section>
  </main>`;
}

function render() {
  const route = location.hash.slice(1) || "memory-on";
  const mode = data.modes.find((item) => item.key === route) || data.modes[1];
  app.innerHTML = `<header><a class="brand" href="#memory-on"><img src="./assets/amuye-logo.png" alt="Amúyẹ"/><span><strong>Amúyẹ</strong><small>Procurement intelligence</small></span></a><nav>${data.modes.map((item) => `<a class="${route === item.key ? "active" : ""}" href="#${item.key}">${safe(item.label)}</a>`).join("")}<a class="${route === "partner-proof" ? "active" : ""}" href="#partner-proof">Partner proof</a></nav><span class="live"><i></i>Evidence loaded</span></header>${route === "partner-proof" ? proofPage() : modePage(mode)}<footer><span>Amúyẹ</span><p>Specialist procurement shaped by execution evidence.</p></footer>`;
}

addEventListener("hashchange", render);
render();
