# Strict replay

This directory contains the baseline adapters used for the
paper's Strict baseline accounting. The Strict harness applies the common
certificate acceptance policy to each method's saved candidate artifacts,
including the native translated certificate and method-specific replay rules.

The included adapters are:

- `fossil_method/` for FOSSIL;
- `ahmed/` for the Ahmed et al. baseline;
- `analytical_rl/` for Analytical-RL;
- `synnlf/` and `cbf_lbp/` for the corresponding native baselines;
- `_common/` for shared inventory, environment, schema, and I/O helpers.

The saved Strict evidence is under the sibling `strict_results/` directory.
See `../../../docs/BASELINE_PROTOCOL.md` for the acceptance rules.
Operational server launchers, upstream repositories, licenses, SSH settings,
and machine-specific paths are intentionally omitted. A fresh baseline run
requires the corresponding upstream software and licenses.

The adapters therefore do not run from this repository alone. `--stage-root`
must point to a stage that provides `accepted_certificate_inventory.json`,
`fossil_native_unified_recount.json`, the upstream method sources under
`sources/` (`fossil`, `fossil_driver`, `synnlf`, `cbf_lbp`, `analytical_rl`,
`ahmed_tacas_py3`), and, for SynNLF, `envs/mosek.lic`. Without such a stage,
use the adapters to inspect the Strict acceptance rules and the saved results
in `strict_results/`.
