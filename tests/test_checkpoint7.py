from __future__ import annotations

import json

import pytest

from amuye.demo_checkpoint7 import run


@pytest.fixture(scope="module")
def controlled_report(tmp_path_factory):
    root = tmp_path_factory.mktemp("memory-control")
    output = root / "comparison.json"
    report = run(root / "sibyl.db", output)
    return report, output


def output_by_role(run_value: dict, role: str) -> dict:
    return next(item for item in run_value["execution"]["result"]["evidence"]
                if item["role"] == role)


def test_same_input_and_environment_memory_off_produces_cold_plan(controlled_report) -> None:
    report, _ = controlled_report
    off = report["runA_memoryOff"]
    on = report["runB_memoryOn"]

    assert off["request"] == on["request"]
    assert off["environment"] == on["environment"]
    assert off["strategy"]["source"] == "baseline"
    assert off["memory"]["recalledLessonIds"] == []
    assert off["execution"]["executionSequence"] == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]


def test_memory_on_fresh_process_retrieves_applicable_sibyl_lesson(controlled_report) -> None:
    report, _ = controlled_report
    on = report["runB_memoryOn"]
    lesson_id = report["control"]["persistedLessonId"]

    assert report["runA_memoryOff"]["freshProcessId"] != on["freshProcessId"]
    assert on["strategy"]["source"] == "adapted"
    assert on["memory"]["recalledLessonIds"] == [lesson_id]
    assert on["memory"]["strategyMemoryRefs"] == [lesson_id]
    assert on["memory"]["applicabilityDecision"].startswith("Applicable:")


def test_memory_changes_actual_purchase_with_identical_shared_evidence(controlled_report) -> None:
    report, _ = controlled_report
    off = report["runA_memoryOff"]
    on = report["runB_memoryOn"]

    assert output_by_role(off, "viability_onchain") == output_by_role(on, "viability_onchain")
    assert output_by_role(off, "risk_synthesis") == output_by_role(on, "risk_synthesis")
    assert on["execution"]["executionSequence"] == ["viability_onchain", "risk_synthesis"]
    assert [job["role"] for job in off["execution"]["providerJobsPurchased"]] == [
        "viability_onchain", "risk_synthesis", "security_analysis",
    ]
    assert [job["role"] for job in on["execution"]["providerJobsPurchased"]] == [
        "viability_onchain", "risk_synthesis",
    ]
    assert off["execution"]["spent"] == 95.0
    assert on["execution"]["spent"] == 35.0


def test_changed_action_is_traceable_to_recalled_lesson(controlled_report) -> None:
    report, _ = controlled_report
    difference = report["comparison"]["changedAction"]
    lesson_id = report["control"]["persistedLessonId"]

    assert difference["role"] == "security_analysis"
    assert difference["attributedToLessonId"] == lesson_id
    assert lesson_id in difference["lessonTrace"]
    assert difference["memoryOnReason"] == "risk evidence did not justify security analysis"


def test_identical_hard_constraints_override_memory_authority(controlled_report) -> None:
    report, _ = controlled_report
    off = report["runA_memoryOff"]
    on = report["runB_memoryOn"]
    policy = report["comparison"]["policyProof"]

    assert off["request"]["hardConstraints"] == on["request"]["hardConstraints"]
    assert policy == {
        "hardConstraintsIdentical": True,
        "budgetCeilingIdentical": True,
        "memoryExpandedAuthority": False,
        "bothRunsWithinBudget": True,
    }
    assert off["execution"]["spent"] <= off["request"]["maxBudget"]
    assert on["execution"]["spent"] <= on["request"]["maxBudget"]


def test_machine_readable_comparison_artifact_is_internally_consistent(controlled_report) -> None:
    report, output = controlled_report
    persisted = json.loads(output.read_text(encoding="utf-8"))
    comparison = persisted["comparison"]

    assert persisted == report
    assert comparison["onlyControlledVariable"] == (
        "Sibyl operational memory availability during planning"
    )
    assert comparison["rolesPurchasedOnlyWithMemoryOff"] == ["security_analysis"]
    assert comparison["rolesPurchasedOnlyWithMemoryOn"] == []
    assert comparison["memoryOffSecurityStatus"] == "completed"
    assert comparison["memoryOnSecurityStatus"] == "skipped"
    assert comparison["spendAvoidedByMemory"] == 60.0
    assert comparison["remainingBudgetIncrease"] == 60.0


def test_controlled_result_is_reproducible(tmp_path) -> None:
    first = run(tmp_path / "first.db", tmp_path / "first.json")
    second = run(tmp_path / "second.db", tmp_path / "second.json")

    for key in ("runA_memoryOff", "runB_memoryOn"):
        assert first[key]["execution"]["executionSequence"] == second[key]["execution"]["executionSequence"]
        assert first[key]["execution"]["spent"] == second[key]["execution"]["spent"]
        assert first[key]["execution"]["remainingBudget"] == second[key]["execution"]["remainingBudget"]
        assert first[key]["execution"]["finalGraphByRole"] == second[key]["execution"]["finalGraphByRole"]
    stable_fields = [
        "rolesPurchasedOnlyWithMemoryOff", "rolesPurchasedOnlyWithMemoryOn",
        "memoryOffSecurityStatus", "memoryOnSecurityStatus",
        "memoryOffSpend", "memoryOnSpend", "spendAvoidedByMemory",
    ]
    assert {key: first["comparison"][key] for key in stable_fields} == {
        key: second["comparison"][key] for key in stable_fields
    }
