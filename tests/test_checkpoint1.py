from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict

from tadbir.checkpoint import execute_baseline
from tadbir.demo import DEMO_REQUEST
from tadbir.sibyl_store import SibylStore


def test_checkpoint_one_survives_fresh_process_and_changes_plan(tmp_path):
    memory_db = tmp_path / "sibyl.db"
    execution, reflection = execute_baseline(DEMO_REQUEST, SibylStore(memory_db))

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, ["src", env.get("PYTHONPATH")]))
    child = subprocess.run(
        [sys.executable, "-m", "tadbir.fresh_session", "--memory-db", str(memory_db),
         "--request-json", json.dumps(asdict(DEMO_REQUEST))],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    result = json.loads(child.stdout)
    baseline = execution["strategy"]
    changed = result["strategy"]

    assert reflection.proposedLessons[0].id in changed["memoryRefs"]
    assert changed["source"] == "adapted"
    assert baseline["budgetPlan"]["planned"] == 95.0
    assert changed["budgetPlan"]["initialCommitment"] == 10.0
    assert all(not node["dependencies"] for node in baseline["orderedSteps"])
    assert changed["orderedSteps"][1]["dependencies"] == [changed["orderedSteps"][0]["id"]]
    assert changed["orderedSteps"][2]["dependencies"] == [changed["orderedSteps"][1]["id"]]
    assert changed["orderedSteps"][1]["conditionalTrigger"]
    assert changed["orderedSteps"][2]["conditionalTrigger"]


def test_no_memory_returns_baseline(tmp_path):
    request_json = json.dumps(asdict(DEMO_REQUEST))
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, ["src", env.get("PYTHONPATH")]))
    child = subprocess.run(
        [sys.executable, "-m", "tadbir.fresh_session", "--memory-db", str(tmp_path / "empty.db"),
         "--request-json", request_json],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert json.loads(child.stdout)["strategy"]["source"] == "baseline"

