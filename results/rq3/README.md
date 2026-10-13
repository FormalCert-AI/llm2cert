# RQ3: Lean proof repair

RQ3 starts the three feedback strategies from the same 26 failed first attempts, drawn from 19 systems. The directory contains all 78 recorded trajectories.

Open a problem directory, then its candidate/obligation directory, to read `generic_retry.md`, `raw_diagnostics.md`, and `structured_repair.md`. Each file contains the frozen first response, subsequent model prompts and responses, generated Lean sources, and compiler results.

- `obligations.csv`: the 78 outcomes, repair rounds, charged time, and transcript paths.
- `summary.csv`: the completion and cost of each strategy.
- `calls.csv`: the 232 saved post-failure model calls.
- `records.tar.gz`: all three strategies' execution records and the shared frozen inputs.

Generic Retry repairs 1/26 obligations, Raw Diagnostics 17/26, and Structured Repair 21/26. Unrepaired obligations are charged the full 900-second budget.

Unpack with `python scripts/unpack_records.py rq3`, then validate the inputs:

```bash
python benchmark/run_frozen_repair.py validate
```

For new model runs, configure the runtime and credentials, then execute:

```bash
python benchmark/run_frozen_repair.py batch --workers 3 --repeats 1 --output-root runs/rq3 --execute
```

See the [running guide](../../docs/RUNNING.md) for setup.
