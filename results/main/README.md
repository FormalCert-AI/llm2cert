# Main experiment

This directory contains the 105-system end-to-end experiment and the comparisons in Table 2 and Figure 3.

- `full/`, `smt_only/`, and `lean_only/`: saved model prompts and responses, one Markdown file per problem ID. Each file contains all recorded attempts for that configuration.
- `systems.csv`: the selected result for each problem and configuration, with paths to its model outputs and execution records.
- `summary.csv`: the Full, SMT-only, Lean-only, and One-shot coverage counts.
- `calls.csv`: individual model calls, including calls with no returned response.
- `baselines/`: supported benchmark sets, Native/Strict acceptance records, and certification adapters.
- `records.tar.gz`: the original execution records with portable paths, grouped by configuration and problem ID.

Full verifies 81/105 systems, SMT-only 57/105, and Lean-only 60/105. The One-shot reference is reconstructed from the 63 successful Full runs that required no feedback; it is not an independent model run.

Unpack this experiment with `python scripts/unpack_records.py main` from the repository root. To generate new runs, use `llm2cert/run_dataset.py`; the command and runtime setup are in the [running guide](../../docs/RUNNING.md).
