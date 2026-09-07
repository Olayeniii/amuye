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
let liveJob = null;
let pollTimer = null;

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
          <div><dt>Cost</dt><dd>${money(node.cost)} budget units</dd></div>
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
  return `${mode.intent ? `<section class="intent-strip"><span>Selected intent</span><strong>${safe(mode.intent.intent.replaceAll("_", " "))}</strong><small>${mode.intent.requiredCapabilities.map((item) => safe(labels[item] || item)).join(" · ")}</small><p>${safe(mode.intent.reason)}</p></section>` : ""}<section class="job-strip">
    <div class="job-objective"><span>Objective</span><strong>${safe(mode.request.objective)}</strong></div>
    <div><span>Budget</span><strong>${money(mode.request.maxBudget)} units</strong></div>
    <div><span>Deadline</span><strong>${safe(new Date(mode.request.deadline).toLocaleDateString())}</strong></div>
    <div><span>Priority</span><strong>${safe(mode.request.priority)}</strong></div>
    <div class="constraints"><span>Hard constraints</span><strong>${mode.request.hardConstraints.map((item) => `<em>${safe(item)}</em>`).join("")}</strong></div>
  </section>`;
}

function memorySourcePanel(memory) {
  const source = memory.source;
  if (!memory.enabled) {
    return `<div class="memory-source unavailable"><strong>View Sibyl source</strong><span>No Sibyl memory read for this run.</span></div>`;
  }
  if (!source) {
    return `<div class="memory-source unavailable"><strong>View Sibyl source</strong><span>This is reproducible artifact evidence, not a live Sibyl response. Run a Memory ON assessment to inspect its source record.</span></div>`;
  }
  if (!source.readPerformed || !source.records.length) {
    return `<details class="memory-source"><summary>View Sibyl source</summary><div class="source-empty">${safe(source.message)}</div></details>`;
  }
  return `<details class="memory-source"><summary>View Sibyl source</summary>
    <div class="source-session"><span>Process</span><code>${safe(source.processSessionId)}</code><span>Sibyl source</span><code>${safe(source.databaseSource)}</code><span>Returned</span><code>${safe(source.returnedLessonIds.join(", "))}</code><span>Applied by plan</span><code>${safe(source.plannerMemoryRefs.join(", ") || "None")}</code></div>
    ${source.records.map((lesson) => `<div class="source-record">
      <div><span>Lesson ID</span><code>${safe(lesson.id)}</code></div>
      <div><span>Task pattern</span><strong>${safe(lesson.taskPattern)}</strong></div>
      <div class="wide"><span>Learned strategy</span><p>${safe(lesson.strategy)}</p></div>
      <div class="wide"><span>Reasoning</span><p>${safe(lesson.reasoning)}</p></div>
      <div class="wide"><span>Applicability conditions</span><p>${lesson.applicabilityConditions.map(safe).join(" · ")}</p></div>
      <div class="wide"><span>Non-applicability conditions</span><p>${lesson.nonApplicabilityConditions.map(safe).join(" · ")}</p></div>
      <div><span>Confidence</span><strong>${safe(lesson.confidence)}</strong></div>
      <div><span>Status</span><strong>${safe(lesson.status)}</strong></div>
      <div><span>Last updated</span><strong>${safe(lesson.lastUpdatedAt)}</strong></div>
      <div class="wide"><span>Supporting Sibyl journal events</span><code>${safe(lesson.supportingExecutionRefs.join(", ") || "None")}</code></div>
      <div class="wide"><span>Contradictory evidence</span><code>${safe(lesson.contradictoryEvidenceRefs.join(", ") || "None")}</code></div>
    </div>`).join("")}
    <div class="source-decision"><span>Planner applicability</span><p>${safe(source.plannerApplicability)}</p><span>Execution rule influenced</span>${source.influencedRules.map((item) => `<p><strong>${safe(labels[item.taskNode] || item.taskNode)}:</strong> ${safe(item.rule)} <small>${safe(item.reason)}</small></p>`).join("")}</div>
  </details>`;
}

function visibleLesson(mode) {
  if (mode.memory?.lessonRecord) return { lesson: mode.memory.lessonRecord, state: "recalled" };
  if (mode.learning?.lesson) return { lesson: mode.learning.lesson, state: "learned" };
  return null;
}

function lessonSummary(mode) {
  const visible = visibleLesson(mode);
  if (!visible) return "";
  const lesson = visible.lesson;
  const title = visible.state === "recalled" ? "What Amúyẹ recalled" : "Lesson learned this run";
  return `<div class="source-record">
    <div class="wide"><span>${title}</span><p>${safe(lesson.strategy)}</p></div>
    <div class="wide"><span>Why</span><p>${safe(lesson.reasoning)}</p></div>
  </div>`;
}

function memoryOutcome(mode) {
  if (!mode.memory?.enabled) return "";
  const risk = mode.evidence?.find((item) => item.role === "risk_synthesis");
  const security = mode.graph?.find((node) => node.role === "security_analysis");
  if (mode.memory.adapted && risk?.continueToSecurity === true && security?.status === "completed") {
    return `<div class="source-decision"><span>Outcome this run</span><p>Memory changed when downstream work was committed, but current risk evidence still justified security analysis. The final spend therefore remained ${money(mode.execution.spent)} budget units.</p></div>`;
  }
  if (mode.memory.adapted && risk?.continueToSecurity === false && security?.status === "skipped") {
    return `<div class="source-decision"><span>Outcome this run</span><p>Memory made security conditional, current risk evidence did not justify it, and the security purchase was skipped.</p></div>`;
  }
  return "";
}

function memoryConsequencePanel(mode) {
  if (mode.key !== "memory-off" && mode.key !== "memory-on") return "";
  const proof = data.memoryConsequence;
  const off = proof.withoutExperience;
  const on = proof.withExperience;
  return `<section class="memory-consequence panel">
    <div class="section-head"><div><p class="eyebrow">What Sibyl changed</p><h2>Prior execution experience changed one purchase</h2></div><span>Same task · same budget · same specialists</span></div>
    <div class="consequence-grid">
      <article class="consequence-run ${mode.key === "memory-off" ? "active" : ""}">
        <p>No prior execution experience</p>
        <strong>${safe(off.specialistsCommissioned)} specialists commissioned</strong>
        <dl><div><dt>Spend</dt><dd>${money(off.spend)} / ${money(off.budget)} budget units</dd></div><div><dt>Security specialist</dt><dd>${safe(off.securityStatus === "completed" ? "Commissioned" : off.securityStatus)}</dd></div><div><dt>Reason</dt><dd>Cold execution</dd></div></dl>
      </article>
      <article class="consequence-run recalled ${mode.key === "memory-on" ? "active" : ""}">
        <p>Experience recalled from Sibyl</p>
        <strong>${safe(on.specialistsCommissioned)} specialists commissioned</strong>
        <dl><div><dt>Spend</dt><dd>${money(on.spend)} / ${money(on.budget)} budget units</dd></div><div><dt>Security specialist</dt><dd>${safe(on.securityStatus === "skipped" ? "Skipped unnecessary security purchase" : on.securityStatus)}</dd></div><div><dt>Reason</dt><dd>${safe(on.reason)}</dd></div></dl>
      </article>
    </div>
    <div class="consequence-result"><strong>${safe(proof.avoidedSpecialistCount)} unnecessary specialist purchase avoided</strong><strong>${money(proof.preservedBudget)} budget units preserved</strong></div>
  </section>`;
}

function memoryCausalStrip(mode) {
  if (mode.key !== "memory-on") return "";
  const proof = data.memoryConsequence.withExperience;
  return `<section class="causal-strip" aria-label="Sibyl procurement consequence">
    <span>Experience recalled from Sibyl<small>${safe(proof.recalledLessonId)}</small></span>
    <i>→</i><span>Security became conditional<small>${safe(proof.securityGate)}</small></span>
    <i>→</i><span>Risk evidence did not justify deeper work<small>continueToSecurity: ${safe(proof.riskContinueToSecurity)}</small></span>
    <i>→</i><span>Security purchase skipped<small>${safe(proof.securitySkipReason)}</small></span>
    <i>→</i><span>${money(data.memoryConsequence.preservedBudget)} budget units preserved</span>
  </section>`;
}

function modePage(mode) {
  const comparison = mode.key === "memory-off" || mode.key === "memory-on" ? `<div class="comparison-bar"><span>Controlled difference</span><b class="${mode.key === "memory-off" ? "selected" : ""}">Memory OFF · security purchased · 95 units</b><b class="${mode.key === "memory-on" ? "selected" : ""}">Memory ON · security skipped · 35 units</b></div>` : "";
  const visible = visibleLesson(mode);
  const memoryHeading = !mode.memory.enabled
    ? "No prior execution experience"
    : mode.memory.lessonId
      ? "Experience applied"
      : visible?.state === "learned"
        ? "Lesson learned"
        : "No applicable experience recalled";
  return `
    <main>
      <section class="result-hero">
        <div>
          <p class="eyebrow">${safe(mode.eyebrow)}</p>
          <h1>${safe(mode.result)}</h1>
          <p class="verified"><i>✓</i>${safe(mode.verification)}</p>
        </div>
        <div class="spend-orb"><small>Spent</small><strong>${money(mode.execution.spent)}</strong><span>budget units</span><span>${money(mode.execution.remaining)} remaining</span></div>
      </section>
      ${comparison}
      ${memoryConsequencePanel(mode)}
      ${memoryCausalStrip(mode)}
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
            <h2>${safe(memoryHeading)}</h2>
            ${mode.key === "memory-on" ? `<p class="fresh-session-statement">Fresh process. Prior conversation unavailable.<strong>Sibyl recalled ${safe(data.memoryConsequence.withExperience.recalledLessonCount)} applicable execution lesson</strong></p>` : ""}
            ${mode.key === "memory-off" ? `<p class="fresh-session-statement">Fresh process. No prior execution experience available.<strong>No Sibyl memory read for this run.</strong></p>` : ""}
            <dl class="stacked-list">
              <div><dt>Recalled lesson</dt><dd>${safe(mode.memory.lessonId || "None")}</dd></div>
              ${mode.memory.freshProcessId ? `<div><dt>Fresh process</dt><dd>${safe(mode.memory.freshProcessId)}</dd></div>` : ""}
              <div><dt>Applicability</dt><dd>${safe(mode.memory.applicability)}</dd></div>
              <div><dt>Rule influenced</dt><dd>${safe(mode.memory.influencedRule)}</dd></div>
              <div><dt>Adapted for constraints</dt><dd>${mode.memory.adapted ? "Yes" : "No"}${mode.memory.adaptationReason ? `<small>${safe(mode.memory.adaptationReason)}</small>` : ""}</dd></div>
            </dl>
            ${lessonSummary(mode)}
            ${memoryOutcome(mode)}
            ${memorySourcePanel(mode.memory)}
          </section>
          <section class="panel summary-panel">
            <div class="panel-label">Execution summary</div>
            <div class="metric-row"><div><span>Spent, units</span><strong>${money(mode.execution.spent)}</strong></div><div><span>Unspent, units</span><strong>${money(mode.execution.remaining)}</strong></div></div>
            <p><span>Purchased</span>${mode.execution.purchased.map((item) => `<b>${safe(labels[item.role])}</b>`).join("")}</p>
            <p><span>Early stop</span><b>${mode.execution.stoppedEarly ? safe(mode.execution.stopReason) : "No"}</b></p>
          </section>
        </aside>
      </div>
      <div class="lower-grid">
        <section class="panel"><div class="section-head"><div><p class="eyebrow">Accepted outputs</p><h2>Evidence</h2></div></div>${evidence(mode)}</section>
        <section class="panel learning-panel"><div class="section-head"><div><p class="eyebrow">Outcome to memory</p><h2>Learning record</h2></div><span class="confirmed">${mode.learning.confirmed ? "Confirmed" : "Pending"}</span></div>
          <p>${safe(mode.learning.reflection)}</p><div class="learning-decision"><span>Lesson decision</span><strong>${safe(mode.learning.decision)}</strong></div>
          ${mode.learning.lesson ? `<div class="source-record"><div class="wide"><span>Learned strategy</span><p>${safe(mode.learning.lesson.strategy)}</p></div><div class="wide"><span>Reasoning</span><p>${safe(mode.learning.lesson.reasoning)}</p></div></div>` : ""}
          <div class="ref"><span>Sibyl lesson</span><code>${safe(mode.learning.lessonId)}</code></div>
          <div class="ref"><span>Evidence event</span><code>${safe(mode.learning.evidenceRefs.join(", "))}</code></div>
        </section>
      </div>
      ${liveAcpPanel(mode)}
    </main>`;
}

function liveAcpPanel(mode) {
  if (!mode.acp || mode.acp.providerMode !== "live Virtuals ACP risk purchase on Base mainnet") return "";
  const jobs = mode.acp.providerJobs || [];
  const proofs = mode.acp.settlementProofs || [];
  return `<section class="panel live-acp-panel">
    <div class="section-head"><div><p class="eyebrow">Paid specialist procurement</p><h2>Virtuals ACP on Base</h2></div><span>${jobs.length ? "VERIFIED LIVE RUN" : "NO ACP JOB CREATED"}</span></div>
    ${jobs.length ? jobs.map((job) => {
      const proof = proofs.find((item) => String(item.jobId) === String(job.acpJobId));
      return `<div class="acp-job">
        <div class="proof-grid"><div><span>ACP job</span><strong>${safe(job.acpJobId)}</strong></div><div><span>Provider</span><strong title="${safe(job.providerId)}">${safe(shortAddress(job.providerId))}</strong></div><div><span>Offering</span><strong>riskSynthesis</strong></div><div><span>Quote</span><strong>${money(job.quotedCost)} USDC</strong></div><div><span>Recorded cost</span><strong>${money(job.settledCost)} USDC</strong></div><div><span>Status</span><strong>${safe(job.status)}</strong></div></div>
        <div class="ref"><span>Deliverable</span><code>${safe(job.deliverableRef || "Not available")}</code></div>
        <div class="ref"><span>Evaluation</span><code>${safe(job.evaluationRef || "Not available")}</code></div>
        ${proof ? `<div class="transactions"><a href="${safe(proof.funding.explorerUrl)}" target="_blank" rel="noreferrer"><span>Funding · ${money(proof.escrowedAmount)} USDC escrow</span><code>${safe(proof.funding.transactionHash)}</code><b>View on BaseScan ↗</b></a><a href="${safe(proof.completion.explorerUrl)}" target="_blank" rel="noreferrer"><span>Completion · ${money(proof.providerReleasedAmount)} USDC provider release</span><code>${safe(proof.completion.transactionHash)}</code><b>View on BaseScan ↗</b></a></div><p class="accounting">Verified on ${safe(proof.network)}: ${money(proof.escrowedAmount)} USDC escrowed, ${money(proof.providerReleasedAmount)} USDC released to the provider, ${money(proof.evaluatorFeeAmount)} USDC evaluator fee, and ${money(proof.platformFeeAmount)} USDC platform fee.</p>` : `<p class="accounting">No settlement proof was attached.</p>`}
      </div>`;
    }).join("") : `<p class="accounting">The viability gate ended this run before risk synthesis, so no paid ACP job was created.</p>`}
  </section>`;
}

function newAssessmentPage() {
  const defaultDeadline = new Date(Date.now() + 86400000).toISOString().slice(0, 16);
  return `<main>
    <section class="result-hero form-hero"><div><p class="eyebrow">Live procurement run</p><h1>Commission a protocol assessment</h1><p class="verified">Amúyẹ owns planning, specialist selection, gates, evaluation, and learning.</p></div><div class="safety-note"><strong>Local mode by default</strong><span>A real paid ACP job requires selecting Live ACP and confirming its purchase notice.</span></div></section>
    <form id="assessment-form" class="panel assessment-form">
      <label class="wide"><span>Objective</span><textarea name="objective" required>Assess protocol Aave for integration viability and material risks</textarea></label>
      <label><span>Maximum budget, units</span><input name="maxBudget" type="number" min="1" step="0.1" value="100" required></label>
      <label><span>Deadline</span><input name="deadline" type="datetime-local" value="${defaultDeadline}" required></label>
      <label><span>Priority</span><select name="priority"><option>balanced</option><option>risk</option><option>urgent</option></select></label>
      <label><span>Client ID</span><input name="clientId" value="ui-demo-client" required></label>
      <label class="wide"><span>Hard constraints, one per line</span><textarea name="hardConstraints" required>protocolSlug=aave</textarea><small>Example: protocolSlug=aave. Add "security analysis is mandatory" to enforce security.</small></label>
      <label class="memory-choice"><input name="memoryEnabled" type="checkbox" checked><span>Use Sibyl operational memory</span></label>
      <label class="memory-choice live-acp-choice"><input name="liveAcpEnabled" type="checkbox"><span>Live ACP risk purchase</span><small>Uses Base mainnet and can spend real USDC. You will see a confirmation before submission.</small></label>
      <p id="assessment-error" class="assessment-error" hidden></p>
      <div class="form-actions"><button type="submit">Run assessment</button><span>Task class: protocol_assessment</span></div>
    </form>
  </main>`;
}

function eventLabel(event) {
  return ({ request_accepted: "Request accepted", intake_accepted: "Intake validated", memory_retrieval_started: "Sibyl retrieval", plan_created: "Plan created", graph_mutation: "Graph updated", specialist_purchase: `Purchased ${labels[event.role] || event.role}`, acp_purchase_started: "Virtuals ACP purchase started", acp_job_completed: `ACP job ${event.acpJobId} completed`, settlement_verified: `Base settlement verified for ACP job ${event.acpJobId}`, evidence_accepted: `Accepted ${labels[event.role] || event.role} evidence`, evaluation_completed: "Execution evaluated", reflection_completed: "Reflection completed", lesson_updated: "Sibyl lesson updated", execution_completed: "Result ready", execution_failed: "Execution failed" })[event.type] || event.type;
}

function liveProgressPage(job) {
  const result = job.result;
  if (result) return modePage(liveResultToMode(result));
  return `<main><section class="result-hero"><div><p class="eyebrow">Live run</p><h1>${job.error ? "Assessment failed" : "Amúyẹ is executing the assessment"}</h1><p class="verified"><i>${job.error ? "×" : "•"}</i>${safe(job.error || "Polling real backend state")}</p></div><div class="spend-orb"><small>Status</small><strong class="status-word">${safe(job.status)}</strong><span>${job.providerMode === "live_acp" ? "Live ACP" : "Local specialists"}</span></div></section>
    ${job.request ? jobSummary({ request: job.request }) : ""}
    <section class="panel timeline-panel"><div class="section-head"><div><p class="eyebrow">Backend events</p><h2>Live execution</h2></div><span>${job.events.length} events</span></div><div class="timeline">${job.events.map((event) => `<div><i></i><strong>${safe(eventLabel(event))}</strong><span>${safe(new Date(event.at).toLocaleTimeString())}</span>${event.reason ? `<small>${safe(event.reason)}</small>` : ""}</div>`).join("")}</div></section></main>`;
}

function liveResultToMode(result) {
  const nodes = result.execution.nodes;
  const outputs = result.finalResult.evidence;
  const recalled = result.memory.recalledLessonIds;
  const sourceRecords = result.memory.source?.records || [];
  const recalledRecord = recalled.length ? sourceRecords.find((lesson) => lesson.id === recalled[0]) || null : null;
  return {
    eyebrow: "Live procurement result",
    result: result.finalResult.decision,
    verification: result.finalResult.verification,
    request: result.request,
    intent: result.strategy.objectiveIntent,
    memory: { enabled: result.memory.enabled, lessonId: recalled[0] || null, lessonRecord: recalledRecord, applicability: result.memory.applicability, influencedRule: recalled.length ? result.strategy.rationale : "No operational lesson influenced this plan.", adapted: result.strategy.source === "adapted", adaptationReason: result.strategy.source === "adapted" ? result.strategy.applicabilityAssessment : null, source: result.memory.source },
    graph: nodes.map((node) => ({ id: node.id, role: node.type, status: node.status, dependencies: node.dependencies, gate: node.conditionalTrigger, cost: node.actualCost, reason: node.mutationReason, verification: node.evaluationStatus })),
    mutations: result.execution.mutations,
    execution: { purchased: result.execution.purchasedRoles.map((role) => ({ role })), order: result.execution.purchasedRoles, spent: result.execution.spent, remaining: result.execution.remainingBudget, stoppedEarly: result.execution.stoppedEarly, stopReason: result.execution.stopReason },
    evidence: outputs,
    learning: { reflection: [...result.reflection.successfulDecisions, ...result.reflection.failedDecisions].join(" ") || "Execution evaluated before reflection.", decision: result.lessonUpdate ? `${result.lessonUpdate.action} ${result.lessonUpdate.lesson.id}` : "Execution recorded, no lesson mutation required", lessonId: result.lessonUpdate?.lesson?.id || recalled[0] || "None", lesson: result.lessonUpdate?.lesson || null, evidenceRefs: result.reflection.evidenceRefs, confirmed: true },
    acp: { providerMode: result.providerMode, providerJobs: result.execution.providerJobs, settlementProofs: result.settlementProofs },
  };
}

async function pollJob(statusUrl) {
  const response = await fetch(statusUrl);
  liveJob = await response.json();
  if (location.hash === "#live-run") render();
  if (!["completed", "failed"].includes(liveJob.status)) pollTimer = setTimeout(() => pollJob(statusUrl), 450);
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
  const content = route === "new-assessment" ? newAssessmentPage() : route === "live-run" ? (liveJob ? liveProgressPage(liveJob) : newAssessmentPage()) : route === "partner-proof" ? proofPage() : modePage(mode);
  const evidenceRoute = data.modes.some((item) => item.key === route) || route === "partner-proof";
  app.innerHTML = `<header><a class="brand" href="#memory-on"><img src="./assets/amuye-logo.png" alt="Amúyẹ"/><span><strong>Amúyẹ</strong><small>Procurement intelligence</small></span></a><nav><a class="new-action ${route === "new-assessment" || route === "live-run" ? "active" : ""}" href="#new-assessment">New Assessment</a>${data.modes.map((item) => `<a class="${route === item.key ? "active" : ""}" href="#${item.key}">${safe(item.label)}</a>`).join("")}<a class="${route === "partner-proof" ? "active" : ""}" href="#partner-proof">Partner proof</a></nav><span class="live"><i></i>${evidenceRoute ? "Reproducible proof" : "Live backend"}</span></header>${content}<footer><span>Amúyẹ</span><p>Procurement decisions shaped by execution evidence.</p><code title="${safe(data.buildEvidence.commitHash)}">commit ${safe(data.buildEvidence.commitHash.slice(0, 7))} · built ${safe(new Date(data.buildEvidence.builtAt).toISOString().slice(0, 16).replace("T", " "))} UTC</code></footer>`;

  document.querySelector("#assessment-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const request = { objective: form.get("objective"), maxBudget: Number(form.get("maxBudget")), deadline: new Date(form.get("deadline")).toISOString(), priority: form.get("priority"), hardConstraints: String(form.get("hardConstraints")).split("\n").map((item) => item.trim()).filter(Boolean), clientId: form.get("clientId"), taskClass: "protocol_assessment" };
    event.currentTarget.querySelector("button").disabled = true;
    try {
      const memory = form.get("memoryEnabled") ? "on" : "off";
      const liveAcp = Boolean(form.get("liveAcpEnabled"));
      let providerQuery = "provider=local";
      if (liveAcp) {
        const configResponse = await fetch("/api/acp/config");
        const config = await configResponse.json();
        if (!configResponse.ok || !config.enabled) throw new Error(`Live ACP is not configured${config.missingConfiguration?.length ? `: ${config.missingConfiguration.join(", ")}` : ""}`);
        const approved = confirm([
          "Create a real paid Virtuals ACP job?",
          `Provider: ${config.provider}`,
          `Offering: ${config.offering}`,
          `Network: ${config.network}`,
          `Maximum expected spend: ${money(config.maxExpectedSpend)} ${config.asset}`,
          config.notice,
        ].join("\n"));
        if (!approved) throw new Error("Live ACP purchase was not confirmed.");
        providerQuery = "provider=live_acp&confirmAcp=true";
      }
      const response = await fetch(`/api/assessments?memory=${memory}&${providerQuery}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
      const accepted = await response.json();
      if (!response.ok) throw new Error(accepted.error || "Assessment was rejected");
      liveJob = { id: accepted.jobId, status: accepted.status, providerMode: liveAcp ? "live_acp" : "local", request, events: [], result: null, error: null };
      location.hash = "live-run";
      pollJob(accepted.statusUrl);
    } catch (error) {
      const errorBox = event.currentTarget.querySelector("#assessment-error");
      errorBox.textContent = error.message;
      errorBox.hidden = false;
      event.currentTarget.querySelector("button").disabled = false;
    }
  });
}

addEventListener("hashchange", render);
render();