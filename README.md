# Tadbir

Give Tadbir a job, budget, and deadline. It commissions specialist agents as needed, learns from every execution, and applies that experience to the next one.

This repository currently implements Checkpoint 1 only:

`task -> baseline execution -> reflection -> Sibyl write -> fresh session -> Sibyl retrieval -> changed plan`

Virtuals ACP, Base, specialist integrations, mutable execution graphs, and the frontend are intentionally deferred.

## Run the proof

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m tadbir.demo --memory-db artifacts/checkpoint1/sibyl.db --output artifacts/checkpoint1/report.json
```

The command starts a child Python process for the second plan. That process receives only the serialized request and the Sibyl database path. It does not receive the first plan, execution, reflection, or lesson.

Run tests:

```bash
.venv/bin/pytest
```

## Checkpoint 1 code paths

- Sibyl read and write: `src/tadbir/sibyl_store.py`
- Baseline and memory-aware planning: `src/tadbir/planner.py`
- Baseline execution and reflection: `src/tadbir/checkpoint.py`
- Fresh-process test: `src/tadbir/demo.py`

## Memory is load-bearing

Without the operational lesson retrieved from Sibyl, Tadbir returns the baseline plan and commissions all three roles immediately. With the lesson, it changes the graph to progressive purchasing: viability runs first, risk is gated by viability evidence, and security is gated by risk evidence. Removing the Sibyl database removes that learned behavior.

