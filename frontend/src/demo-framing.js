const PURCHASE_PROOF = {
  purchase: "Security analysis",
  cost: "60 budget units",
  priorOutcome: "Did not change the decision",
  learnedPolicy: "Buy security again only when current risk evidence justifies it",
  freshDecision: "Skipped on the fresh run",
};

function activeMemoryMode(main) {
  const selected = main.querySelector(".comparison-bar .selected")?.textContent || "";
  if (selected.includes("Memory OFF")) return "memory-off";
  if (selected.includes("Memory ON")) return "memory-on";
  return null;
}

function proofCard(modeKey) {
  const section = document.createElement("section");
  section.className = "panel purchase-memory-proof";

  if (modeKey === "memory-off") {
    section.innerHTML = `
      <div class="section-head">
        <div><p class="eyebrow">Cold execution → full specialist path</p><h2>Why was security purchased?</h2></div>
        <span>Memory OFF proof</span>
      </div>
      <div class="purchase-proof-grid">
        <div><small>Fresh process</small><strong>No prior execution experience</strong><span>No Sibyl memory read influenced this run.</span></div>
        <b>→</b>
        <div><small>Cold plan</small><strong>Full specialist path retained</strong><span>There was no learned repurchase rule available to make security conditional.</span></div>
        <b>→</b>
        <div><small>Security decision</small><strong>Security analysis commissioned</strong><span>The cold execution purchased the deeper specialist rather than skipping it from prior experience.</span></div>
        <b>→</b>
        <div><small>Run outcome</small><strong>95 budget units spent</strong><span>Three specialists were commissioned.</span></div>
      </div>`;
    return section;
  }

  section.innerHTML = `
    <div class="section-head">
      <div><p class="eyebrow">Purchase → usefulness → memory → next purchase</p><h2>Did the previous purchase earn its cost?</h2></div>
      <span>Sibyl memory proof</span>
    </div>
    <div class="purchase-proof-grid">
      <div><small>Purchase made</small><strong>${PURCHASE_PROOF.purchase}</strong><span>${PURCHASE_PROOF.cost}</span></div>
      <b>→</b>
      <div><small>Usefulness evaluated</small><strong>${PURCHASE_PROOF.priorOutcome}</strong><span>Accepted risk evidence had already resolved whether deeper work was needed.</span></div>
      <b>→</b>
      <div><small>Stored in Sibyl</small><strong>${PURCHASE_PROOF.learnedPolicy}</strong><span>Sibyl preserves this learned purchasing experience so a fresh Amúyẹ process can recall it before deciding whether to buy security analysis again.</span></div>
      <b>→</b>
      <div><small>Fresh-process decision</small><strong>${PURCHASE_PROOF.freshDecision}</strong><span>Current risk evidence did not justify buying the same specialist again.</span></div>
    </div>`;
  return section;
}

function partnerFlowCard(panel) {
  const job = panel.querySelector(".acp-job");
  if (!job) return null;
  const values = [...job.querySelectorAll(".proof-grid > div")].reduce((result, item) => {
    const key = item.querySelector("span")?.textContent?.trim();
    const value = item.querySelector("strong")?.textContent?.trim();
    if (key && value) result[key] = value;
    return result;
  }, {});
  const settlementVerified = panel.querySelectorAll(".transactions a").length >= 2;
  const section = document.createElement("div");
  section.className = "partner-live-flow";
  section.innerHTML = `
    <div><small>Amúyẹ purchase decision</small><strong>Risk synthesis required</strong></div><b>→</b>
    <div><small>Virtuals ACP exercised</small><strong>Job ${values["ACP job"] || "created"}</strong><span>${values.Offering || "riskSynthesis"} · ${values.Status || "completed"}</span></div><b>→</b>
    <div><small>Specialist work returned</small><strong>${values.Provider || "ACP provider"}</strong><span>${values["Recorded cost"] || values.Quote || "paid job"}</span></div><b>→</b>
    <div><small>Base action</small><strong>${settlementVerified ? "Settlement verified ✓" : "Settlement pending"}</strong><span>${settlementVerified ? "Funding + completion transactions from this job" : "Waiting for onchain proof"}</span></div>`;
  return section;
}

function applyPurchaseFraming() {
  const main = document.querySelector("main");
  if (!main) return;
  const consequence = main.querySelector(".memory-consequence");
  const modeKey = activeMemoryMode(main);
  if (consequence && modeKey && !main.querySelector(".purchase-memory-proof")) {
    const heading = consequence.querySelector("h2");
    if (heading) heading.textContent = "Amúyẹ remembers whether a purchase was useful, then changes the next buying decision";
    const eyebrow = consequence.querySelector(".eyebrow");
    if (eyebrow) eyebrow.textContent = "The proof";
    consequence.insertAdjacentElement("afterend", proofCard(modeKey));
    const causal = main.querySelector(".causal-strip");
    if (causal) causal.setAttribute("aria-label", "Purchase usefulness memory consequence");
    const learningHeading = main.querySelector(".learning-panel h2");
    if (learningHeading) learningHeading.textContent = modeKey === "memory-off" ? "Cold-run learning record" : "Purchase usefulness record";
  }

  const partnerPanel = main.querySelector(".live-acp-panel");
  if (partnerPanel && !partnerPanel.querySelector(".partner-live-flow")) {
    const heading = partnerPanel.querySelector("h2");
    if (heading) heading.textContent = "Live partner execution: Virtuals ACP → Base";
    const badge = partnerPanel.querySelector(".section-head > span");
    if (badge) badge.textContent = "THIS RUN · PARTNER WORK VISIBLE";
    const flow = partnerFlowCard(partnerPanel);
    if (flow) partnerPanel.querySelector(".section-head")?.insertAdjacentElement("afterend", flow);
  }
}

new MutationObserver(applyPurchaseFraming).observe(document.querySelector("#app"), { childList: true, subtree: true });
addEventListener("hashchange", applyPurchaseFraming);
applyPurchaseFraming();
