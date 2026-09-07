const PURCHASE_PROOF = {
  purchase: "Security analysis",
  cost: "60 budget units",
  priorOutcome: "Did not change the decision",
  learnedPolicy: "Buy security again only when current risk evidence justifies it",
  freshDecision: "Skipped on the fresh run",
};

function proofCard() {
  const section = document.createElement("section");
  section.className = "panel purchase-memory-proof";
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
      <div><small>Stored in Sibyl</small><strong>${PURCHASE_PROOF.learnedPolicy}</strong><span>Memory is a conditional repurchase policy, not a claim that security is always useless.</span></div>
      <b>→</b>
      <div><small>Fresh-process decision</small><strong>${PURCHASE_PROOF.freshDecision}</strong><span>Current risk evidence did not justify buying the same specialist again.</span></div>
    </div>`;
  return section;
}

function applyPurchaseFraming() {
  const main = document.querySelector("main");
  if (!main) return;
  const consequence = main.querySelector(".memory-consequence");
  if (!consequence || main.querySelector(".purchase-memory-proof")) return;

  const heading = consequence.querySelector("h2");
  if (heading) heading.textContent = "Amúyẹ remembers whether a purchase was useful, then changes the next buying decision";
  const eyebrow = consequence.querySelector(".eyebrow");
  if (eyebrow) eyebrow.textContent = "The proof";

  consequence.insertAdjacentElement("afterend", proofCard());

  const causal = main.querySelector(".causal-strip");
  if (causal) {
    causal.setAttribute("aria-label", "Purchase usefulness memory consequence");
  }

  const learningHeading = [...main.querySelectorAll(".learning-panel h2")][0];
  if (learningHeading) learningHeading.textContent = "Purchase usefulness record";
}

new MutationObserver(applyPurchaseFraming).observe(document.querySelector("#app"), { childList: true, subtree: true });
addEventListener("hashchange", applyPurchaseFraming);
applyPurchaseFraming();
