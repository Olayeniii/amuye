from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class JobRequest:
    objective: str
    maxBudget: float
    deadline: str
    priority: str
    hardConstraints: list[str]
    clientId: str
    taskClass: str = "protocol_assessment"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "JobRequest":
        required = {
            "objective",
            "maxBudget",
            "deadline",
            "priority",
            "hardConstraints",
            "clientId",
        }
        missing = sorted(required - value.keys())
        if missing:
            raise ValueError(f"missing request fields: {', '.join(missing)}")
        if value.get("taskClass", "protocol_assessment") != "protocol_assessment":
            raise ValueError("Amúyẹ currently accepts protocol_assessment only")
        if float(value["maxBudget"]) <= 0:
            raise ValueError("maxBudget must be greater than zero")
        return cls(
            objective=str(value["objective"]),
            maxBudget=float(value["maxBudget"]),
            deadline=str(value["deadline"]),
            priority=str(value["priority"]),
            hardConstraints=list(value["hardConstraints"]),
            clientId=str(value["clientId"]),
            taskClass="protocol_assessment",
        )


@dataclass
class TaskNode:
    id: str
    jobId: str
    type: str
    description: str
    assignedProvider: str | None
    dependencies: list[str]
    estimatedCost: float
    actualCost: float = 0
    status: str = "proposed"
    conditionalTrigger: str | None = None
    inputRefs: list[str] = field(default_factory=list)
    outputRefs: list[str] = field(default_factory=list)
    evaluationStatus: str = "pending"
    createdAt: str = field(default_factory=utc_now)
    startedAt: str | None = None
    completedAt: str | None = None
    mutationReason: str | None = None


@dataclass
class ProviderJob:
    id: str
    parentJobId: str
    taskNodeId: str
    providerId: str
    providerRole: str
    acpJobId: str
    quotedCost: float
    settledCost: float
    status: str
    submittedAt: str
    completedAt: str | None
    deliverableRef: str | None
    evaluationRef: str | None


@dataclass
class ExecutionStrategy:
    jobId: str
    source: Literal["baseline", "recalled", "adapted"]
    taskPattern: str
    orderedSteps: list[TaskNode]
    branchingRules: list[str]
    budgetPlan: dict[str, float]
    expectedLatency: str
    memoryRefs: list[str]
    rationale: str
    applicabilityAssessment: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LearnedLesson:
    id: str
    taskPattern: str
    strategy: str
    reasoning: str
    applicabilityConditions: list[str]
    nonApplicabilityConditions: list[str]
    supportingExecutionRefs: list[str]
    contradictoryEvidenceRefs: list[str]
    confidence: float
    status: str
    lastUpdatedAt: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReflectionResult:
    jobId: str
    successfulDecisions: list[str]
    failedDecisions: list[str]
    unnecessaryPurchases: list[str]
    missedDependencies: list[str]
    strategyChanges: list[str]
    proposedLessons: list[LearnedLesson]
    evidenceRefs: list[str]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"
