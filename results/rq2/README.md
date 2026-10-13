# RQ2: Routing and verification cost

RQ2 analyzes the 81 frozen certificates and 296 obligations from Full. It uses the observed routed runs and a comparison that composes 30-second SMT results with independent Lean records.

- Each `DCB-*.md` file contains the saved router and proof-agent calls for that problem's final candidate.
- `obligations.csv`: all 296 obligations, their verification paths, and links to model outputs.
- `summary.csv`: task-wise coverage, backend allocation, and verification time.
- `calls.csv`: the saved model calls used by these routed verification paths.
- `records.tar.gz`: the frozen candidates, routing decisions, solver results, Lean sources, and compilation records.

Observed Full verifies 81/81 certificates. SMT-first plus Lean verifies 80/81; it is a composition of saved backend results, not a separate end-to-end run. Mean verification time uses verified certificates. Token means use the common 81-certificate cohort.

Unpack with `python scripts/unpack_records.py rq2`. Run `python scripts/export_results.py` after unpacking all four experiments to recompute the comparison and its accounting.
