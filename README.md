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

Amúyẹ learns how to procure specialist agent work from previous executions and applies that experience in later sessions. The core product value is not simple routing.

Removing Sibyl does not prevent a basic protocol assessment. It removes persistent learned procurement behavior. A fresh session can no longer recall prior execution lessons and falls back to the cold baseline plan.

The official `sibyl-memory-client` stores execution journal events and current operational lessons. A separate process can retrieve a lesson, assess its applicability, reference its ID in the plan, and change a real purchase. Amúyẹ does not maintain a second operational-memory database.

### Exact Sibyl paths

- Write execution evidence: `SibylStore.write_execution_history()` in `src/amuye/sibyl_store.py`
- Write or update lessons: `SibylStore.write_lesson()` in `src/amuye/sibyl_store.py`
- Retrieve relevant lessons: `SibylStore.retrieve_lessons()` in `src/amuye/sibyl_store.py`
- Retrieve one current lesson: `SibylStore.get_lesson()` in `src/amuye/sibyl_store.py`
- Fresh-session planning entry: `plan_in_fresh_session()` in `src/amuye/checkpoint.py`
- Lesson mutation flow: `learn_from_execution()` in `src/amuye/learning.py`

`write_execution_history()` returns the real Sibyl journal-event ID. Supporting and contradictory lesson references use those journal IDs while Amúyẹ execution IDs remain in the event metadata.

### Critical Sibyl SDK calls

Judges can verify the full memory boundary in `src/amuye/sibyl_store.py`:

| Operation | Function | Official client call |
| --- | --- | --- |
| Open the Sibyl-managed local store | `SibylStore.__init__()` | `MemoryClient.local(...)` |
| Read lessons before planning | `SibylStore.retrieve_lessons()` | `client.search_entities(...)` |
| Read one current lesson | `SibylStore.get_lesson()` | `client.get_entity(...)` |
| Write execution evidence | `SibylStore.write_execution_history()` | `client.write_event(...)` |
| Write or update a lesson | `SibylStore.write_lesson()` | `client.set_entity(...)` |

`plan_in_fresh_session()` in `src/amuye/checkpoint.py` calls `retrieve_lessons()` and passes those returned records directly into `plan_with_memory()` in `src/amuye/planner.py`. Live runs preserve that planning-time record in the `View Sibyl source` panel before evaluation or reflection can update it.

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

The console exposes Memory OFF and Memory ON as adjacent proof modes. Each shows its distinct fresh-process identifier, graph, purchases, and spend, so both runs can be shown in one continuous recording segment without restarting or editing the video.

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

## Live console and client API

The console has two clearly separated uses. `New Assessment` runs the real Amúyẹ application path. The Memory OFF, Memory ON, mandatory-security, and partner-proof screens render tracked evidence for repeatable judging.

```bash
npm run build
npm run console
```

Open `http://localhost:4173`. In Codespaces, open port `4173` from the Ports panel.

New assessments use local protocol specialists by default and cannot spend ACP funds. Selecting `Live ACP risk purchase` switches only risk synthesis to the registered Virtuals ACP provider. Before submission, the console displays the provider, `riskSynthesis` offering, Base mainnet, and the configured maximum expected USDC spend, then requires explicit confirmation. Viability and security remain local. If viability stops the run, no ACP job is created. A completed ACP job is followed by live Base receipt verification and its settlement links appear in the result.

Set `AMUYE_MEMORY_DB` to choose the Sibyl database. The default is `artifacts/live/sibyl.db`. Live ACP mode also requires the buyer and provider values in `.env.example`; `ACP_RISK_MAX_EXPECTED_SPEND` is the hard maximum passed to the ACP buyer after confirmation.

For a live source demonstration, run the same assessment first with memory disabled, then submit it again with memory enabled. The first execution writes evaluated experience to the Sibyl database. The second reads it during planning. Open `View Sibyl source` on the second result to show the exact planning-time record, database source, process identifier, applicability decision, and rule applied. The footer shows the source commit and console build time throughout the recording.

Another agent or client can submit the same request contract without the frontend:

```bash
curl -X POST 'http://localhost:4173/api/assessments?memory=on' \
  -H 'Content-Type: application/json' \
  -d '{
    "objective": "Assess protocol Aave for integration",
    "maxBudget": 100,
    "deadline": "2026-09-10T18:00:00Z",
    "priority": "balanced",
    "hardConstraints": ["protocolSlug=aave"],
    "clientId": "demo-client",
    "taskClass": "protocol_assessment"
  }'
```

The response is `202 Accepted` with a `jobId` and `statusUrl`:

```json
{
  "jobId": "api_job_...",
  "status": "accepted",
  "statusUrl": "/api/assessments/api_job_...",
  "providerMode": "local specialists, no ACP payment"
}
```

Poll `GET /api/assessments/{jobId}`. It returns current status, ordered execution events, and, once complete, the strategy, graph, purchases, evidence, spend, evaluation, reflection, Sibyl references, and final result. `memory=off` disables operational-memory retrieval for a controlled cold run. It does not change provider behavior or policy enforcement.

Programmatic live ACP submission uses the same request body and requires both explicit query values:

```bash
curl -X POST 'http://localhost:4173/api/assessments?memory=on&provider=live_acp&confirmAcp=true' \
  -H 'Content-Type: application/json' \
  --data @assessment.json
```

Safe provider, network, and maximum-spend confirmation data is available from `GET /api/acp/config`. No signer or wallet credentials are returned. Omitting `confirmAcp=true` rejects a live ACP request before execution. Local mode remains `provider=local` and never invokes the ACP client or settlement verifier.

## Tests

```bash
.venv/bin/pytest
npm run typecheck
npm run build
```

Python tests use deterministic providers and mocked Base RPC responses. CI does not need Virtuals or Base network access.

## Prior Work declaration

Amúyẹ was implemented during this hackathon build window. The repository history begins on September 2, 2026 with the initial Sibyl-backed planning proof, followed by the execution controller, specialist behavior, Virtuals ACP integration, Base settlement verification, controlled memory tests, and judge console. No earlier Amúyẹ application codebase was imported into this repository. Third-party Sibyl, Virtuals ACP, Base, and public protocol-data services are credited dependencies rather than prior Amúyẹ work.

## License and submission

Amúyẹ is released under the OSI-approved [MIT License](LICENSE). The public-post and final-access checks that must be completed manually are listed in [SUBMISSION_CHECKLIST.md](SUBMISSION_CHECKLIST.md). No user, traction, revenue, or testimonial claims are made without public evidence.
