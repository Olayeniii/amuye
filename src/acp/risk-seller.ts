import { base } from "@account-kit/infra";
import {
  AcpAgent,
  AssetToken,
  PrivyAlchemyEvmProviderAdapter,
  type JobRoomEntry,
  type JobSession,
} from "@virtuals-protocol/acp-node-v2";

const required = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env var: ${name}`);
  return value;
};

const synthesizeRisk = (requirement: Record<string, any>) => {
  const viability = requirement.acceptedViabilityEvidence;
  if (!viability || viability.role !== "viability_onchain") {
    throw new Error("accepted viability evidence is required");
  }
  const metrics = viability.metrics || {};
  const protocol = viability.protocol || {};
  const risks: Array<Record<string, string>> = [];
  if (Number(metrics.auditCount || 0) === 0) {
    risks.push({ id: "missing-audit-evidence", severity: "high", reason: "No public audit record was supplied in the accepted viability evidence." });
  }
  if (Number(metrics.change7dPct || 0) <= -20) {
    risks.push({ id: "rapid-tvl-decline", severity: "high", reason: `Seven-day TVL change is ${metrics.change7dPct}%.` });
  }
  if (Number(metrics.chainCount || 0) >= 4) {
    risks.push({ id: "multi-chain-surface", severity: "medium", reason: `Deployment spans ${metrics.chainCount} chains.` });
  }
  if (["bridge", "bridges", "lending", "derivatives"].includes(String(protocol.category || "").toLowerCase())) {
    risks.push({ id: "category-exposure", severity: "medium", reason: `${protocol.category} protocols have material smart-contract and economic risk.` });
  }
  const high = risks.filter((item) => item.severity === "high").length;
  const medium = risks.filter((item) => item.severity === "medium").length;
  const continueToSecurity = high > 0 || medium >= 2;
  return {
    role: "risk_synthesis",
    objectiveSatisfied: false,
    continueToSecurity,
    gateReason: continueToSecurity
      ? "Security analysis is justified by material risk signals."
      : "No material combination of accepted risk signals justified security analysis.",
    identifiedRisks: risks,
    evidence: [
      { source: "viability_onchain", field: "metrics", value: metrics },
      { source: "viability_onchain", field: "protocol", value: protocol },
    ],
    consumedEvidenceRefs: ["viability_onchain"],
  };
};

async function main(): Promise<void> {
  const evmProvider = await PrivyAlchemyEvmProviderAdapter.create({
    walletAddress: required("ACP_RISK_PROVIDER_ADDRESS") as `0x${string}`,
    walletId: required("ACP_RISK_PROVIDER_WALLET_ID"),
    signerPrivateKey: required("ACP_RISK_PROVIDER_SIGNER_PRIVATE_KEY"),
    chains: [base],
    builderCode: process.env.ACP_BUILDER_CODE,
  });
  const seller = await AcpAgent.create({ evmProvider });
  const address = (await seller.getAddress()).toLowerCase();
  const me = await seller.getAgentByWalletAddress(address);
  const offeringName = required("ACP_RISK_OFFERING_NAME");
  const offering = me?.offerings.find((item) => item.name === offeringName);
  if (!offering) throw new Error(`registered offering not found: ${offeringName}`);
  const requirements = new Map<string, Record<string, unknown>>();

  seller.on("entry", async (session: JobSession, entry: JobRoomEntry) => {
    if (entry.kind === "message" && entry.contentType === "requirement" && session.status === "open") {
      try {
        process.stderr.write(`[amuye-risk-provider] job ${session.jobId}: requirement received\n`);
        const requirement = JSON.parse(entry.content) as Record<string, unknown>;
        synthesizeRisk(requirement);
        requirements.set(session.jobId.toString(), requirement);
        await session.setBudget(AssetToken.usdc(offering.priceValue, session.chainId));
        process.stderr.write(`[amuye-risk-provider] job ${session.jobId}: budget set to ${offering.priceValue} USDC\n`);
      } catch (error) {
        await session.sendMessage(String(error));
        await session.reject("invalid risk requirement");
      }
    }
    if (entry.kind === "system" && entry.event.type === "job.funded") {
      try {
        process.stderr.write(`[amuye-risk-provider] job ${session.jobId}: funded\n`);
        const requirement = requirements.get(session.jobId.toString());
        if (!requirement) throw new Error("requirement not found in ACP context");
        await session.submit(JSON.stringify(synthesizeRisk(requirement)));
        process.stderr.write(`[amuye-risk-provider] job ${session.jobId}: deliverable submitted\n`);
      } catch (error) {
        await session.sendMessage(String(error));
        await session.reject("risk synthesis failed");
      }
    }
  });

  await seller.start();
  process.stderr.write(`[amuye-risk-provider] listening at ${address}\n`);

  const keepAlive = setInterval(() => undefined, 60_000);
  await new Promise<void>((resolve, reject) => {
    let stopping = false;
    const stop = () => {
      if (stopping) return;
      stopping = true;
      clearInterval(keepAlive);
      void seller.stop().then(resolve, reject);
    };

    process.once("SIGINT", stop);
    process.once("SIGTERM", stop);
  });
}

main().catch((error) => {
  process.stderr.write(String(error));
  process.exitCode = 1;
});
