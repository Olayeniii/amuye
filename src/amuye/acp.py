from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .domain import JobRequest, ProviderJob, TaskNode, new_id, utc_now
from .execution import SpecialistEvidence
from .specialists import ProtocolAssessmentProvider


@dataclass(frozen=True)
class AcpPurchaseResult:
    acp_job_id: str
    provider_id: str
    quoted_cost: float
    settled_cost: float
    status: str
    deliverable: Any
    deliverable_ref: str | None
    evaluation_ref: str | None
    submitted_at: str
    completed_at: str | None


class AcpRiskClient(Protocol):
    def purchase_risk(self, requirement: dict[str, Any], max_cost: float) -> AcpPurchaseResult: ...


class AcpPurchaseError(RuntimeError):
    def __init__(self, message: str, result: AcpPurchaseResult | None = None) -> None:
        super().__init__(message)
        self.result = result


class NodeAcpRiskClient:
    """Runs the official Virtuals ACP Node v2 buyer as a bounded subprocess."""

    REQUIRED_ENV = (
        "ACP_BUYER_WALLET_ADDRESS",
        "ACP_BUYER_WALLET_ID",
        "ACP_BUYER_SIGNER_PRIVATE_KEY",
        "ACP_RISK_PROVIDER_ADDRESS",
        "ACP_RISK_OFFERING_NAME",
    )

    def __init__(self, project_root: Path | None = None, timeout_seconds: float = 150) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.timeout_seconds = timeout_seconds

    def purchase_risk(self, requirement: dict[str, Any], max_cost: float) -> AcpPurchaseResult:
        missing = [name for name in self.REQUIRED_ENV if not os.environ.get(name)]
        if missing:
            raise AcpPurchaseError(f"missing ACP configuration: {', '.join(missing)}")
        payload = {"requirement": requirement, "maxCost": max_cost}
        try:
            completed = subprocess.run(
                ["npm", "exec", "--", "tsx", "src/acp/risk-buyer.ts"],
                cwd=self.project_root,
                input=json.dumps(payload),
                text=True,
                stdout=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AcpPurchaseError("ACP risk purchase timed out") from exc
        if not completed.stdout.strip():
            raise AcpPurchaseError("ACP buyer returned no lifecycle result")
        try:
            raw = json.loads(completed.stdout)
            result = AcpPurchaseResult(
                acp_job_id=str(raw["acpJobId"]),
                provider_id=str(raw["providerId"]),
                quoted_cost=float(raw.get("quotedCost", 0)),
                settled_cost=float(raw.get("settledCost", 0)),
                status=str(raw["status"]),
                deliverable=raw.get("deliverable"),
                deliverable_ref=raw.get("deliverableRef"),
                evaluation_ref=raw.get("evaluationRef"),
                submitted_at=str(raw["submittedAt"]),
                completed_at=raw.get("completedAt"),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AcpPurchaseError("ACP buyer returned an invalid lifecycle result") from exc
        if completed.returncode != 0 or result.status != "completed":
            raise AcpPurchaseError(str(raw.get("error") or f"ACP job ended as {result.status}"), result)
        return result


class FakeAcpRiskClient:
    """Network-free ACP boundary used by tests."""

    def __init__(self, outcomes: list[AcpPurchaseResult | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[dict[str, Any]] = []
        self.max_costs: list[float] = []

    def purchase_risk(self, requirement: dict[str, Any], max_cost: float) -> AcpPurchaseResult:
        self.requests.append(requirement)
        self.max_costs.append(max_cost)
        if not self.outcomes:
            raise AcpPurchaseError("no fake ACP outcome configured")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class AcpRiskAssessmentProvider:
    """Local viability/security with risk synthesis purchased over ACP v2."""

    def __init__(self, acp_client: AcpRiskClient,
                 local_provider: ProtocolAssessmentProvider | None = None,
                 event_callback: Callable[[dict[str, Any]], None] | None = None,
                 max_purchase_cost: float | None = None) -> None:
        self.acp_client = acp_client
        self.local = local_provider or ProtocolAssessmentProvider()
        self.event_callback = event_callback
        self.max_purchase_cost = max_purchase_cost
        self.calls: list[str] = []
        self.contexts: list[dict[str, dict[str, Any]]] = []

    @staticmethod
    def _provider_job(node: TaskNode, result: AcpPurchaseResult) -> ProviderJob:
        return ProviderJob(
            id=new_id("provider_job"),
            parentJobId=node.jobId,
            taskNodeId=node.id,
            providerId=result.provider_id,
            providerRole="risk_synthesis",
            acpJobId=result.acp_job_id,
            quotedCost=result.quoted_cost,
            settledCost=result.settled_cost,
            status=result.status,
            submittedAt=result.submitted_at,
            completedAt=result.completed_at,
            deliverableRef=result.deliverable_ref,
            evaluationRef=result.evaluation_ref,
        )

    def purchase(self, node: TaskNode, request: JobRequest,
                 context: dict[str, dict[str, Any]],
                 remaining_budget: float) -> SpecialistEvidence:
        self.calls.append(node.type)
        self.contexts.append(context)
        if node.type != "risk_synthesis":
            return self.local.purchase(node, request, context, remaining_budget)
        viability = context.get("viability_onchain")
        if not viability:
            raise ValueError("ACP risk synthesis requires accepted viability evidence")
        requirement = {
            "taskClass": "protocol_assessment",
            "role": "risk_synthesis",
            "objective": request.objective,
            "deadline": request.deadline,
            "priority": request.priority,
            "hardConstraints": request.hardConstraints,
            "acceptedViabilityEvidence": viability,
            "requiredOutputContract": {
                "role": "risk_synthesis",
                "fields": [
                    "objectiveSatisfied", "continueToSecurity", "gateReason",
                    "identifiedRisks", "evidence", "consumedEvidenceRefs",
                ],
            },
        }
        authorized_cost = min(remaining_budget, self.max_purchase_cost or remaining_budget)
        if self.event_callback is not None:
            self.event_callback({
                "type": "acp_purchase_started",
                "provider": os.environ.get("ACP_RISK_PROVIDER_ADDRESS", "configured ACP provider"),
                "offering": os.environ.get("ACP_RISK_OFFERING_NAME", "riskSynthesis"),
                "network": "Base mainnet",
                "maxCost": authorized_cost,
            })
        try:
            result = self.acp_client.purchase_risk(requirement, authorized_cost)
        except AcpPurchaseError as exc:
            provider_job = self._provider_job(node, exc.result) if exc.result else None
            return SpecialistEvidence(
                status="failed",
                findings={"providerError": str(exc)},
                actualCost=exc.result.settled_cost if exc.result else 0,
                providerId=exc.result.provider_id if exc.result else "virtuals-acp",
                providerJob=provider_job,
            )
        if self.event_callback is not None:
            self.event_callback({
                "type": "acp_job_completed",
                "acpJobId": result.acp_job_id,
                "provider": result.provider_id,
                "quotedCost": result.quoted_cost,
                "settledCost": result.settled_cost,
                "status": result.status,
                "deliverableRef": result.deliverable_ref,
            })
        return SpecialistEvidence(
            status="completed",
            findings=result.deliverable,
            actualCost=result.settled_cost,
            providerId=result.provider_id,
            providerJob=self._provider_job(node, result),
        )
