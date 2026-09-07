import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { resolve } from "node:path";
import { promisify } from "node:util";

const root = resolve(import.meta.dirname, "..");
const frontend = resolve(root, "frontend");
const dist = resolve(root, "dist");
const execFileAsync = promisify(execFile);

const load = async (path) => JSON.parse(await readFile(resolve(root, path), "utf8"));
const settlement = (await load("artifacts/checkpoint6/job-75660-settlement.json")).settlementProof;
const comparison = await load("artifacts/checkpoint7/memory-off-vs-on.json");
const adaptation = await load("artifacts/checkpoint8/mandatory-security-adaptation.json");
const lesson = comparison.control.persistedLesson;
const { stdout: commitOutput } = await execFileAsync("git", ["rev-parse", "HEAD"], { cwd: root });
const commitHash = commitOutput.trim();

function compactRun(key, label, run, overrides = {}) {
  const evidence = run.execution.result.evidence;
  const security = run.execution.finalGraph.find((node) => node.type === "security_analysis");
  return {
    key,
    label,
    eyebrow: overrides.eyebrow || "Controlled protocol assessment",
    result: overrides.result || (security.status === "skipped"
      ? "Assessment completed without deeper security work. Accepted risk evidence did not justify the purchase."
      : "Assessment completed across viability, risk, and security specialists."),
    verification: "Specialist output contracts passed validation",
    request: run.request,
    memory: {
      enabled: run.memory.operationalMemoryAvailableToPlanner,
      freshProcessId: run.freshProcessId,
      lessonId: run.memory.recalledLessonIds[0] || null,
      applicability: run.memory.applicabilityDecision,
      influencedRule: overrides.influencedRule || (run.memory.recalledLessonIds.length
        ? "Security work is purchased only when accepted risk evidence justifies it."
        : "No memory rule influenced this plan."),
      adapted: overrides.adapted || false,
      adaptationReason: overrides.adaptationReason || null,
    },
    graph: run.execution.finalGraph.map((node) => ({
      id: node.id,
      role: node.type,
      status: node.status,
      dependencies: node.dependencies,
      gate: node.conditionalTrigger,
      cost: node.actualCost,
      reason: node.mutationReason,
      verification: node.evaluationStatus,
    })),
    mutations: run.execution.mutations,
    execution: {
      purchased: run.execution.providerJobsPurchased,
      order: run.execution.executionSequence,
      spent: run.execution.spent,
      remaining: run.execution.remainingBudget,
      stoppedEarly: run.execution.stoppedEarly,
      stopReason: run.execution.stopReason,
    },
    evidence,
    learning: overrides.learning || {
      reflection: run.memory.operationalMemoryAvailableToPlanner
        ? "This controlled execution tested an existing lesson without changing it."
        : "Cold execution showed that unconditional security purchasing can spend more than the evidence requires.",
      decision: run.memory.operationalMemoryAvailableToPlanner ? "No lesson mutation in this run" : "Progressive purchasing lesson available from evaluated execution history",
      lessonId: lesson.id,
      evidenceRefs: lesson.supportingExecutionRefs,
      confirmed: true,
    },
  };
}

const modeA = compactRun("memory-off", "Memory OFF", comparison.runA_memoryOff);
const modeB = compactRun("memory-on", "Memory ON", comparison.runB_memoryOn);
const controlledProof = comparison.comparison;
const memoryOffSecurity = comparison.runA_memoryOff.execution.finalGraph.find((node) => node.type === "security_analysis");
const memoryOnSecurity = comparison.runB_memoryOn.execution.finalGraph.find((node) => node.type === "security_analysis");
const memoryOnRisk = comparison.runB_memoryOn.execution.result.evidence.find((item) => item.role === "risk_synthesis");
const memoryConsequence = {
  withoutExperience: {
    freshProcessId: comparison.runA_memoryOff.freshProcessId,
    memoryReadPerformed: comparison.runA_memoryOff.memory.operationalMemoryAvailableToPlanner,
    specialistsCommissioned: comparison.runA_memoryOff.execution.providerJobsPurchased.length,
    spend: comparison.runA_memoryOff.execution.spent,
    budget: comparison.runA_memoryOff.request.maxBudget,
    securityStatus: memoryOffSecurity.status,
    reason: comparison.runA_memoryOff.strategy.source,
  },
  withExperience: {
    freshProcessId: comparison.runB_memoryOn.freshProcessId,
    memoryReadPerformed: comparison.runB_memoryOn.memory.operationalMemoryAvailableToPlanner,
    recalledLessonCount: comparison.runB_memoryOn.memory.recalledLessonIds.length,
    recalledLessonId: comparison.runB_memoryOn.memory.recalledLessonIds[0],
    planningMemoryRefs: comparison.runB_memoryOn.memory.strategyMemoryRefs,
    specialistsCommissioned: comparison.runB_memoryOn.execution.providerJobsPurchased.length,
    spend: comparison.runB_memoryOn.execution.spent,
    budget: comparison.runB_memoryOn.request.maxBudget,
    securityStatus: memoryOnSecurity.status,
    securityGate: memoryOnSecurity.conditionalTrigger,
    securitySkipReason: memoryOnSecurity.mutationReason,
    riskContinueToSecurity: memoryOnRisk.continueToSecurity,
    reason: controlledProof.changedAction.lessonTrace,
  },
  avoidedSpecialistCount: controlledProof.rolesPurchasedOnlyWithMemoryOff.length,
  preservedBudget: controlledProof.spendAvoidedByMemory,
};

if (
  memoryConsequence.withoutExperience.spend - memoryConsequence.withExperience.spend !== memoryConsequence.preservedBudget
  || memoryConsequence.withExperience.securitySkipReason !== controlledProof.changedAction.memoryOnReason
  || memoryConsequence.withExperience.recalledLessonId !== controlledProof.recalledLessonId
  || !memoryConsequence.withExperience.planningMemoryRefs.includes(memoryConsequence.withExperience.recalledLessonId)
) throw new Error("Controlled memory consequence does not match backend execution evidence");

const changedRun = {
  request: adaptation.request,
  memory: {
    operationalMemoryAvailableToPlanner: true,
    recalledLessonIds: [adaptation.recalledLessonId],
    applicabilityDecision: adaptation.applicabilityAssessment,
  },
  execution: {
    result: adaptation.finalResult,
    finalGraph: adaptation.finalGraph,
    mutations: adaptation.mandatorySecurityEvidence.policyMutation ? [adaptation.mandatorySecurityEvidence.policyMutation] : [],
    providerJobsPurchased: adaptation.purchases,
    executionSequence: adaptation.executionSequence,
    spent: adaptation.spend,
    remainingBudget: adaptation.remainingBudget,
    stoppedEarly: false,
    stopReason: null,
  },
};
const modeC = compactRun("mandatory-security", "Mandatory security", changedRun, {
  eyebrow: "Changed client constraint",
  result: "Mandatory security analysis completed even though risk evidence did not recommend deeper work.",
  influencedRule: adaptation.overriddenRule,
  adapted: true,
  adaptationReason: adaptation.reasonForOverride,
  learning: {
    reflection: "The recalled lesson remained useful for ordering and the viability-to-risk gate. Its security gate conflicted with this job's authority rules.",
    decision: "Job-local override only. The stored Sibyl lesson was not mutated.",
    lessonId: adaptation.recalledLessonId,
    evidenceRefs: lesson.supportingExecutionRefs,
    confirmed: adaptation.lessonIntegrity.unchanged,
  },
});

const payload = {
  buildEvidence: { commitHash, builtAt: new Date().toISOString() },
  product: {
    name: "Amúyẹ",
    line: "Amúyẹ remembers whether specialist work earned its cost, then uses that experience after a fresh restart to decide whether the same kind of purchase is worth making again.",
  },
  memoryConsequence,
  modes: [modeA, modeB, modeC],
  partnerProof: {
    jobId: settlement.jobId,
    provider: settlement.provider,
    offering: "riskSynthesis",
    network: settlement.network,
    chainId: settlement.chainId,
    asset: "USDC",
    escrow: settlement.escrowedAmount,
    providerRelease: settlement.providerReleasedAmount,
    evaluatorFee: settlement.evaluatorFeeAmount,
    platformFee: settlement.platformFeeAmount,
    funding: settlement.funding,
    completion: settlement.completion,
  },
};

if (payload.partnerProof.chainId !== 8453 || payload.partnerProof.jobId !== "75660") throw new Error("Expected Base proof for ACP job 75660");
if (payload.modes[0].execution.spent !== 95 || payload.modes[1].execution.spent !== 35) throw new Error("Controlled comparison artifact does not match expected proof");

await rm(dist, { recursive: true, force: true });
await mkdir(resolve(dist, "assets"), { recursive: true });
await cp(resolve(frontend, "index.html"), resolve(dist, "index.html"));
await cp(resolve(frontend, "src", "app.js"), resolve(dist, "app.js"));
await cp(resolve(frontend, "src", "styles.css"), resolve(dist, "styles.css"));
await cp(resolve(frontend, "src", "readability.css"), resolve(dist, "readability.css"));
await cp(resolve(frontend, "src", "demo-framing.js"), resolve(dist, "demo-framing.js"));
await cp(resolve(frontend, "src", "runtime-fixes.js"), resolve(dist, "runtime-fixes.js"));
await cp(resolve(frontend, "assets", "amuye-logo.png"), resolve(dist, "assets", "amuye-logo.png"));
await writeFile(resolve(dist, "demo-data.json"), `${JSON.stringify(payload, null, 2)}\n`);
console.log(`Built Amúyẹ execution console at ${dist}`);
