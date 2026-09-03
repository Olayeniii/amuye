from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .domain import ExecutionStrategy, JobRequest, ProviderJob, TaskNode, new_id, utc_now


TERMINAL_STATUSES = {
    "completed",
    "failed",
    "skipped",
    "replaced",
    "cancelled",
}


@dataclass(frozen=True)
class SpecialistEvidence:
    status: str
    findings: dict[str, Any]
    actualCost: float | None = None
    providerId: str | None = None
    providerJob: ProviderJob | None = None


class SpecialistProvider(Protocol):
    def purchase(
        self,
        node: TaskNode,
        request: JobRequest,
        context: dict[str, dict[str, Any]],
        remaining_budget: float,
    ) -> Any: ...


class SpecialistContractError(ValueError):
    pass


def _require_fields(output: dict[str, Any], role: str,
                    contract: dict[str, type]) -> None:
    for field_name, expected_type in contract.items():
        if field_name not in output:
            raise SpecialistContractError(f"{role} output is missing {field_name}")
        value = output[field_name]
        if expected_type is bool:
            valid = type(value) is bool
        else:
            valid = isinstance(value, expected_type)
        if not valid:
            raise SpecialistContractError(
                f"{role}.{field_name} must be {expected_type.__name__}"
            )


def _require_object_list(output: dict[str, Any], field_name: str, role: str) -> None:
    if any(not isinstance(item, dict) for item in output[field_name]):
        raise SpecialistContractError(f"{role}.{field_name} must contain objects")


def _validate_role_details(output: dict[str, Any], role: str) -> None:
    _require_object_list(output, "evidence", role)
    if role == "viability_onchain":
        for key in ("slug", "name"):
            if not isinstance(output["protocol"].get(key), str) or not output["protocol"][key]:
                raise SpecialistContractError(f"{role}.protocol.{key} must be a non-empty string")
        metrics = output["metrics"]
        if not isinstance(metrics.get("currentTvlUsd"), (int, float)):
            raise SpecialistContractError(f"{role}.metrics.currentTvlUsd must be numeric")
        if not isinstance(metrics.get("chains"), list):
            raise SpecialistContractError(f"{role}.metrics.chains must be a list")
    elif role == "risk_synthesis":
        _require_object_list(output, "identifiedRisks", role)
        if any(not isinstance(item, str) for item in output["consumedEvidenceRefs"]):
            raise SpecialistContractError(f"{role}.consumedEvidenceRefs must contain strings")
    elif role == "security_analysis":
        _require_object_list(output, "findings", role)
        if any(not isinstance(item, str) for item in output["consumedEvidenceRefs"]):
            raise SpecialistContractError(f"{role}.consumedEvidenceRefs must contain strings")


SPECIALIST_CONTRACTS: dict[str, dict[str, type]] = {
    "viability_onchain": {
        "role": str,
        "objectiveSatisfied": bool,
        "continueToRisk": bool,
        "gateReason": str,
        "evidence": list,
        "protocol": dict,
        "metrics": dict,
    },
    "risk_synthesis": {
        "role": str,
        "objectiveSatisfied": bool,
        "continueToSecurity": bool,
        "gateReason": str,
        "identifiedRisks": list,
        "evidence": list,
        "consumedEvidenceRefs": list,
    },
    "security_analysis": {
        "role": str,
        "objectiveSatisfied": bool,
        "assessment": str,
        "findings": list,
        "evidence": list,
        "consumedEvidenceRefs": list,
    },
}


def validate_specialist_evidence(raw: Any, role: str) -> SpecialistEvidence:
    if isinstance(raw, SpecialistEvidence):
        evidence = raw
    elif isinstance(raw, dict):
        if "findings" in raw and isinstance(raw.get("findings"), dict):
            evidence = SpecialistEvidence(
                status=raw.get("status", "completed"),
                findings=raw["findings"],
                actualCost=raw.get("actualCost"),
                providerId=raw.get("providerId"),
                providerJob=raw.get("providerJob"),
            )
        else:
            evidence = SpecialistEvidence(status="completed", findings=raw)
    else:
        raise SpecialistContractError(f"{role} provider returned a non-object output")
    if evidence.status not in {"completed", "failed"}:
        raise SpecialistContractError(f"{role}.status must be completed or failed")
    if evidence.status == "failed":
        return evidence
    contract = SPECIALIST_CONTRACTS[role]
    _require_fields(evidence.findings, role, contract)
    if evidence.findings["role"] != role:
        raise SpecialistContractError(f"{role}.role does not match the purchased role")
    if "gateReason" in evidence.findings and not evidence.findings["gateReason"].strip():
        raise SpecialistContractError(f"{role}.gateReason cannot be blank")
    _validate_role_details(evidence.findings, role)
    return evidence


@dataclass(frozen=True)
class GraphMutation:
    sequence: int
    nodeId: str
    mutation: str
    fromStatus: str | None
    toStatus: str | None
    reason: str
    createdAt: str = field(default_factory=utc_now)
    relatedNodeId: str | None = None


@dataclass
class ExecutionResult:
    jobId: str
    status: str
    spent: float
    remainingBudget: float
    purchasedRoles: list[str]
    outputs: dict[str, dict[str, Any]]
    nodes: list[dict[str, Any]]
    mutations: list[dict[str, Any]]
    stoppedEarly: bool
    stopReason: str | None
    providerJobs: list[dict[str, Any]] = field(default_factory=list)


class ScriptedSpecialistProvider:
    """Deterministic specialist fixture for graph tests, not an ACP adapter."""

    def __init__(self, outcomes: dict[str, list[Any]]) -> None:
        self._outcomes = {role: list(items) for role, items in outcomes.items()}
        self.calls: list[str] = []
        self.contexts: list[dict[str, dict[str, Any]]] = []

    def purchase(self, node: TaskNode, request: JobRequest,
                 context: dict[str, dict[str, Any]],
                 remaining_budget: float) -> Any:
        self.calls.append(node.type)
        self.contexts.append(context)
        available = self._outcomes.get(node.type, [])
        if not available:
            raise RuntimeError(f"no scripted evidence for {node.type}")
        outcome = available.pop(0)
        if not isinstance(outcome, SpecialistEvidence) or outcome.status != "completed":
            return outcome
        findings = dict(outcome.findings)
        if "role" in findings:
            return outcome
        findings["role"] = node.type
        findings.setdefault("objectiveSatisfied", False)
        if node.type == "viability_onchain":
            findings.setdefault("continueToRisk", False)
            findings.setdefault("gateReason", "scripted viability gate")
            findings.setdefault("evidence", [])
            findings.setdefault("protocol", {"slug": "scripted", "name": "Scripted Protocol"})
            findings.setdefault("metrics", {"currentTvlUsd": 0.0, "chains": []})
        elif node.type == "risk_synthesis":
            findings.setdefault("continueToSecurity", False)
            findings.setdefault("gateReason", "scripted risk gate")
            findings.setdefault("identifiedRisks", [])
            findings.setdefault("evidence", [])
            findings.setdefault("consumedEvidenceRefs", ["viability_onchain"])
        elif node.type == "security_analysis":
            findings.setdefault("assessment", "scripted")
            findings.setdefault("findings", [])
            findings.setdefault("evidence", [])
            findings.setdefault("consumedEvidenceRefs", ["viability_onchain", "risk_synthesis"])
        return SpecialistEvidence(
            status=outcome.status,
            findings=findings,
            actualCost=outcome.actualCost,
            providerId=outcome.providerId,
            providerJob=outcome.providerJob,
        )


class TaskGraph:
    def __init__(self, strategy: ExecutionStrategy) -> None:
        self.nodes: dict[str, TaskNode] = {node.id: node for node in strategy.orderedSteps}
        self.order: list[str] = [node.id for node in strategy.orderedSteps]
        self.mutations: list[GraphMutation] = []

    def _record(
        self,
        node_id: str,
        mutation: str,
        reason: str,
        *,
        from_status: str | None = None,
        to_status: str | None = None,
        related_node_id: str | None = None,
    ) -> None:
        if not reason.strip():
            raise ValueError("every graph mutation requires a reason")
        self.mutations.append(GraphMutation(
            sequence=len(self.mutations) + 1,
            nodeId=node_id,
            mutation=mutation,
            fromStatus=from_status,
            toStatus=to_status,
            reason=reason,
            relatedNodeId=related_node_id,
        ))

    def transition(self, node: TaskNode, status: str, reason: str) -> None:
        previous = node.status
        node.status = status
        node.mutationReason = reason
        self._record(node.id, "status_transition", reason,
                     from_status=previous, to_status=status)

    def dependencies_completed(self, node: TaskNode) -> bool:
        return all(self.nodes[dependency].status == "completed"
                   for dependency in node.dependencies)

    def has_terminal_dependency(self, node: TaskNode) -> bool:
        return any(self.nodes[dependency].status in {
            "failed", "skipped", "cancelled"
        } for dependency in node.dependencies)

    def replace(self, failed: TaskNode, replacement: TaskNode, reason: str) -> None:
        self.transition(failed, "replaced", reason)
        index = self.order.index(failed.id)
        self.nodes[replacement.id] = replacement
        self.order.insert(index + 1, replacement.id)
        self._record(replacement.id, "node_added", reason,
                     to_status=replacement.status, related_node_id=failed.id)
        for node in self.nodes.values():
            if failed.id not in node.dependencies:
                continue
            node.dependencies = [replacement.id if item == failed.id else item
                                 for item in node.dependencies]
            self._record(node.id, "dependency_rewired", reason,
                         related_node_id=replacement.id)

    def active_nodes(self) -> list[TaskNode]:
        return [self.nodes[node_id] for node_id in self.order]


class ExecutionController:
    def __init__(
        self,
        request: JobRequest,
        strategy: ExecutionStrategy,
        provider: SpecialistProvider,
        *,
        max_replacements_per_role: int = 1,
    ) -> None:
        self.request = request
        self.strategy = strategy
        self.provider = provider
        self.graph = TaskGraph(strategy)
        self.spent = 0.0
        self.outputs: dict[str, dict[str, Any]] = {}
        self.purchased_roles: list[str] = []
        self.replacement_counts: dict[str, int] = {}
        self.max_replacements_per_role = max_replacements_per_role
        self.stopped_early = False
        self.stop_reason: str | None = None
        self.provider_jobs: list[ProviderJob] = []

    def _mandatory_security_required(self) -> bool:
        normalized = " ".join(self.request.hardConstraints).lower().replace("-", " ").replace("_", " ")
        return "mandatory security" in normalized or "security analysis is mandatory" in normalized

    def _mandatory_security_completed(self) -> bool:
        return any(
            node.type == "security_analysis" and node.status == "completed"
            for node in self.graph.active_nodes()
        )

    def _specialist_context(self) -> dict[str, dict[str, Any]]:
        context: dict[str, dict[str, Any]] = {}
        for node_id, output in self.outputs.items():
            node = self.graph.nodes[node_id]
            if node.status == "completed":
                context[node.type] = output
        return context

    def _gate_satisfied(self, node: TaskNode) -> tuple[bool, str]:
        if node.type == "security_analysis" and self._mandatory_security_required():
            return True, "security continuation gate overridden by hard client constraint: mandatory security analysis"
        if not node.conditionalTrigger:
            return True, "node has no continuation gate"
        dependency_outputs = [self.outputs.get(item, {}) for item in node.dependencies]
        if node.type == "risk_synthesis":
            allowed = any(output.get("continueToRisk") is True for output in dependency_outputs)
            return allowed, "viability evidence justified risk synthesis" if allowed else "viability evidence did not justify risk synthesis"
        if node.type == "security_analysis":
            allowed = any(output.get("continueToSecurity") is True for output in dependency_outputs)
            return allowed, "risk evidence justified security analysis" if allowed else "risk evidence did not justify security analysis"
        return False, f"unsupported continuation gate for {node.type}"

    def _skip_remaining(self, reason: str) -> None:
        for node in self.graph.active_nodes():
            if node.status not in TERMINAL_STATUSES:
                self.graph.transition(node, "skipped", reason)

    def _replacement_for(self, failed: TaskNode, evidence: SpecialistEvidence) -> TaskNode | None:
        count = self.replacement_counts.get(failed.type, 0)
        if count >= self.max_replacements_per_role:
            return None
        self.replacement_counts[failed.type] = count + 1
        return TaskNode(
            id=new_id("node"),
            jobId=failed.jobId,
            type=failed.type,
            description=failed.description,
            assignedProvider=evidence.providerId or f"replacement-{failed.type}-{count + 1}",
            dependencies=list(failed.dependencies),
            estimatedCost=failed.estimatedCost,
            conditionalTrigger=failed.conditionalTrigger,
            inputRefs=list(failed.inputRefs),
            mutationReason=f"replacement created after {failed.id} failed",
        )

    def run(self) -> ExecutionResult:
        while True:
            progress = False
            for node in self.graph.active_nodes():
                if node.status in TERMINAL_STATUSES or node.status == "running":
                    continue
                if self.graph.has_terminal_dependency(node):
                    self.graph.transition(node, "skipped", "a required dependency did not complete")
                    progress = True
                    continue
                if not self.graph.dependencies_completed(node):
                    if node.status != "waiting":
                        self.graph.transition(node, "waiting", "waiting for dependencies to complete")
                        progress = True
                    continue
                gate_allowed, gate_reason = self._gate_satisfied(node)
                if not gate_allowed:
                    self.graph.transition(node, "skipped", gate_reason)
                    progress = True
                    continue
                if node.status != "ready":
                    self.graph.transition(node, "ready", gate_reason)
                if self.spent + node.estimatedCost > self.request.maxBudget:
                    self.graph.transition(node, "cancelled", "purchase would exceed the client budget ceiling")
                    progress = True
                    continue
                self.graph.transition(node, "running", "dependencies and policy checks passed; specialist work purchased")
                node.startedAt = utc_now()
                context = self._specialist_context()
                node.inputRefs = [f"evidence:{node_id}" for node_id, output in self.outputs.items()
                                  if self.graph.nodes[node_id].status == "completed"]
                raw_evidence: Any = None
                try:
                    raw_evidence = self.provider.purchase(
                        node, self.request, context,
                        self.request.maxBudget - self.spent,
                    )
                    evidence = validate_specialist_evidence(raw_evidence, node.type)
                except Exception as exc:
                    evidence = SpecialistEvidence(
                        status="failed",
                        findings={"validationError": str(exc)},
                        actualCost=(raw_evidence.actualCost
                                    if isinstance(raw_evidence, SpecialistEvidence) else None),
                        providerId=(raw_evidence.providerId
                                    if isinstance(raw_evidence, SpecialistEvidence)
                                    else f"replacement-{node.type}"),
                        providerJob=(raw_evidence.providerJob
                                     if isinstance(raw_evidence, SpecialistEvidence) else None),
                    )
                actual_cost = node.estimatedCost if evidence.actualCost is None else evidence.actualCost
                if evidence.providerJob is not None:
                    self.provider_jobs.append(evidence.providerJob)
                if self.spent + actual_cost > self.request.maxBudget:
                    self.graph.transition(node, "failed", "provider cost exceeded remaining budget and was rejected")
                    progress = True
                    continue
                self.spent += actual_cost
                node.actualCost = actual_cost
                self.purchased_roles.append(node.type)
                node.completedAt = utc_now()
                node.outputRefs = [f"evidence:{node.id}"]
                self.outputs[node.id] = dict(evidence.findings)
                if evidence.status == "completed":
                    node.evaluationStatus = "passed"
                    self.graph.transition(node, "completed", "specialist evidence received and accepted")
                    if (evidence.findings.get("objectiveSatisfied") is True
                            and not (self._mandatory_security_required()
                                     and not self._mandatory_security_completed())):
                        self.stopped_early = True
                        self.stop_reason = f"objective satisfied by {node.type} evidence"
                        self._skip_remaining(self.stop_reason)
                        return self._result("completed")
                else:
                    node.evaluationStatus = "failed"
                    self.graph.transition(node, "failed", "specialist execution failed")
                    replacement = self._replacement_for(node, evidence)
                    if replacement is not None:
                        self.graph.replace(node, replacement, "failed specialist was replaced so execution could be replanned")
                progress = True
            unfinished = [node for node in self.graph.active_nodes()
                          if node.status not in TERMINAL_STATUSES]
            if not unfinished:
                break
            if not progress:
                for node in unfinished:
                    self.graph.transition(node, "cancelled", "execution reached an unresolved dependency state")
                break
        completed = any(node.status == "completed" for node in self.graph.active_nodes())
        return self._result("completed" if completed else "failed")

    def _result(self, status: str) -> ExecutionResult:
        return ExecutionResult(
            jobId=self.strategy.jobId,
            status=status,
            spent=self.spent,
            remainingBudget=self.request.maxBudget - self.spent,
            purchasedRoles=list(self.purchased_roles),
            outputs=dict(self.outputs),
            nodes=[asdict(node) for node in self.graph.active_nodes()],
            mutations=[asdict(item) for item in self.graph.mutations],
            stoppedEarly=self.stopped_early,
            stopReason=self.stop_reason,
            providerJobs=[asdict(item) for item in self.provider_jobs],
        )
