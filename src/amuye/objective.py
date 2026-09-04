from __future__ import annotations

import re

from .domain import JobRequest, ObjectiveIntent


VIABILITY = "viability_onchain"
RISK = "risk_synthesis"
SECURITY = "security_analysis"


class UnsupportedObjectiveError(ValueError):
    def __init__(self, result: ObjectiveIntent) -> None:
        self.result = result
        super().__init__(result.reason)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().replace("-", " ").replace("_", " ")).strip()


def classify_objective(objective: str) -> ObjectiveIntent:
    """Classify only the intents supported by the protocol-assessment MVP."""
    text = _normalized(objective)
    recent_research = bool(
        re.search(r"\b(?:recent|latest)\b.{0,60}\b(?:governance|developments?|proposals?)\b", text)
        or re.search(r"\bgovernance\s+(?:changes|developments?|proposals?)\b", text)
        or re.search(r"\bprotocol\s+developments?\b", text)
    )
    if recent_research:
        return ObjectiveIntent(
            "unsupported", [], ["recent_protocol_governance_research"],
            "Recent protocol/governance research is not supported by the current protocol-assessment MVP.",
        )
    if not text:
        return ObjectiveIntent(
            "unsupported", [], ["missing_assessment_objective"],
            "A concrete protocol-assessment objective is required.",
        )

    if re.search(r"\bsecurity\b", text):
        return ObjectiveIntent(
            "security_assessment", [VIABILITY, RISK, SECURITY], [],
            "The objective explicitly requests protocol security assessment.",
        )

    evidence_terms = ("public protocol evidence", "public evidence", "viability evidence")
    limiting_terms = ("only need", "evidence only", "only public", "viability only")
    if any(term in text for term in evidence_terms) and any(term in text for term in limiting_terms):
        return ObjectiveIntent(
            "evidence_only", [VIABILITY], [],
            "The objective explicitly limits the assessment to public viability evidence.",
        )

    if re.search(r"\brisks?\b", text) or "deeper diligence" in text:
        return ObjectiveIntent(
            "risk_assessment", [VIABILITY, RISK, SECURITY], [],
            "The objective requests integration diligence or material-risk assessment; deeper security work remains a candidate capability subject to execution strategy.",
        )

    if "evidence" in text or re.search(r"\bviab(?:le|ility)\b", text):
        return ObjectiveIntent(
            "evidence_only", [VIABILITY], [],
            "The smallest defensible supported interpretation is public viability evidence.",
        )
    return ObjectiveIntent(
        "unsupported", [], ["ambiguous_protocol_assessment_need"],
        "The objective does not clearly request evidence, risk, or security assessment within the current MVP.",
    )


def mandatory_security_constraint(request: JobRequest) -> bool:
    text = _normalized(" ".join(request.hardConstraints))
    return any(marker in text for marker in (
        "mandatory security", "security analysis is mandatory", "security review is mandatory",
    ))


def resolve_objective_intent(request: JobRequest) -> ObjectiveIntent:
    result = classify_objective(request.objective)
    if result.intent == "unsupported":
        raise UnsupportedObjectiveError(result)
    if not mandatory_security_constraint(request):
        return result
    return ObjectiveIntent(
        "security_assessment", [VIABILITY, RISK, SECURITY], list(result.unsupportedNeeds),
        f"{result.reason} Hard client constraints additionally require security analysis.",
    )
