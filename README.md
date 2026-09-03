# Amúyẹ

Give Amúyẹ a job, budget, and deadline. It commissions specialist agents as needed, learns from execution, and applies that experience to later work.

Amúyẹ handles one task class: protocol assessment. It can commission viability and onchain analysis, risk synthesis, and security analysis.

The main product behavior is progressive purchasing. Amúyẹ gathers cheap, useful evidence first, then buys deeper work only when accepted evidence and client constraints support it. Budget and hard-constraint enforcement remain outside memory reasoning.

## Architecture

1. Intake validates the request, budget, deadline, and hard constraints.
2. Sibyl retrieval finds structurally relevant operational lessons.
3. Planning creates either a cold baseline or a memory-informed graph.
4. The execution controller enforces dependencies, gates, budget, early stopping, replacement, and mutation reasons.
5. Role-specific validation checks specialist outputs.
6. Evaluation and reflection run before any operational lesson mutation.
7. Execution history and lessons are persisted through Sibyl.

Viability and security use the local specialist runtime. Risk synthesis can use either the deterministic adapter or a real Virtuals ACP provider purchase.

## Why Sibyl is load-bearing

The core product value is not simple routing. Amúyẹ learns how specialist work should be purchased, ordered, checked, and stopped.

The official `sibyl-memory-client` stores execution journal events and current operational lessons. A separate process can retrieve a lesson, assess its applicability, reference its ID in the plan, and change a real purchase. Amúyẹ does not maintain a second operational-memory database.

### Exact Sibyl paths

- Write execution evidence: `SibylStore.write_execution_history()` in `src/amuye/sibyl_store.py`
- Write or update lessons: `SibylStore.write_lesson()` in `src/amuye/sibyl_store.py`
- Retrieve relevant lessons: `SibylStore.retrieve_lessons()` in `src/amuye/sibyl_store.py`
- Retrieve one current lesson: `SibylStore.get_lesson()` in `src/amuye/sibyl_store.py`
- Fresh-session planning entry: `plan_in_fresh_session()` in `src/amuye/checkpoint.py`
- Lesson mutation flow: `learn_from_execution()` in `src/amuye/learning.py`

`write_execution_history()` returns the real Sibyl journal-event ID. Supporting and contradictory lesson references use those journal IDs while Amúyẹ execution IDs remain in the event metadata.

## Fresh-session and controlled memory proof

The fresh-session proof runs planning in a new process with no conversation history. Sibyl returns `lesson_progressive_specialist_purchasing_v1`, and the planner changes the graph from unconditional purchases to:

```text
viability -> viability gate -> risk synthesis -> risk gate -> security analysis
```

The controlled comparison uses the same request, provider profile, prices, controller, evidence, and runtime:

| Run | Memory | Specialists purchased | Spend |
| --- | --- | --- | ---: |
| A | OFF | viability, risk, security | 95 |
| B | ON | viability, risk | 35 |

Risk evidence returns `continueToSecurity: false`. Run B skips the security purchase and traces that action to the recalled Sibyl lesson ID.

```bash
.venv/bin/python -m amuye.demo_memory_control \
  --memory-db artifacts/memory-control/sibyl.db \
  --output artifacts/memory-control/comparison.json
```

## Changed-constraint adaptation

A related request makes security analysis mandatory. Amúyẹ still retrieves the progressive lesson and keeps viability-first ordering plus the viability-to-risk gate. It identifies the conflict with the normal security gate and overrides only that rule for the current job.

Security runs even when risk returns `continueToSecurity: false`. The hard constraint is enforced by the planner and execution controller. The stored lesson is unchanged, and a later ordinary task can still use its original security gate.

```bash
.venv/bin/python -m amuye.demo_constraint_adaptation \
  --memory-db artifacts/constraint-adaptation/sibyl.db \
  --output artifacts/constraint-adaptation/result.json
```

## Virtuals ACP integration

Amúyẹ is the ACP buyer. A separately registered provider exposes the `riskSynthesis` offering through Virtuals ACP. When viability permits continuation, the buyer sends the accepted viability output as `acceptedViabilityEvidence`.

The lifecycle is:

```text
createJobFromOffering -> budget.set -> fund -> submit -> self-evaluation -> complete
```

The deliverable is converted into the same validated risk specialist contract used by the local controller. Failures, malformed deliverables, rejection, and timeouts follow the provider failure and replacement path. ACP costs count against the client budget.

Set the registered provider and buyer values using `.env.example`. Keep the provider running in one terminal:

```bash
set -a
source .env
set +a
npm run acp:risk-seller
```

Run the buyer from a second terminal:

```bash
set -a
source .env
set +a
.venv/bin/python -m amuye.demo_acp \
  --protocol aave \
  --memory-db artifacts/acp/sibyl.db \
  --output artifacts/acp/aave.json
```

## Base settlement proof

Virtuals ACP job `75660` completed on Base mainnet. Verified accounting:

- 0.1 USDC moved from the buyer into ACP escrow.
- 0.09 USDC was released to the risk provider.
- 0.005 USDC was paid to the evaluator.
- 0.005 USDC was paid to the platform treasury.

Funding and completion were separate successful Base transactions:

- [Funding transaction on BaseScan](https://basescan.org/tx/0xe28f073db856502b6c18446d687db7eac361085c859082905614f728dd6b8348)
- [Completion and release transaction on BaseScan](https://basescan.org/tx/0xec26b0a878c1cf3c5836861b6a659882ae0cace33aeeb69d8a559701882ce369)
- [ACP contract on BaseScan](https://basescan.org/address/0x238e541bfefd82238730d00a2208e5497f1832e0#readProxyContract)

The settlement record separates job budget, escrowed funds, provider release, evaluator fee, and platform fee. Verify it again without creating a transaction:

```bash
.venv/bin/python -m amuye.demo_settlement \
  --job-id 75660 \
  --output artifacts/base/job-75660-settlement.json
```

## Setup and local assessment

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm install
```

```bash
.venv/bin/python -m amuye.demo_assessment \
  --protocol aave \
  --memory-db artifacts/live/sibyl.db \
  --output artifacts/live/aave.json
```

## Judge console

The console reads tracked proof artifacts during its build. It has separate screens for memory OFF, memory ON, mandatory-security adaptation, and verified ACP/Base settlement.

```bash
npm run build
npm run console
```

Open `http://localhost:4173`. In Codespaces, open port `4173` from the Ports panel.

## Tests

```bash
.venv/bin/pytest
npm run typecheck
npm run build
```

Python tests use deterministic providers and mocked Base RPC responses. CI does not need Virtuals or Base network access.
