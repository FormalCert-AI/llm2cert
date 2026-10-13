#!/usr/bin/env python3
"""Plot end-to-end experiment results."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT.parent / "results/main/data"
ELIG = ROOT.parent / "results/main/baselines/eligibility.json"
OUT = Path(__file__).resolve().parent / "figures"

FULL = "full"
SMT = ["smt_only"]
LEAN = ["lean_only"]


NATIVE = {
    "DCB-LIT-P4-003",
    "DCB-LIT-P4-008",
    "DCB-LIT-P4-026",
    "DCB-LIT-P4-037",
    "DCB-LIT-P4-038",
    "DCB-LIT-P4-040",
    "DCB-LIT-P4-041",
    "DCB-LIT-P4-045",
    "DCB-LIT-P3-002",
    "DCB-LIT-P4-005",
    "DCB-LIT-P4-009",
    "DCB-LIT-P1-015",
    "DCB-LIT-P1-002",
    "DCB-LIT-P1-006",
    "DCB-LIT-P1-007",
    "DCB-LIT-P1-008",
    "DCB-LIT-P1-009",
    "DCB-LIT-P1-013",
    "DCB-LIT-P1-016",
}

NAVY = "#1F4E79"
SLATE = "#8FA0AE"
ORANGE = "#E09A3E"
GRAY = "#C8CDD3"
TEAL = "#5BA8A8"
GREEN = "#6FA86F"
SHOT = "#D5D8DC"
SMT_GREEN = "#2E8B57"
GRID = "#E6E8EB"


def _load(path: Path):
    return json.loads(path.read_text())


def _rows(names: list[str]) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for name in names:
        data = _load(EXP / (name + ".json"))
        for row in data:
            merged[row["record_id"]] = row
    return merged


def _union50() -> set[str]:
    elig = _load(ELIG)["methods"]
    ids: set[str] = set()
    for key in ("fossil_generic", "cbf", "analytical_rl", "synnlf"):
        ids.update(elig[key]["eligible_ids"])
    return ids


def panel_a_counts() -> dict[str, int]:
    union = _union50()
    verified = {
        row["record_id"]
        for row in _rows([FULL]).values()
        if row["status"] == "verified"
    }
    ours = union & verified
    both = ours & NATIVE
    baseline_only = (union & NATIVE) - verified
    ours_only = ours - NATIVE
    neither = union - ours - baseline_only
    counts = {
        "ours_only": len(ours_only),
        "both": len(both),
        "baseline_only": len(baseline_only),
        "neither": len(neither),
    }
    if sum(counts.values()) != 51:
        raise SystemExit(f"panel (a) does not sum to 51: {counts}")
    if not NATIVE <= union:
        raise SystemExit(f"native ids outside the 50-union: {sorted(NATIVE - union)}")
    return counts


def _waterfall_bucket(row: dict) -> str:
    trace = _load(EXP / "traces.json")
    return next(r["waterfall_bucket"] for r in trace if r["record_id"] == row["record_id"])


def panel_c_counts(full_rows: dict[str, dict]) -> dict[str, int]:
    counts = {"one_shot": 0, "smt_sat": 0, "lean_repair": 0, "new_candidate": 0}
    for row in full_rows.values():
        if row["status"] != "verified":
            continue
        counts[_waterfall_bucket(row)] += 1
    if sum(counts.values()) != sum(row["status"] == "verified" for row in full_rows.values()):
        raise SystemExit(f"panel (c) does not match verified count: {counts}")
    return counts


def verified_walls(rows: dict[str, dict]) -> list[float]:
    return sorted(
        float(row["total_wall_seconds"])
        for row in rows.values()
        if row["status"] == "verified"
    )


def _style(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#B7BCC2")
    ax.spines["bottom"].set_color("#B7BCC2")
    ax.tick_params(colors="#4A4F55", width=0.6, length=3)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def main() -> None:
    full_rows = _rows([FULL])
    smt_rows = _rows(SMT)
    lean_rows = _rows(LEAN)
    if len(full_rows) != 105 or len(smt_rows) != 105 or len(lean_rows) != 105:
        raise SystemExit(
            f"expected 105 rows, got full={len(full_rows)} smt={len(smt_rows)} lean={len(lean_rows)}"
        )
    part_a = panel_a_counts()
    part_c = panel_c_counts(full_rows)
    print("panel a", part_a)
    print("panel c", part_c)

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 7.2,
            "ytick.labelsize": 7.5,
            "legend.fontsize": 7.2,
            "axes.linewidth": 0.6,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.facecolor": "white",
        }
    )
    fig, axes = plt.subplots(1, 3, figsize=(10.4, 3.15))
    fig.subplots_adjust(left=0.055, right=0.985, top=0.86, bottom=0.22, wspace=0.32)


    ax = axes[0]
    labels = ["LLM2Cert\nonly", "Both", "Baseline\nonly", "Neither"]
    values = [
        part_a["ours_only"],
        part_a["both"],
        part_a["baseline_only"],
        part_a["neither"],
    ]
    colors = [NAVY, SLATE, ORANGE, GRAY]
    bars = ax.bar(range(4), values, color=colors, width=0.72, zorder=3)
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.6,
            str(value),
            ha="center",
            va="bottom",
            fontsize=8,
            color="#24303A",
            fontweight="medium",
        )
    ax.set_xticks(range(4), labels)
    ax.set_ylim(0, 40)
    ax.set_yticks([0, 10, 20, 30, 40])
    ax.set_ylabel("Verified systems")
    ax.set_title("(a) Baseline comparison", loc="center", fontweight="bold", pad=8)
    _style(ax)


    ax = axes[1]
    series = [
        ("Full", verified_walls(full_rows), NAVY, "-"),
        ("SMT-only", verified_walls(smt_rows), SMT_GREEN, "--"),
        ("Lean-only", verified_walls(lean_rows), ORANGE, "--"),
    ]
    label_shift = {"Full": 3.2, "SMT-only": -3.4, "Lean-only": 3.2}
    for name, walls, color, linestyle in series:
        xs = [0.0, *walls, 2400.0]
        ys = [0, *range(1, len(walls) + 1), len(walls)]
        ax.plot(xs, ys, color=color, linestyle=linestyle, linewidth=1.6, label=name, zorder=3)
        ax.text(
            2320,
            len(walls) + label_shift[name],
            str(len(walls)),
            va="center",
            ha="left",
            color=color,
            fontsize=7.5,
            fontweight="bold",
            clip_on=False,
        )
    ax.set_xlim(0, 2400)
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Time per system (s)")
    ax.set_ylabel("Verified systems")
    ax.set_title("(b) Verification over time", loc="center", fontweight="bold", pad=8)
    ax.legend(frameon=False, loc="upper left")
    _style(ax)


    ax = axes[2]
    one_shot = part_c["one_shot"]
    sat = part_c["smt_sat"]
    lean = part_c["lean_repair"]
    new = part_c["new_candidate"]
    full = one_shot + sat + lean + new
    stages = [
        ("One-shot", one_shot, 0, SHOT, str(one_shot)),
        ("SMT\nfeedback", sat, one_shot, TEAL, f"+{sat}"),
        ("Lean\nrepair", lean, one_shot + sat, NAVY, f"+{lean}"),
        ("New\ncandidate", new, one_shot + sat + lean, GREEN, f"+{new}"),
        ("Full", full, 0, NAVY, str(full)),
    ]
    for index, (_, height, start, color, label) in enumerate(stages):
        ax.bar(index, height, bottom=start, color=color, width=0.72, zorder=3)
        ax.text(
            index,
            start + height + 1.4,
            label,
            ha="center",
            va="bottom",
            fontsize=8,
            color="#24303A",
            fontweight="medium",
        )
    ax.set_xticks(range(5), [item[0] for item in stages])
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("Verified systems")
    ax.set_title("(c) LLM2Cert Full", loc="center", fontweight="bold", pad=8)
    _style(ax)

    OUT.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"end_to_end.{ext}", dpi=300)
    print("wrote", OUT / "end_to_end.pdf")


if __name__ == "__main__":
    main()
