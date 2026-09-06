from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def built_payload() -> dict:
    subprocess.run(["node", "frontend/build.mjs"], cwd=ROOT, check=True,
                   capture_output=True, text=True)
    return json.loads((ROOT / "dist" / "demo-data.json").read_text(encoding="utf-8"))


def test_console_build_contains_three_required_demo_modes() -> None:
    payload = built_payload()
    expected_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    assert payload["buildEvidence"]["commitHash"] == expected_commit
    assert payload["buildEvidence"]["builtAt"].endswith("Z")
    modes = {mode["key"]: mode for mode in payload["modes"]}
    assert set(modes) == {"memory-off", "memory-on", "mandatory-security"}
    assert modes["memory-off"]["execution"]["spent"] == 95.0
    assert modes["memory-on"]["execution"]["spent"] == 35.0
    assert modes["memory-off"]["memory"]["freshProcessId"]
    assert modes["memory-on"]["memory"]["freshProcessId"]
    assert (modes["memory-off"]["memory"]["freshProcessId"]
            != modes["memory-on"]["memory"]["freshProcessId"])
    assert [item["role"] for item in modes["memory-on"]["execution"]["purchased"]] == [
        "viability_onchain", "risk_synthesis",
    ]
    assert next(node for node in modes["memory-on"]["graph"]
                if node["role"] == "security_analysis")["status"] == "skipped"


def test_memory_consequence_is_derived_from_controlled_execution_evidence() -> None:
    payload = built_payload()
    consequence = payload["memoryConsequence"]
    modes = {mode["key"]: mode for mode in payload["modes"]}
    off = modes["memory-off"]
    on = modes["memory-on"]
    security = next(node for node in on["graph"]
                    if node["role"] == "security_analysis")
    risk = next(item for item in on["evidence"]
                if item["role"] == "risk_synthesis")

    assert consequence["withoutExperience"]["specialistsCommissioned"] == len(
        off["execution"]["purchased"])
    assert consequence["withExperience"]["specialistsCommissioned"] == len(
        on["execution"]["purchased"])
    assert consequence["withoutExperience"]["spend"] == off["execution"]["spent"]
    assert consequence["withExperience"]["spend"] == on["execution"]["spent"]
    assert consequence["preservedBudget"] == (
        off["execution"]["spent"] - on["execution"]["spent"])
    assert consequence["avoidedSpecialistCount"] == 1
    assert consequence["withExperience"]["securityStatus"] == security["status"]
    assert consequence["withExperience"]["securitySkipReason"] == security["reason"]
    assert consequence["withExperience"]["securityGate"] == security["gate"]
    assert consequence["withExperience"]["riskContinueToSecurity"] == risk["continueToSecurity"]


def test_memory_consequence_traces_lesson_and_distinct_fresh_processes() -> None:
    consequence = built_payload()["memoryConsequence"]
    off = consequence["withoutExperience"]
    on = consequence["withExperience"]

    assert off["freshProcessId"] != on["freshProcessId"]
    assert off["memoryReadPerformed"] is False
    assert on["memoryReadPerformed"] is True
    assert on["recalledLessonCount"] == 1
    assert on["recalledLessonId"] in on["planningMemoryRefs"]


def test_console_presents_memory_consequence_before_source_proof() -> None:
    source = (ROOT / "frontend" / "src" / "app.js").read_text(encoding="utf-8")
    assert "No prior execution experience" in source
    assert "Experience recalled from Sibyl" in source
    assert "Skipped unnecessary security purchase" in source
    assert "budget units preserved" in source
    assert "Fresh process. Prior conversation unavailable." in source
    assert source.index("memoryConsequencePanel(mode)") < source.index(
        "memorySourcePanel(mode.memory)")


def test_changed_constraint_mode_surfaces_partial_adaptation() -> None:
    mode = next(item for item in built_payload()["modes"]
                if item["key"] == "mandatory-security")
    risk = next(item for item in mode["evidence"] if item["role"] == "risk_synthesis")
    security = next(item for item in mode["graph"] if item["role"] == "security_analysis")
    assert mode["memory"]["adapted"] is True
    assert mode["memory"]["applicability"].startswith("Partially applicable:")
    assert risk["continueToSecurity"] is False
    assert security["status"] == "completed"
    assert "hard client constraint" in mode["memory"]["adaptationReason"]


def test_console_partner_proof_matches_verified_base_artifact() -> None:
    proof = built_payload()["partnerProof"]
    assert proof["jobId"] == "75660"
    assert proof["offering"] == "riskSynthesis"
    assert proof["network"] == "Base mainnet"
    assert proof["chainId"] == 8453
    assert (proof["escrow"], proof["providerRelease"], proof["evaluatorFee"],
            proof["platformFee"]) == (0.1, 0.09, 0.005, 0.005)
    assert proof["funding"]["receiptStatus"] == 1
    assert proof["completion"]["receiptStatus"] == 1
    assert proof["funding"]["explorerUrl"].startswith("https://basescan.org/tx/")
    assert proof["completion"]["explorerUrl"].startswith("https://basescan.org/tx/")


def test_user_facing_console_has_no_stale_name_or_build_phase_language() -> None:
    files = [
        ROOT / "frontend" / "index.html",
        ROOT / "frontend" / "src" / "app.js",
        ROOT / "frontend" / "src" / "styles.css",
        ROOT / "dist" / "demo-data.json",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "Tadbir" not in text
    assert "tadbir" not in text.lower()
    assert "checkpoint" not in text.lower()
    assert "Amúyẹ" in text
