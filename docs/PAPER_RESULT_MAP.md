# Paper results and computation

Run `python scripts/recompute_paper_tables.py` from the release root. The
command writes `results/paper_tables.json` using the records listed below.

| Paper item | Data | Computation |
| --- | --- | --- |
| Table 2(a) | Baseline eligibility and Native/Strict acceptance records | Supported sets and successful systems are deduplicated by record ID |
| Table 2(b), Figure 3 | Three end-to-end run summaries and Full traces | Full, SMT-only, and Lean-only coverage; trace-based One-shot reference and decomposition |
| Table 3 | RQ1 frozen SMT and selected Lean records, with observed Full records | Coverage and mean verification time, split by polynomial class |
| Table 4 | RQ3: 78 repair results on 26 obligations | Completion, mean rounds, and 900-second timeout-charged mean time |
| Table 7 | Main: 105 Full summary rows | Coverage by task; token and time means over successful systems |
| Table 8 | Main: 707 Full call records | Per-role means over returned usage receipts |
| Tables 9-12 | 81 frozen certificates and 296 active obligations | Backend allocation, verification times, and token costs |
| Table 13 | 232 repair-call records | Per-arm call counts and receipt-based token totals |
| Table 14 | 24 unresolved Full traces | Groups defined by the last recorded execution event |
| Tables 15-16 | Grouped curation ledger and final benchmark membership | Candidate-pool totals and final literature-source counts |
| Figure 2 | The 105 descriptive and executable benchmark records | Source groups, task counts, and executable state dimensions |

## Fixed-certificate accounting

The cohort contains the 81 certificates verified by Full. Compatible records
share the certificate ID, candidate hash, obligation manifest, model settings,
and obligation budget. Coverage combines complete certificate successes by ID.
For cost, use the latest complete compatible certificate attempt. The resource ledger sums every recorded attempt. Checks of individual obligations are counted at obligation level.

SMT-first plus Lean combines 30-second SMT outcomes with independent Lean
records. Parallel obligations contribute their maximum interval; sequential
stages contribute their sum. Full time uses the observed final-verification
interval. Verification-time means use successful certificates. Token means
use all 81 selected certificate records.

| Strategy | Verified | Time per verified certificate | Tokens per cohort certificate |
| --- | --- | --- | --- |
| All-SMT | 59/81 | 3.68 s | 0.00k |
| All-Lean | 64/81 | 579.17 s | 24.87k |
| Full | 81/81 | 119.31 s | 8.34k |
| SMT-first plus Lean | 80/81 | 94.28 s | 9.15k |

## Benchmark accounting

The final dataset contains 80 Literature-derived, 11 Extended, and 14 New
instances. The curation ledger records grouped counts by source category and
curation rule. Table 16 attributes final Literature-derived instances to their
individual references. Figure 2 uses the chart's source groups: the
Samanipour/PVTOL group includes the Wu 2023 PVTOL instance. State dimensions
are read from executable dynamics after the stated coordinate reductions.

## Frozen repair inputs

`results/rq3/inputs/` contains 26 first-failure inputs from 19 systems
and 246 payload files. Each fixture includes the problem, candidate, condition,
initial model response, compiler result, and Lean sources for the 78 recorded
strategy results.

```bash
python benchmark/run_frozen_repair.py validate
```

For new model runs, configure the model endpoint, API key, Lean, and solvers as
described in the root README. External baseline execution uses the corresponding
upstream packages, saved candidate models, and applicable licenses.
