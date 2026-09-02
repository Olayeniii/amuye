from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote
from urllib.request import Request, urlopen

from .domain import JobRequest, TaskNode
from .execution import SpecialistEvidence


class ProtocolDataSource(Protocol):
    def get_protocol(self, slug: str) -> dict[str, Any]: ...


class DefiLlamaProtocolDataSource:
    """Public, unauthenticated protocol data from api.llama.fi."""

    base_url = "https://api.llama.fi/protocol"

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds

    def get_protocol(self, slug: str) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}/{quote(slug, safe='')}",
            headers={"Accept": "application/json", "User-Agent": "amuye/0.1"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise ValueError("DefiLlama returned a non-object protocol record")
        return payload


@dataclass
class StaticProtocolDataSource:
    protocols: dict[str, dict[str, Any]]

    def get_protocol(self, slug: str) -> dict[str, Any]:
        if slug not in self.protocols:
            raise KeyError(f"protocol data not found for {slug}")
        return dict(self.protocols[slug])


def protocol_slug(request: JobRequest) -> str:
    for constraint in request.hardConstraints:
        match = re.fullmatch(r"protocolSlug\s*=\s*([a-zA-Z0-9_-]+)", constraint.strip())
        if match:
            return match.group(1).lower()
    match = re.search(r"protocol\s+([a-zA-Z0-9_-]+)", request.objective, re.IGNORECASE)
    if match and match.group(1).lower() not in {"assessment", "a"}:
        return match.group(1).lower()
    raise ValueError("protocol assessment requires hard constraint protocolSlug=<slug>")


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _current_tvl(profile: dict[str, Any]) -> float:
    direct = profile.get("tvl")
    if isinstance(direct, (int, float)) and not isinstance(direct, bool):
        return float(direct)
    if isinstance(direct, list) and direct:
        latest = direct[-1]
        if isinstance(latest, dict):
            return _number(latest.get("totalLiquidityUSD"))
    chain_tvls = profile.get("currentChainTvls", {})
    if isinstance(chain_tvls, dict):
        return sum(
            _number(value) for chain, value in chain_tvls.items()
            if not any(marker in chain.lower() for marker in ("borrowed", "staking", "pool2", "doublecounted"))
        )
    return 0.0


def _deployment_chains(profile: dict[str, Any]) -> list[str]:
    listed = profile.get("chains")
    if isinstance(listed, list) and listed:
        return sorted({str(chain) for chain in listed})
    chain_tvls = profile.get("currentChainTvls")
    if not isinstance(chain_tvls, dict):
        return []
    chains: set[str] = set()
    for raw_chain, value in chain_tvls.items():
        if _number(value) <= 0:
            continue
        lowered = raw_chain.lower()
        if lowered in {"borrowed", "staking", "pool2", "doublecounted"}:
            continue
        base_chain = re.sub(r"-(borrowed|staking|pool2|doublecounted)$", "", raw_chain,
                            flags=re.IGNORECASE)
        chains.add(base_chain)
    return sorted(chains)


class ViabilityOnchainSpecialist:
    role = "viability_onchain"

    def __init__(self, data_source: ProtocolDataSource) -> None:
        self.data_source = data_source

    def assess(self, request: JobRequest) -> dict[str, Any]:
        slug = protocol_slug(request)
        profile = self.data_source.get_protocol(slug)
        tvl = _current_tvl(profile)
        chains = _deployment_chains(profile)
        audits = str(profile.get("audits") or "0")
        audit_links = profile.get("audit_links") if isinstance(profile.get("audit_links"), list) else []
        active = tvl >= 1_000_000 and bool(chains)
        if active:
            gate_reason = f"{profile.get('name', slug)} has measurable activity and deployment evidence, so risk synthesis is justified."
        else:
            gate_reason = f"Available public data shows insufficient activity for deeper paid assessment of {profile.get('name', slug)}."
        return {
            "role": self.role,
            "objectiveSatisfied": not active,
            "continueToRisk": active,
            "gateReason": gate_reason,
            "protocol": {
                "slug": slug,
                "name": str(profile.get("name") or slug),
                "category": str(profile.get("category") or "unknown"),
                "url": str(profile.get("url") or ""),
            },
            "metrics": {
                "currentTvlUsd": tvl,
                "chains": [str(chain) for chain in chains],
                "chainCount": len(chains),
                "change1dPct": _number(profile.get("change_1d")),
                "change7dPct": _number(profile.get("change_7d")),
                "auditCount": int(audits) if audits.isdigit() else 0,
                "auditLinks": [str(link) for link in audit_links],
                "marketCapUsd": _number(profile.get("mcap")),
            },
            "evidence": [
                {"source": "defillama", "field": "currentTvlUsd", "value": tvl},
                {"source": "defillama", "field": "chains", "value": chains},
                {"source": "defillama", "field": "audits", "value": audits},
            ],
        }


class RiskSynthesisSpecialist:
    role = "risk_synthesis"

    def assess(self, request: JobRequest,
               context: dict[str, dict[str, Any]]) -> dict[str, Any]:
        viability = context.get("viability_onchain")
        if not viability:
            raise ValueError("risk synthesis requires viability evidence")
        metrics = viability["metrics"]
        protocol = viability["protocol"]
        risks: list[dict[str, Any]] = []
        if metrics["auditCount"] == 0:
            risks.append({"id": "missing-audit-evidence", "severity": "high", "reason": "No public audit record was supplied by the protocol data source."})
        if metrics["change7dPct"] <= -20:
            risks.append({"id": "rapid-tvl-decline", "severity": "high", "reason": f"Seven-day TVL change is {metrics['change7dPct']}%."})
        if metrics["chainCount"] >= 4:
            risks.append({"id": "multi-chain-surface", "severity": "medium", "reason": f"Deployment spans {metrics['chainCount']} chains."})
        if protocol["category"].lower() in {"bridge", "bridges", "lending", "derivatives"}:
            risks.append({"id": "category-exposure", "severity": "medium", "reason": f"{protocol['category']} protocols have material smart-contract and economic risk."})
        high = sum(risk["severity"] == "high" for risk in risks)
        medium = sum(risk["severity"] == "medium" for risk in risks)
        continue_to_security = high > 0 or medium >= 2
        gate_reason = "Security analysis is justified by material risk signals." if continue_to_security else "No material combination of public risk signals justified security analysis."
        return {
            "role": self.role,
            "objectiveSatisfied": False,
            "continueToSecurity": continue_to_security,
            "gateReason": gate_reason,
            "identifiedRisks": risks,
            "evidence": [
                {"source": "viability_onchain", "field": "metrics", "value": metrics},
                {"source": "viability_onchain", "field": "protocol", "value": protocol},
            ],
            "consumedEvidenceRefs": ["viability_onchain"],
        }


class SecurityAnalysisSpecialist:
    role = "security_analysis"

    def assess(self, request: JobRequest,
               context: dict[str, dict[str, Any]]) -> dict[str, Any]:
        viability = context.get("viability_onchain")
        risk = context.get("risk_synthesis")
        if not viability or not risk:
            raise ValueError("security analysis requires viability and risk evidence")
        metrics = viability["metrics"]
        findings: list[dict[str, Any]] = []
        if metrics["auditCount"] == 0:
            findings.append({"check": "audit-coverage", "status": "unverified", "severity": "high", "detail": "The selected public data source supplied no audit evidence; independent verification is required."})
        else:
            findings.append({"check": "audit-coverage", "status": "reported", "severity": "info", "detail": f"Protocol data reports {metrics['auditCount']} audit record(s)."})
        if metrics["chainCount"] >= 4:
            findings.append({"check": "deployment-surface", "status": "review-required", "severity": "medium", "detail": f"Review deployment and bridge assumptions across {metrics['chainCount']} chains."})
        for identified in risk["identifiedRisks"]:
            findings.append({"check": f"risk:{identified['id']}", "status": "review-required", "severity": identified["severity"], "detail": identified["reason"]})
        assessment = "review_required" if any(item["severity"] in {"high", "medium"} for item in findings) else "no_material_public_signal"
        return {
            "role": self.role,
            "objectiveSatisfied": True,
            "assessment": assessment,
            "findings": findings,
            "evidence": [
                {"source": "viability_onchain", "field": "auditLinks", "value": metrics["auditLinks"]},
                {"source": "risk_synthesis", "field": "identifiedRisks", "value": risk["identifiedRisks"]},
            ],
            "consumedEvidenceRefs": ["viability_onchain", "risk_synthesis"],
        }


class ProtocolAssessmentProvider:
    """Runtime provider for the three frozen protocol-assessment roles."""

    def __init__(self, data_source: ProtocolDataSource | None = None) -> None:
        source = data_source or DefiLlamaProtocolDataSource()
        self.viability = ViabilityOnchainSpecialist(source)
        self.risk = RiskSynthesisSpecialist()
        self.security = SecurityAnalysisSpecialist()
        self.calls: list[str] = []
        self.contexts: list[dict[str, dict[str, Any]]] = []

    def purchase(self, node: TaskNode, request: JobRequest,
                 context: dict[str, dict[str, Any]],
                 remaining_budget: float) -> SpecialistEvidence:
        self.calls.append(node.type)
        self.contexts.append(context)
        if node.type == "viability_onchain":
            output = self.viability.assess(request)
        elif node.type == "risk_synthesis":
            output = self.risk.assess(request, context)
        elif node.type == "security_analysis":
            output = self.security.assess(request, context)
        else:
            raise ValueError(f"unsupported specialist role {node.type}")
        return SpecialistEvidence(
            status="completed",
            findings=output,
            providerId=f"local-{node.type}",
        )
