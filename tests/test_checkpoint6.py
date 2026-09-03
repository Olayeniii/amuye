from __future__ import annotations

import json

import pytest

from amuye.settlement import (
    ACP_CONTRACT,
    BUDGET_SET_TOPIC,
    EVALUATOR_FEE_PAID_TOPIC,
    JOB_COMPLETED_TOPIC,
    JOB_CREATED_TOPIC,
    JOB_FUNDED_TOPIC,
    JOB_SUBMITTED_TOPIC,
    PAYMENT_RELEASED_TOPIC,
    TRANSFER_TOPIC,
    USDC_CONTRACT,
    capture_settlement_proof,
)


BUYER = "0x6d0355d3f32789eed1099020209f5cb4f564761f"
PROVIDER = "0xad72f78ef0ef88aaab8a3c66aacd077396187f0a"
TREASURY = "0x3f833be7447f82e8654bc634981899db0ee8042e"
JOB_TOPIC = "0x" + format(75660, "064x")
TXS = {
    JOB_CREATED_TOPIC: "0x" + "01" * 32,
    BUDGET_SET_TOPIC: "0x" + "02" * 32,
    JOB_FUNDED_TOPIC: "0x" + "03" * 32,
    JOB_SUBMITTED_TOPIC: "0x" + "04" * 32,
    JOB_COMPLETED_TOPIC: "0x" + "05" * 32,
}


def word(value: int) -> str:
    return format(value, "064x")


def address_word(address: str) -> str:
    return address.removeprefix("0x").rjust(64, "0")


def topic_address(address: str) -> str:
    return "0x" + address.removeprefix("0x").rjust(64, "0")


def transfer(source: str, target: str, amount: int) -> dict:
    return {
        "address": USDC_CONTRACT,
        "topics": [TRANSFER_TOPIC, topic_address(source), topic_address(target)],
        "data": "0x" + word(amount),
        "logIndex": "0x1",
    }


class FakeRpc:
    def __init__(self, chain_id: int = 8453, omit_provider_payment: bool = False,
                 failed_receipt_topic: str | None = None) -> None:
        self.chain_id = chain_id
        self.omit_provider_payment = omit_provider_payment
        self.failed_receipt_topic = failed_receipt_topic
        self.calls: list[tuple[str, list]] = []
        self.job_data = "0x" + "".join([word(32),
            address_word(BUYER), word(3), address_word(PROVIDER), word(1_788_390_954),
            address_word(BUYER), address_word("0x" + "00" * 20), word(100_000), word(256),
        ])

    def call(self, method: str, params: list):
        self.calls.append((method, params))
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_call":
            data = params[0]["data"]
            if data.startswith("0xbf22c457"):
                return self.job_data
            if data == "0x3013ce29":
                return "0x" + address_word(USDC_CONTRACT)
            if data == "0xe138818c":
                return "0x" + address_word(TREASURY)
        if method == "eth_getLogs":
            assert params[0]["topics"][0] == list(TXS)
            return [{
                "address": ACP_CONTRACT,
                "topics": [event_topic, JOB_TOPIC] + (
                    [topic_address(BUYER), topic_address(PROVIDER)]
                    if event_topic == JOB_CREATED_TOPIC else
                    [topic_address(BUYER)]
                    if event_topic == JOB_FUNDED_TOPIC else
                    [topic_address(PROVIDER)]
                    if event_topic == JOB_SUBMITTED_TOPIC else
                    [topic_address(BUYER)]
                    if event_topic == JOB_COMPLETED_TOPIC else []
                ),
                "data": "0x" + word(
                    100_000 if event_topic in {BUDGET_SET_TOPIC, JOB_FUNDED_TOPIC} else 0
                ),
                "transactionHash": TXS[event_topic],
                "blockNumber": hex(100 + list(TXS).index(event_topic)),
            } for event_topic in TXS]
        if method == "eth_getTransactionReceipt":
            tx_hash = params[0]
            event_topic = next(topic for topic, value in TXS.items() if value == tx_hash)
            logs: list[dict] = [{
                "address": ACP_CONTRACT,
                "topics": [event_topic, JOB_TOPIC],
                "data": "0x" + word(100_000 if event_topic == JOB_FUNDED_TOPIC else 0),
            }]
            if event_topic == JOB_FUNDED_TOPIC:
                logs.insert(0, transfer(BUYER, ACP_CONTRACT, 100_000))
            if event_topic == JOB_COMPLETED_TOPIC:
                logs = [
                    transfer(ACP_CONTRACT, TREASURY, 5_000),
                    transfer(ACP_CONTRACT, BUYER, 5_000),
                    {
                        "address": ACP_CONTRACT,
                        "topics": [EVALUATOR_FEE_PAID_TOPIC, JOB_TOPIC, topic_address(BUYER)],
                        "data": "0x" + word(5_000),
                    },
                    {
                        "address": ACP_CONTRACT,
                        "topics": [PAYMENT_RELEASED_TOPIC, JOB_TOPIC, topic_address(PROVIDER)],
                        "data": "0x" + word(90_000),
                    },
                    {
                        "address": ACP_CONTRACT,
                        "topics": [JOB_COMPLETED_TOPIC, JOB_TOPIC, topic_address(BUYER)],
                        "data": "0x" + word(0),
                    },
                ]
                if not self.omit_provider_payment:
                    logs.insert(3, transfer(ACP_CONTRACT, PROVIDER, 90_000))
            return {
                "transactionHash": tx_hash,
                "blockNumber": hex(100 + list(TXS.values()).index(tx_hash)),
                "status": "0x0" if event_topic == self.failed_receipt_topic else "0x1",
                "from": "0x" + "aa" * 20,
                "to": "0x" + "bb" * 20,
                "logs": logs,
            }
        raise AssertionError((method, params))


def capture(rpc: FakeRpc):
    return capture_settlement_proof(
        75660,
        rpc,
        expected_buyer=BUYER,
        expected_provider=PROVIDER,
        expected_budget_raw=100_000,
    )


def test_captures_verified_job_budget_escrow_and_provider_release() -> None:
    proof = capture(FakeRpc())

    assert proof.chainId == 8453
    assert proof.jobStatus == "completed"
    assert proof.usdcContract == USDC_CONTRACT
    assert proof.buyer == BUYER
    assert proof.provider == PROVIDER
    assert proof.jobBudget == 0.1
    assert proof.escrowedAmount == 0.1
    assert proof.providerReleasedAmount == 0.09
    assert proof.evaluatorFeeAmount == 0.005
    assert proof.platformFeeAmount == 0.005
    assert proof.funding.transactionHash != proof.completion.transactionHash
    assert proof.funding.receiptStatus == proof.completion.receiptStatus == 1
    assert len({item.transactionHash for item in proof.lifecycleTransactions}) == 5
    assert proof.escrowTransfer.source == BUYER
    assert proof.escrowTransfer.destination == ACP_CONTRACT
    assert [movement.purpose for movement in proof.completionTransfers] == [
        "provider release", "evaluator fee", "platform fee",
    ]


def test_reads_job_and_filters_each_lifecycle_log_by_job_id() -> None:
    rpc = FakeRpc()
    capture(rpc)

    calls = [params for method, params in rpc.calls if method == "eth_getLogs"]
    assert len(calls) == 1
    assert all(params[0]["address"] == ACP_CONTRACT for params in calls)
    assert all(params[0]["topics"][1] == JOB_TOPIC for params in calls)
    job_calls = [params for method, params in rpc.calls if method == "eth_call"]
    assert any(params[0]["data"].startswith("0xbf22c457") for params in job_calls)


def test_rejects_wrong_chain_or_expected_identity() -> None:
    with pytest.raises(ValueError, match="expected Base chain ID"):
        capture(FakeRpc(chain_id=1))
    with pytest.raises(ValueError, match="buyer mismatch"):
        capture_settlement_proof(75660, FakeRpc(), expected_buyer="0x" + "11" * 20)


def test_completed_status_without_provider_token_movement_is_not_settlement() -> None:
    with pytest.raises(ValueError, match="does not prove provider payment"):
        capture(FakeRpc(omit_provider_payment=True))


def test_failed_funding_or_completion_receipt_is_rejected() -> None:
    with pytest.raises(ValueError, match="funding or completion receipt failed"):
        capture(FakeRpc(failed_receipt_topic=JOB_FUNDED_TOPIC))


def test_proof_record_is_json_serializable() -> None:
    value = json.loads(json.dumps(capture(FakeRpc()).to_dict()))
    assert value["funding"]["explorerUrl"].endswith(TXS[JOB_FUNDED_TOPIC])
    assert value["completion"]["explorerUrl"].endswith(TXS[JOB_COMPLETED_TOPIC])
