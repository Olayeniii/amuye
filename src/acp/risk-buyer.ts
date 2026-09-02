import { base } from "@account-kit/infra";
import {
  AcpAgent,
  PrivyAlchemyEvmProviderAdapter,
  type JobRoomEntry,
  type JobSession,
} from "@virtuals-protocol/acp-node-v2";

type Input = { requirement: Record<string, unknown>; maxCost: number };
type Result = {
  acpJobId: string;
  providerId: string;
  quotedCost: number;
  settledCost: number;
  status: string;
  deliverable: unknown;
  deliverableRef: string | null;
  evaluationRef: string | null;
  submittedAt: string;
  completedAt: string | null;
  error?: string;
};

const required = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env var: ${name}`);
  return value;
};

const log = (message: string): void => {
  process.stderr.write(`[amuye-acp-buyer] ${message}\n`);
};

let liveBuyer: AcpAgent | null = null;

const readInput = async (): Promise<Input> => {
  let body = "";
  for await (const chunk of process.stdin) body += chunk;
  return JSON.parse(body) as Input;
};

const parseRisk = (raw: string): Record<string, unknown> => {
  const value = JSON.parse(raw) as Record<string, unknown>;
  if (
    value.role !== "risk_synthesis" ||
    typeof value.objectiveSatisfied !== "boolean" ||
    typeof value.continueToSecurity !== "boolean" ||
    typeof value.gateReason !== "string" ||
    !Array.isArray(value.identifiedRisks) ||
    !Array.isArray(value.evidence) ||
    !Array.isArray(value.consumedEvidenceRefs)
  ) throw new Error("deliverable does not satisfy the risk-synthesis contract");
  return value;
};

async function main(): Promise<void> {
  const input = await readInput();
  const providerAddress = required("ACP_RISK_PROVIDER_ADDRESS");
  const offeringName = required("ACP_RISK_OFFERING_NAME");
  const evmProvider = await PrivyAlchemyEvmProviderAdapter.create({
    walletAddress: required("ACP_BUYER_WALLET_ADDRESS") as `0x${string}`,
    walletId: required("ACP_BUYER_WALLET_ID"),
    signerPrivateKey: required("ACP_BUYER_SIGNER_PRIVATE_KEY"),
    chains: [base],
    builderCode: process.env.ACP_BUILDER_CODE,
  });
  const buyer = await AcpAgent.create({
    evmProvider,
  });
  liveBuyer = buyer;
  const buyerAddress = await buyer.getAddress();
  log(`connected as ${buyerAddress}`);
  let current: Result | null = null;
  let active: JobSession | null = null;
  let resolved = false;
  const finish = async (result: Result, code = 0) => {
    if (resolved) return;
    resolved = true;
    clearTimeout(timer);
    await buyer.stop();
    process.stdout.write(JSON.stringify(result));
    process.exitCode = code;
  };
  buyer.on("entry", async (session: JobSession, entry: JobRoomEntry) => {
    active = session;
    if (!current) return;
    if (entry.kind !== "system") return;
    if (entry.event.type === "budget.set") {
      current.quotedCost = Number(entry.event.amount);
      log(`job ${session.jobId}: provider quoted ${current.quotedCost} USDC`);
      if (current.quotedCost > input.maxCost) {
        log(`job ${session.jobId}: quote rejected by budget policy`);
        await session.reject("budget over Amúyẹ authority");
        return;
      }
      await session.fetchJob();
      await session.fund();
      log(`job ${session.jobId}: funded`);
    } else if (entry.event.type === "job.submitted") {
      log(`job ${session.jobId}: deliverable received`);
      try {
        current.deliverable = parseRisk(entry.event.deliverable);
        current.deliverableRef = `acp:${session.jobId}:deliverable`;
        current.evaluationRef = `acp:${session.jobId}:self-evaluation`;
        await session.complete("Risk output contract accepted by Amúyẹ");
        log(`job ${session.jobId}: deliverable accepted`);
      } catch (error) {
        current.error = String(error);
        await session.reject("malformed risk deliverable");
      }
    } else if (entry.event.type === "job.completed") {
      current.status = "completed";
      current.settledCost = current.quotedCost;
      current.completedAt = new Date().toISOString();
      log(`job ${session.jobId}: completed`);
      await finish(current);
    } else if (entry.event.type === "job.rejected") {
      current.status = "rejected";
      current.settledCost = 0;
      current.completedAt = new Date().toISOString();
      current.error ||= entry.event.reason;
      log(`job ${session.jobId}: rejected, ${current.error}`);
      await finish(current, 2);
    } else if (entry.event.type === "job.expired") {
      current.status = "expired";
      current.settledCost = 0;
      current.completedAt = new Date().toISOString();
      current.error = "ACP job expired";
      log(`job ${session.jobId}: expired`);
      await finish(current, 2);
    }
  });
  await buyer.start();
  log("event stream started");
  const agent = await buyer.getAgentByWalletAddress(providerAddress);
  if (!agent) throw new Error("registered ACP risk provider was not found");
  const offering = agent.offerings.find((item) => item.name === offeringName);
  if (!offering) throw new Error(`ACP offering not found: ${offeringName}`);
  log(`provider offering found: ${offering.name} at ${offering.priceValue} USDC`);
  if (Number(offering.priceValue) > input.maxCost) {
    throw new Error("ACP offering price exceeds Amúyẹ remaining authority");
  }
  const submittedAt = new Date().toISOString();
  const jobId = await buyer.createJobFromOffering(
    base.id,
    offering,
    agent.walletAddress,
    input.requirement,
    { evaluatorAddress: buyerAddress },
  );
  current = {
    acpJobId: jobId.toString(),
    providerId: agent.walletAddress,
    quotedCost: Number(offering.priceValue),
    settledCost: 0,
    status: "created",
    deliverable: null,
    deliverableRef: null,
    evaluationRef: null,
    submittedAt,
    completedAt: null,
  };
  log(`job ${jobId}: created`);
  const timeoutMs = Number(process.env.ACP_JOB_TIMEOUT_MS || "120000");
  timer = setTimeout(async () => {
    if (active) await active.reject("Amúyẹ ACP timeout").catch(() => undefined);
    if (current) {
      current.status = "timeout";
      current.error = "ACP job timed out";
      current.completedAt = new Date().toISOString();
      log(`job ${current.acpJobId}: timed out after ${timeoutMs}ms`);
      await finish(current, 2);
    }
  }, timeoutMs);
}

let timer: ReturnType<typeof setTimeout>;
main().catch(async (error) => {
  process.stderr.write(String(error));
  if (liveBuyer) await liveBuyer.stop().catch(() => undefined);
  process.exitCode = 1;
});
