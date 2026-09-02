from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from .checkpoint import execute_baseline, plan_in_fresh_session
from .demo import DEMO_REQUEST
from .execution import ExecutionController
from .sibyl_store import SibylStore
from .specialists import ProtocolAssessmentProvider


def run(protocol: str, memory_db: Path, output: Path) -> dict:
    request = replace(
        DEMO_REQUEST,
        objective=f"Assess whether protocol {protocol} warrants deeper diligence before integration",
        hardConstraints=["do not exceed budget", f"protocolSlug={protocol}"],
        clientId="checkpoint3-live-demo",
    )
    memory_db.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    store = SibylStore(memory_db)
    execute_baseline(request, store)
    strategy, lessons = plan_in_fresh_session(request, SibylStore(memory_db))
    provider = ProtocolAssessmentProvider()
    result = ExecutionController(request, strategy, provider).run()
    report = {
        "request": asdict(request),
        "strategy": strategy.to_dict(),
        "recalledLessonIds": [lesson.id for lesson in lessons],
        "providerCalls": provider.calls,
        "execution": asdict(result),
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Amúyẹ Checkpoint 3 against public protocol data")
    parser.add_argument("--protocol", required=True, help="DefiLlama protocol slug, for example aave")
    parser.add_argument("--memory-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.protocol, args.memory_db, args.output)
    print(json.dumps({
        "providerCalls": report["providerCalls"],
        "spent": report["execution"]["spent"],
        "remainingBudget": report["execution"]["remainingBudget"],
        "nodeStates": [(node["type"], node["status"]) for node in report["execution"]["nodes"]],
    }, indent=2))


if __name__ == "__main__":
    main()
