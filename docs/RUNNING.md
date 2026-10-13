# Running LLM2Cert

This release provides the four-task certificate pipeline, the final benchmark, frozen verification and repair inputs, and recorded paper results.
`docs/PAPER_RESULT_MAP.md` maps the data and calculations to each table.

All commands below run from the repository root. Unpack the saved records before any offline calculation or frozen replay:

```bash
python scripts/unpack_records.py
```

## Download and install

Clone the repository and enter its root directory:

```bash
git clone https://github.com/FormalCert-AI/llm2cert.git
cd llm2cert
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e llm2cert/framework
```

The dependencies are listed in `llm2cert/framework/pyproject.toml`.
The Lean project is separate and uses the pinned toolchain in
`llm2cert/formalization/lean/lean-toolchain`. After installing Lean:

```bash
cd llm2cert/formalization/lean
lake update
lake exe cache get
lake build LeanBarrier Audit
cd ../../..
```

Figure 2 and Figure 3 plotting additionally require the `analysis` dependencies:

```bash
python -m pip install -e 'llm2cert/framework[analysis]'
python benchmark/analysis/plot_figure3_end_to_end.py
python benchmark/analysis/plot_figure2.py
```

## Recompute the paper results without an API key

```bash
python scripts/verify_release.py
python scripts/recompute_statistics.py
python scripts/recompute_paper_tables.py
```

These commands read recorded evidence and reproduce the headline counts and
experiment-table metrics without network or model calls. The detailed command
writes `results/paper_tables.json`. To export the results by research question, run `python scripts/export_results.py`. See `docs/PAPER_RESULT_MAP.md` for the source of
each table and the coverage of fresh reproduction.

## Run one case with your own API key

Copy the environment template and set your own provider credentials in the
shell. Do not commit the file or paste the key into source code:

```bash
cp .env.example .env.local
nano .env.local
set -a
source .env.local
set +a
export DYNACERT_RUNTIME_MANIFEST="$PWD/llm2cert/config/runtime.example.json"
```

Put your key only in `.env.local`, which is ignored by Git. `DYNACERT_API_KEY`
is the only required secret; the other variables select the provider, model,
endpoint, router mode, and local runtime manifest. Set `DYNACERT_BASE_URL`
to a service that exposes the recorded `openai/gpt-5.6-sol` model ID; the
example URL is configurable.

Edit `runtime.example.json` if Lean or the SMT solvers are installed
at paths other than `/usr/bin`. The runtime manifest must point to installed
Lean 4.32.2, Z3 4.15.4, cvc5 1.3.3, Yices 2.7.0, and the pinned dReal image
for a paper-matching run.

Run a single case from the public executable dataset:

```bash
PYTHONPATH=llm2cert/framework python llm2cert/run_pipeline.py "$PWD/data/dynacertbench_executable.json" DCB-LIT-P4-025
```

The command writes a new local run artifact. It does not modify the recorded
paper evidence. To run the full dataset after validating one case:

```bash
PYTHONPATH=llm2cert/framework python llm2cert/run_dataset.py --workers 8
```

The same launcher exposes the paper's backend controls:

```bash
PYTHONPATH=llm2cert/framework python llm2cert/run_dataset.py --workers 8 --smt-only
PYTHONPATH=llm2cert/framework python llm2cert/run_dataset.py --workers 8 --lean-only
PYTHONPATH=llm2cert/framework python llm2cert/run_dataset.py --workers 8 --lean-repair-feedback verbatim
```

Use `--record-ids DCB-LIT-P4-025` for a single-record validation run. The environment template sets `DYNACERT_ROUTER=llm` to match the recorded
Full configuration. Use `DYNACERT_ROUTER=fixed` for deterministic routing.

Full model-backed reproduction consumes API credits and may differ from the
recorded run because model responses are stochastic. Use the offline evidence
path when you need the exact paper numbers.

## Fixed-certificate verification

Unpack Main and RQ1 before replaying the 81 frozen certificates:

```bash
python scripts/unpack_records.py main rq1
python benchmark/run_fixed_certificate_all_smt.py --output runs/rq1/all_smt --timeout-seconds 900
python benchmark/run_fixed_certificate_all_lean.py --output runs/rq1/all_lean --budget-seconds 900 --workers 8
```

The SMT runner uses installed solvers. The Lean runner uses the configured model API.

## RQ3 repair reproduction

The bundle contains the original failed proofs, compiler feedback, and initial
model responses for all 26 obligations from 19 systems. Validate it offline:

```bash
python benchmark/run_frozen_repair.py validate
```

After configuring your key and the local Lean runtime, run all three arms:

```bash
python benchmark/run_frozen_repair.py batch --workers 3 --repeats 1 --output-root runs/rq3 --execute
```

Each new repair trajectory starts from its matching frozen first attempt.

## Fixed environment

Lean and Mathlib versions are pinned in `llm2cert/formalization/lean`.
Solver versions are recorded in the experiment metadata and runtime template.
Saved machine paths use portable placeholders.

## External baselines

The baseline adapters and recorded Native/Strict acceptance results are under
`results/main/baselines/`. For fresh baseline execution, install the corresponding
upstream implementations, provide the saved candidate models, and configure
the solver or certification dependencies. See `docs/BASELINE_PROTOCOL.md`.

## License

See `LICENSE` and `THIRD_PARTY_NOTICES.md`.
