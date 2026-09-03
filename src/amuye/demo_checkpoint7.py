from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from .checkpoint import execute_baseline
from .domain import JobRequest
from .sibyl_store import SibylStore


CONTROL_REQUEST = JobRequest(
    objective="Assess whether protocol controlled warrants deeper diligence before integration",
    maxBudget=100,
    deadline="2027-01-15T18:00:00Z",
    priority="balanced",
    hardConstraints=[
        "do not exceed budget",
        "use only supplied protocol evidence",
        "protocolSlug=controlled",
    ],
    clientId="controlled-memory-proof",
)

CONTROL_PROFILE = {
    "name": "Controlled Protocol",
    "category": "DEX",
    "url": "https://example.invalid/controlled",
    "tvl": [{"date": 1, "totalLiquidityUSD": 50_000_000}],
    "chains": ["Base"],
    "audits": "2",
    "audit_links": ["https://example.invalid/audit-1", "https://example.invalid/audit-2"],
    "change_1d": 1.0,
    "change_7d": 2.0,
    "mcap": 75_000_000,
}


def _fresh_process(memory_state: str, memory_db: Path) -> dict:
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1])
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [source_root, environment.get("PYTHONPATH")])
    )
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "amuye.controlled_session",
            "--memory-state",
            memory_state,
            "--memory-db",
            str(memory_db),
            "--request-json",
            json.dumps(asdict(CONTROL_REQUEST), sort_keys=True),
            "--provider-profile-json",
            json.dumps(CONTROL_PROFILE, sort_keys=True),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return json.loads(child.stdout)


def _role_status(run: dict, role: str) -> str:
    return next(node["status"] for node in run["execution"]["finalGraphByRole"]
                if node["role"] == role)


def _validate_control(off: dict, on: dict, lesson_id: str) -> dict:
    if off["request"] != on["request"]:
        raise ValueError("controlled runs did not use the same request")
    if off["environment"] != on["environment"]:
        raise ValueError("controlled runs did not use the same environment")
    if off["memory"]["state"] != "off" or on["memory"]["state"] != "on":
        raise ValueError("memory state labels are invalid")
    if off["memory"]["recalledLessonIds"]:
        raise ValueError("memory-off run recalled an operational lesson")
    if lesson_id not in on["memory"]["recalledLessonIds"]:
        raise ValueError("memory-on run did not recall the prepared lesson")
    if lesson_id not in on["memory"]["strategyMemoryRefs"]:
        raise ValueError("adapted strategy does not reference its lesson")

    off_roles = off["execution"]["executionSequence"]
    on_roles = on["execution"]["executionSequence"]
    only_off = [role for role in off_roles if role not in on_roles]
    only_on = [role for role in on_roles if role not in off_roles]
    if not only_off and not only_on:
        raise ValueError("memory did not change an actual specialist purchase")
    security_initial = next(
        node for node in on["strategy"]["initialGraph"]
        if node["type"] == "security_analysis"
    )
    security_final = next(
        node for node in on["execution"]["finalGraph"]
        if node["id"] == security_initial["id"]
    )
    if lesson_id not in (security_initial["mutationReason"] or ""):
        raise ValueError("changed security action is not traceable to the lesson")
    if security_final["status"] != "skipped":
        raise ValueError("memory-on security node was not skipped")
    if off["execution"]["spent"] > off["request"]["maxBudget"]:
        raise ValueError("memory-off execution exceeded client authority")
    if on["execution"]["spent"] > on["request"]["maxBudget"]:
        raise ValueError("memory-on execution exceeded client authority")

    return {
        "onlyControlledVariable": "Sibyl operational memory availability during planning",
        "sameRequest": True,
        "sameClientConstraints": True,
        "sameEnvironment": True,
        "freshProcessIdsAreDistinct": off["freshProcessId"] != on["freshProcessId"],
        "memoryOffStrategy": off["strategy"]["source"],
        "memoryOnStrategy": on["strategy"]["source"],
        "recalledLessonId": lesson_id,
        "rolesPurchasedOnlyWithMemoryOff": only_off,
        "rolesPurchasedOnlyWithMemoryOn": only_on,
        "memoryOffSecurityStatus": _role_status(off, "security_analysis"),
        "memoryOnSecurityStatus": _role_status(on, "security_analysis"),
        "memoryOffSpend": off["execution"]["spent"],
        "memoryOnSpend": on["execution"]["spent"],
        "spendAvoidedByMemory": off["execution"]["spent"] - on["execution"]["spent"],
        "remainingBudgetIncrease": (
            on["execution"]["remainingBudget"] - off["execution"]["remainingBudget"]
        ),
        "changedAction": {
            "role": "security_analysis",
            "memoryOff": "purchased and completed",
            "memoryOn": "not purchased, skipped after the risk gate",
            "memoryOnNodeId": security_final["id"],
            "memoryOnReason": security_final["mutationReason"],
            "attributedToLessonId": lesson_id,
            "lessonTrace": security_initial["mutationReason"],
        },
        "policyProof": {
            "hardConstraintsIdentical": (
                off["request"]["hardConstraints"] == on["request"]["hardConstraints"]
            ),
            "budgetCeilingIdentical": off["request"]["maxBudget"] == on["request"]["maxBudget"],
            "memoryExpandedAuthority": False,
            "bothRunsWithinBudget": True,
        },
    }


def run(memory_db: Path, output: Path) -> dict:
    memory_db.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    store = SibylStore(memory_db)
    lesson = store.get_lesson("lesson_progressive_specialist_purchasing_v1")
    if lesson is None:
        _, reflection = execute_baseline(CONTROL_REQUEST, store)
        lesson = reflection.proposedLessons[0]

    run_off = _fresh_process("off", memory_db)
    run_on = _fresh_process("on", memory_db)
    comparison = _validate_control(run_off, run_on, lesson.id)
    report = {
        "control": {
            "task": asdict(CONTROL_REQUEST),
            "providerProfile": CONTROL_PROFILE,
            "memoryDatabase": str(memory_db),
            "persistedLessonId": lesson.id,
            "persistedLesson": lesson.to_dict(),
        },
        "runA_memoryOff": run_off,
        "runB_memoryOn": run_on,
        "comparison": comparison,
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Amúyẹ controlled Sibyl comparison")
    parser.add_argument("--memory-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.memory_db, args.output)
    print(json.dumps(report["comparison"], indent=2))


if __name__ == "__main__":
    main()
