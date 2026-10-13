"""Configure dependencies for baseline certificate replay."""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
STRICT_ROOT = HERE.parents[1]
STAGE_DEFAULT = HERE.parents[2]
BENCHMARK = HERE.parents[3]


def apply_mosek(stage_root: Path) -> Path | None:
    lic = Path(stage_root) / "envs" / "mosek.lic"
    if lic.is_file():
        os.environ.setdefault("MOSEKLM_LICENSE_FILE", str(lic))
        return lic
    return None


def apply_ibex(stage_root: Path) -> Path | None:
    lib = Path(stage_root) / "envs" / "fossil-libs"
    if lib.is_dir():
        current = os.environ.get("LD_LIBRARY_PATH", "")
        prefix = str(lib)
        if prefix not in current.split(":"):
            os.environ["LD_LIBRARY_PATH"] = prefix + (":" + current if current else "")
        return lib
    return None


def _insert(path: Path) -> None:
    text = str(path)
    if path.is_dir() and text not in sys.path:
        sys.path.insert(0, text)


def prepare_method_sys_path(method: str, stage_root: Path) -> None:
    stage = Path(stage_root)
    _insert(STRICT_ROOT)
    _insert(stage / "code")
    _insert(STAGE_DEFAULT)
    if method == "fossil":
        _insert(BENCHMARK / "fossil_baseline")
        _insert(stage / "sources" / "fossil_driver")
        _insert(stage / "sources" / "fossil")
        apply_ibex(stage)
    elif method == "synnlf":
        _insert(stage / "sources" / "synnlf")
        apply_mosek(stage)
    elif method == "cbf":
        _insert(stage / "sources" / "cbf_lbp")
        _insert(stage / "code")
    elif method == "analytical_rl":
        _insert(stage / "sources" / "analytical_rl")
        _insert(stage / "sources" / "fossil")
        apply_ibex(stage)
    elif method == "ahmed":
        _insert(stage / "sources" / "ahmed_tacas_py3")
        _insert(stage / "code")


def apply_stage_env(stage_root: Path) -> dict:

    stage = Path(stage_root)
    return {
        "mosek_license": str(apply_mosek(stage) or ""),
        "ibex_lib": str(apply_ibex(stage) or ""),
        "stage_root": str(stage),
    }


def find_dataset(stage_root: Path) -> Path:
    stage = Path(stage_root)
    candidates = [
        HERE.parents[5] / "data" / "dynacertbench_executable.json",
        stage / "data" / "dynacertbench_executable.json",
        stage.parent / "data" / "dynacertbench_executable.json",
        BENCHMARK / "data" / "dynacertbench_executable.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("dynacertbench_executable.json not found")
