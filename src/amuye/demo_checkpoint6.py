from __future__ import annotations

import argparse
import json
from pathlib import Path

from .settlement import JsonRpc, capture_settlement_proof


def run(job_id: int, output: Path, rpc_url: str) -> dict:
    proof = capture_settlement_proof(
        job_id,
        JsonRpc(rpc_url),
        expected_buyer="0x6d0355d3f32789eed1099020209f5cb4f564761f",
        expected_provider="0xad72f78ef0ef88aaab8a3c66aacd077396187f0a",
        expected_budget_raw=100_000,
    )
    report = {
        "settlementProof": proof.to_dict(),
        "statement": (
            "The job budget and escrow were 0.1 USDC. The completion transaction "
            "released 0.09 USDC to the provider and split the remaining 0.01 USDC "
            "between evaluator and platform fees."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture proof for an existing Amúyẹ ACP settlement")
    parser.add_argument("--job-id", type=int, default=75660)
    parser.add_argument("--rpc-url", default="https://mainnet.base.org")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.job_id, args.output, args.rpc_url), indent=2))


if __name__ == "__main__":
    main()
