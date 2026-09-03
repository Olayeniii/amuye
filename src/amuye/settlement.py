from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.request import Request, urlopen

from .domain import SettlementProof, SettlementTransactionProof, TokenMovementProof


CHAIN_ID = 8453
NETWORK = "Base mainnet"
ACP_CONTRACT = "0x238e541bfefd82238730d00a2208e5497f1832e0"
USDC_CONTRACT = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
USDC_DECIMALS = 6
BASESCAN = "https://basescan.org"

GET_JOB_SELECTOR = "0xbf22c457"
PAYMENT_TOKEN_SELECTOR = "0x3013ce29"
PLATFORM_TREASURY_SELECTOR = "0xe138818c"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
JOB_CREATED_TOPIC = "0xb0f0239bfdd96453e24733e18bfc24b70d8fadf123dd977473518dd577ee79b9"
BUDGET_SET_TOPIC = "0x869e2577b006bf47ee981cf6fec2e25583548081c14b98deab587f77b5068038"
JOB_FUNDED_TOPIC = "0xe3fbcc1ea1bdc559ec7f0347efde7655e58b5f45a30b0e4470a583c3ef5496b3"
JOB_SUBMITTED_TOPIC = "0x80c17db79857f338a6a6df68a6883ecc0ce78e2202fe61ed979733573f40538e"
JOB_COMPLETED_TOPIC = "0x0fd54bd364fa9e67f17b091aefe930932c09fe7651cf5ad02c71a418f3341444"
PAYMENT_RELEASED_TOPIC = "0x21d71db5be59bb9fa133895586b7404307dd33fb93b16db09dc6f1d9d7d231b0"
EVALUATOR_FEE_PAID_TOPIC = "0x253dd534010ac976fa263caa123bae79b9c50292adf7ce67bdc5ec309f784e61"


class Rpc(Protocol):
    def call(self, method: str, params: list[Any]) -> Any: ...


@dataclass
class JsonRpc:
    url: str = "https://mainnet.base.org"

    def call(self, method: str, params: list[Any]) -> Any:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        request = Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "amuye-settlement-proof/1"},
        )
        with urlopen(request, timeout=30) as response:
            value = json.load(response)
        if "error" in value:
            raise ValueError(f"Base RPC error: {value['error']}")
        return value["result"]


def _word(value: str, index: int) -> str:
    raw = value.removeprefix("0x")
    start = index * 64
    return raw[start:start + 64]


def _address_word(value: str, index: int) -> str:
    return "0x" + _word(value, index)[-40:].lower()


def _topic_address(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def _amount(value: str) -> int:
    return int(value, 16)


def _usdc(value: int) -> float:
    return value / (10 ** USDC_DECIMALS)


def _tx_proof(event: str, receipt: dict[str, Any]) -> SettlementTransactionProof:
    return SettlementTransactionProof(
        lifecycleEvent=event,
        transactionHash=receipt["transactionHash"],
        blockNumber=int(receipt["blockNumber"], 16),
        receiptStatus=int(receipt["status"], 16),
        outerTransactionFrom=receipt["from"].lower(),
        outerTransactionTo=receipt["to"].lower(),
        explorerUrl=f"{BASESCAN}/tx/{receipt['transactionHash']}",
    )


def _log_proof(event: str, log: dict[str, Any]) -> SettlementTransactionProof:
    return SettlementTransactionProof(
        lifecycleEvent=event,
        transactionHash=log["transactionHash"],
        blockNumber=int(log["blockNumber"], 16),
        receiptStatus=None,
        outerTransactionFrom=None,
        outerTransactionTo=None,
        explorerUrl=f"{BASESCAN}/tx/{log['transactionHash']}",
    )


def _movement(purpose: str, receipt: dict[str, Any], log: dict[str, Any]) -> TokenMovementProof:
    raw_amount = _amount(log["data"])
    return TokenMovementProof(
        purpose=purpose,
        transactionHash=receipt["transactionHash"],
        logIndex=int(log["logIndex"], 16),
        token=log["address"].lower(),
        source=_topic_address(log["topics"][1]),
        destination=_topic_address(log["topics"][2]),
        rawAmount=raw_amount,
        amount=_usdc(raw_amount),
        asset="USDC",
    )


def _lifecycle_logs(rpc: Rpc, job_topic: str, from_block: int,
                    to_block: int | str) -> dict[str, dict[str, Any]]:
    topics = [
        JOB_CREATED_TOPIC, BUDGET_SET_TOPIC, JOB_FUNDED_TOPIC,
        JOB_SUBMITTED_TOPIC, JOB_COMPLETED_TOPIC,
    ]
    logs = rpc.call("eth_getLogs", [{
        "address": ACP_CONTRACT,
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block) if isinstance(to_block, int) else to_block,
        "topics": [topics, job_topic],
    }])
    grouped: dict[str, list[dict[str, Any]]] = {topic: [] for topic in topics}
    for log in logs:
        event_topic = log["topics"][0].lower()
        if event_topic in grouped:
            grouped[event_topic].append(log)
    invalid = {topic: len(values) for topic, values in grouped.items() if len(values) != 1}
    if invalid:
        raise ValueError(f"expected one of each ACP lifecycle log for job: {invalid}")
    return {topic: values[0] for topic, values in grouped.items()}


def _transfers(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    return [log for log in receipt["logs"] if (
        log["address"].lower() == USDC_CONTRACT
        and log["topics"][0].lower() == TRANSFER_TOPIC
    )]


def capture_settlement_proof(job_id: int, rpc: Rpc | None = None,
                             from_block: int = 50_798_000,
                             to_block: int | str = 50_800_000,
                             expected_buyer: str | None = None,
                             expected_provider: str | None = None,
                             expected_budget_raw: int | None = None) -> SettlementProof:
    rpc = rpc or JsonRpc()
    chain_id = int(rpc.call("eth_chainId", []), 16)
    if chain_id != CHAIN_ID:
        raise ValueError(f"expected Base chain ID {CHAIN_ID}, received {chain_id}")

    encoded_job = format(job_id, "064x")
    job_topic = "0x" + encoded_job
    job_data = rpc.call("eth_call", [{
        "to": ACP_CONTRACT,
        "data": GET_JOB_SELECTOR + encoded_job,
    }, "latest"])
    job_offset = int(_word(job_data, 0), 16) // 32
    buyer = _address_word(job_data, job_offset)
    status_code = int(_word(job_data, job_offset + 1), 16)
    provider = _address_word(job_data, job_offset + 2)
    evaluator = _address_word(job_data, job_offset + 4)
    budget_raw = int(_word(job_data, job_offset + 6), 16)
    if status_code != 3:
        raise ValueError(f"ACP job {job_id} is not completed")
    if expected_buyer and buyer != expected_buyer.lower():
        raise ValueError(f"ACP job buyer mismatch: {buyer}")
    if expected_provider and provider != expected_provider.lower():
        raise ValueError(f"ACP job provider mismatch: {provider}")
    if expected_budget_raw is not None and budget_raw != expected_budget_raw:
        raise ValueError(f"ACP job budget mismatch: {budget_raw}")

    payment_token_data = rpc.call("eth_call", [{
        "to": ACP_CONTRACT, "data": PAYMENT_TOKEN_SELECTOR,
    }, "latest"])
    payment_token = _address_word(payment_token_data, 0)
    if payment_token != USDC_CONTRACT:
        raise ValueError(f"ACP payment token is not Base USDC: {payment_token}")
    treasury_data = rpc.call("eth_call", [{
        "to": ACP_CONTRACT, "data": PLATFORM_TREASURY_SELECTOR,
    }, "latest"])
    treasury = _address_word(treasury_data, 0)

    lifecycle_logs = _lifecycle_logs(rpc, job_topic, from_block, to_block)
    created_log = lifecycle_logs[JOB_CREATED_TOPIC]
    budget_log = lifecycle_logs[BUDGET_SET_TOPIC]
    funded_log = lifecycle_logs[JOB_FUNDED_TOPIC]
    submitted_log = lifecycle_logs[JOB_SUBMITTED_TOPIC]
    completed_log = lifecycle_logs[JOB_COMPLETED_TOPIC]
    if _amount(budget_log["data"]) != budget_raw:
        raise ValueError("BudgetSet does not match the stored ACP job budget")
    if _topic_address(created_log["topics"][2]) != buyer:
        raise ValueError("JobCreated buyer does not match getJob")
    if _topic_address(created_log["topics"][3]) != provider:
        raise ValueError("JobCreated provider does not match getJob")
    if _topic_address(funded_log["topics"][2]) != buyer:
        raise ValueError("JobFunded buyer does not match getJob")
    if _topic_address(submitted_log["topics"][2]) != provider:
        raise ValueError("JobSubmitted provider does not match getJob")
    if _topic_address(completed_log["topics"][2]) != evaluator:
        raise ValueError("JobCompleted evaluator does not match getJob")
    funded_receipt = rpc.call("eth_getTransactionReceipt", [funded_log["transactionHash"]])
    completed_receipt = rpc.call("eth_getTransactionReceipt", [completed_log["transactionHash"]])
    if any(int(receipt["status"], 16) != 1 for receipt in [funded_receipt, completed_receipt]):
        raise ValueError("ACP funding or completion receipt failed")

    funded_amount = _amount(funded_log["data"])
    funding_transfers = _transfers(funded_receipt)
    escrow_matches = [log for log in funding_transfers if (
        _topic_address(log["topics"][1]) == buyer
        and _topic_address(log["topics"][2]) == ACP_CONTRACT
        and _amount(log["data"]) == funded_amount
    )]
    if len(escrow_matches) != 1 or funded_amount != budget_raw:
        raise ValueError("funding receipt does not prove the full job budget was escrowed")

    completion_transfers = _transfers(completed_receipt)
    released_logs = [log for log in completed_receipt["logs"] if (
        log["address"].lower() == ACP_CONTRACT
        and log["topics"][0].lower() == PAYMENT_RELEASED_TOPIC
        and log["topics"][1].lower() == job_topic
    )]
    evaluator_logs = [log for log in completed_receipt["logs"] if (
        log["address"].lower() == ACP_CONTRACT
        and log["topics"][0].lower() == EVALUATOR_FEE_PAID_TOPIC
        and log["topics"][1].lower() == job_topic
    )]
    if len(released_logs) != 1 or len(evaluator_logs) != 1:
        raise ValueError("completion receipt lacks ACP payment release accounting")
    if _topic_address(released_logs[0]["topics"][2]) != provider:
        raise ValueError("PaymentReleased provider does not match getJob")
    if _topic_address(evaluator_logs[0]["topics"][2]) != evaluator:
        raise ValueError("EvaluatorFeePaid evaluator does not match getJob")
    provider_raw = _amount(released_logs[0]["data"])
    evaluator_raw = _amount(evaluator_logs[0]["data"])
    token_movements = {
        _topic_address(log["topics"][2]): _amount(log["data"])
        for log in completion_transfers
        if _topic_address(log["topics"][1]) == ACP_CONTRACT
    }
    if token_movements.get(provider) != provider_raw:
        raise ValueError("completion receipt does not prove provider payment")
    if token_movements.get(evaluator) != evaluator_raw:
        raise ValueError("completion receipt does not prove evaluator payment")
    platform_raw = token_movements.get(treasury)
    if platform_raw is None:
        raise ValueError("completion receipt does not prove platform fee payment")
    if provider_raw + evaluator_raw + platform_raw != funded_amount:
        raise ValueError("completion transfers do not account for the escrowed amount")

    provider_transfer = next(log for log in completion_transfers
                             if _topic_address(log["topics"][2]) == provider)
    evaluator_transfer = next(log for log in completion_transfers
                              if _topic_address(log["topics"][2]) == evaluator)
    platform_transfer = next(log for log in completion_transfers
                             if _topic_address(log["topics"][2]) == treasury)

    return SettlementProof(
        chainId=chain_id,
        network=NETWORK,
        acpContract=ACP_CONTRACT,
        usdcContract=USDC_CONTRACT,
        jobId=str(job_id),
        buyer=buyer,
        provider=provider,
        evaluator=evaluator,
        treasury=treasury,
        jobStatus="completed",
        jobStatusCode=status_code,
        jobBudget=_usdc(budget_raw),
        escrowedAmount=_usdc(funded_amount),
        providerReleasedAmount=_usdc(provider_raw),
        evaluatorFeeAmount=_usdc(evaluator_raw),
        platformFeeAmount=_usdc(platform_raw),
        funding=_tx_proof("JobFunded", funded_receipt),
        completion=_tx_proof("EvaluatorFeePaid + PaymentReleased + JobCompleted", completed_receipt),
        lifecycleTransactions=[
            _log_proof("JobCreated", created_log),
            _log_proof("BudgetSet", budget_log),
            _tx_proof("JobFunded", funded_receipt),
            _log_proof("JobSubmitted", submitted_log),
            _tx_proof("EvaluatorFeePaid + PaymentReleased + JobCompleted", completed_receipt),
        ],
        escrowTransfer=_movement("job escrow", funded_receipt, escrow_matches[0]),
        completionTransfers=[
            _movement("provider release", completed_receipt, provider_transfer),
            _movement("evaluator fee", completed_receipt, evaluator_transfer),
            _movement("platform fee", completed_receipt, platform_transfer),
        ],
        contractJobUrl=f"{BASESCAN}/address/{ACP_CONTRACT}#readProxyContract",
    )
