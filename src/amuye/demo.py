from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from .checkpoint import execute_baseline
from .domain import JobRequest
from .sibyl_store import SibylStore


DEMO_REQUEST = JobRequest(
    objective="Assess whether Protocol A warrants deeper diligence before integration",
    maxBudget=100,
    deadline="2026-09-03T18:00:00Z",
    priority="balanced",
    hardConstraints=["do not exceed budget", "use only supplied protocol evidence"],
    clientId="demo-client",
)


def run(memory_db: Path, output: Path) -> dict:
    memory_db.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    execution, reflection = execute_baseline(DEMO_REQUEST, SibylStore(memory_db))
    child = subprocess.run(
        [sys.executable, "-m", "amuye.fresh_session", "--memory-db", str(memory_db),
         "--request-json", json.dumps(asdict(DEMO_REQUEST))],
        check=True,
        capture_output=True,
        text=True,
    )
    recalled = json.loads(child.stdout)
    baseline = execution["strategy"]
    changed = recalled["strategy"]
    report = {
        "request": asdict(DEMO_REQUEST),
        "baselineExecution": execution,
        "reflection": reflection.to_dict(),
        "sibylWrite": {
            "database": str(memory_db.resolve()),
            "executionRef": execution["executionId"],
            "lessonIds": [lesson.id for lesson in reflection.proposedLessons],
        },
        "freshSession": {
            "mechanism": "separate Python process with only request JSON and Sibyl database path",
            **recalled,
        },
        "materialChanges": {
            "source": [baseline["source"], changed["source"]],
            "initialSpecialistCommitment": [baseline["budgetPlan"]["planned"], changed["budgetPlan"]["initialCommitment"]],
            "dependenciesBefore": [node["dependencies"] for node in baseline["orderedSteps"]],
            "dependenciesAfter": [node["dependencies"] for node in changed["orderedSteps"]],
            "conditionalTriggersBefore": [node["conditionalTrigger"] for node in baseline["orderedSteps"]],
            "conditionalTriggersAfter": [node["conditionalTrigger"] for node in changed["orderedSteps"]],
            "memoryRefs": changed["memoryRefs"],
        },
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Amúyẹ Checkpoint 1")
    parser.add_argument("--memory-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.memory_db, args.output)
    print(json.dumps(report["materialChanges"], indent=2))


if __name__ == "__main__":
    main()

