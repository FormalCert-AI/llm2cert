# RQ1: SMT and Lean verification

RQ1 compares the verification backends on the same 81 certificates and 296 active obligations. The candidates come from the successful Full runs.

- `all_lean/`: saved proof-agent prompts and responses for each problem, including every recorded certificate attempt.
- `certificates.csv`: one row per frozen certificate, with coverage, time, tokens, and the selected All-Lean run.
- `summary.csv`: polynomial and non-polynomial coverage and mean verification time.
- `calls.csv`: every saved All-Lean model call.
- `records.tar.gz`: All-SMT outcomes, All-Lean attempts, execution metadata, and obligation checks.

All-SMT verifies 59/81 certificates and All-Lean verifies 64/81. The reported All-Lean cost uses the latest complete compatible certificate attempt, checked against the frozen candidate, obligation set, model settings, and 900-second budget. It does not select the fastest attempt. Checks of individual obligations remain obligation-level evidence and do not add complete-certificate successes.

Unpack with `python scripts/unpack_records.py rq1`. To replay the frozen certificates, also unpack Main and use `benchmark/run_fixed_certificate_all_smt.py` or `benchmark/run_fixed_certificate_all_lean.py`. See the [running guide](../../docs/RUNNING.md).
