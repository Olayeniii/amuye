# Amúyẹ

Give Amúyẹ a job, budget, and deadline. It commissions specialist agents as needed, learns from every execution, and applies that experience to the next one.

This repository currently implements Checkpoints 1 through 4:

`task -> baseline execution -> reflection -> Sibyl write -> fresh session -> Sibyl retrieval -> changed plan`

Checkpoint 2 executes that plan through a mutable protocol-assessment graph. It enforces dependencies and budget, evaluates evidence gates before deeper purchases, skips unjustified work, replaces failed nodes, records every mutation reason, and stops when the objective is satisfied.

Checkpoint 3 supplies real role behavior. Viability reads public DefiLlama protocol data, risk synthesis consumes the viability result, and security analysis consumes both prior outputs. Every completed output is validated before the graph accepts it.

Checkpoint 4 keeps viability and security local, but purchases gated risk synthesis through the official Virtuals ACP Node v2 client flow. Base-specific work beyond ACP settlement and the frontend remain deferred.

## Run the proof

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m amuye.demo --memory-db artifacts/checkpoint1/sibyl.db --output artifacts/checkpoint1/report.json
```

Run a live protocol assessment:

```bash
.venv/bin/python -m amuye.demo_checkpoint3 --protocol aave --memory-db artifacts/checkpoint3/sibyl.db --output artifacts/checkpoint3/aave.json
```

Run the live ACP path after registering a Amúyẹ buyer and a risk provider in the Virtuals Service Registry, funding the buyer wallet, installing Node dependencies, and exporting the values in `.env.example`:

Register the provider offering with the exact name in `ACP_RISK_OFFERING_NAME`, a fixed USDC price no greater than Amúyẹ's risk-node authority, and the requirement schema in `src/acp/risk-offering-requirements.json`. The buyer and provider must use different registered wallets.

```bash
npm install
set -a; . ./.env; set +a
npm run acp:risk-seller # keep this running in terminal 1
.venv/bin/python -m amuye.demo_checkpoint4 --protocol aave --memory-db artifacts/checkpoint4/sibyl.db --output artifacts/checkpoint4/aave-acp.json
```

The ACP lifecycle is `createJobFromOffering -> budget.set -> fund -> job.submitted -> self-evaluation -> complete`. The provider request contains the full accepted viability output under `acceptedViabilityEvidence`. Amúyẹ rejects an offering price or quote above remaining budget before settlement.

The command starts a child Python process for the second plan. That process receives only the serialized request and the Sibyl database path. It does not receive the first plan, execution, reflection, or lesson.

Run tests:

```bash
.venv/bin/pytest
```

## Checkpoint 1 code paths

- Sibyl read and write: `src/amuye/sibyl_store.py`
- Baseline and memory-aware planning: `src/amuye/planner.py`
- Baseline execution and reflection: `src/amuye/checkpoint.py`
- Fresh-process test: `src/amuye/demo.py`
- Mutable graph and progressive controller: `src/amuye/execution.py`
- Real protocol specialists and public data adapter: `src/amuye/specialists.py`
- ACP risk adapter and ProviderJob mapping: `src/amuye/acp.py`
- Official ACP Node v2 buyer lifecycle: `src/acp/risk-buyer.ts`

## Memory is load-bearing

Without the operational lesson retrieved from Sibyl, Amúyẹ returns the baseline plan and commissions all three roles immediately. With the lesson, it changes the graph to progressive purchasing: viability runs first, risk is gated by viability evidence, and security is gated by risk evidence. Removing the Sibyl database removes that learned behavior.
