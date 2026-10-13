# Recorded experiments

The saved runs are organized as they appear in the paper:

- [Main](main): end-to-end synthesis, backend ablations, and baseline comparisons.
- [RQ1](rq1): SMT and Lean verification of the same 81 frozen certificates.
- [RQ2](rq2): routing decisions, obligation outcomes, and verification costs.
- [RQ3](rq3): three feedback strategies on 26 frozen failed proofs.

Open a problem's Markdown file to read the saved prompts and model responses. `calls.csv` lists every saved call and links it to the corresponding problem. RQ3 also includes each repair step's Lean source and compiler result. Empty responses and errors are shown as recorded.

Each experiment's `records.tar.gz` contains its JSON records, proofs, and execution metadata. Unpack all four from the repository root:

```bash
python scripts/unpack_records.py
```

To unpack one experiment, append its name, for example `python scripts/unpack_records.py rq3`.

The exported text replaces machine-specific paths with placeholders. Model response text is preserved.

Recompute the CSV results with `python scripts/export_results.py`. Regenerate the readable outputs with `python scripts/export_model_outputs.py`. Neither command calls a model. [Paper result definitions](../docs/PAPER_RESULT_MAP.md) explain the cohort and time accounting.
