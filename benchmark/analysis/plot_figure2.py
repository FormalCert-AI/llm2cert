"""Plot benchmark source, task, and dimension counts."""
import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from figure2_record_accounting import load_records, source_group

OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(exist_ok=True)
ROOT = Path(__file__).resolve().parents[2]
records, accounting = load_records()
tiers = ["literature", "extended", "ours"]
colors = ["#3568A8", "#E69F00", "#009E73"]
assert len(records) == 105
assert Counter(r["tier"] for r in records) == {"literature": 80, "extended": 11, "ours": 14}

source_order = ["BarrierBench", "FOSSIL papers", "New / Ours", "Other literature", "Zou et al.", "Jun Liu et al.", "Samanipour/PVTOL", "Wu et al.", "Zhou et al.", "Jiang Liu et al."]
sources = Counter(source_group(r) for r in records)
tasks = {tier: [sum(r["tier"] == tier and r["problem"] == p for r in records) for p in range(1, 5)] for tier in tiers}
dims = {tier: [sum(r["tier"] == tier and r["figure2_dimension"] == d for r in records) for d in range(1, 11)] for tier in tiers}
assert sum(sources.values()) == 105
assert all(sum(dims[tier]) == sum(r["tier"] == tier for r in records) for tier in tiers)
(OUT / "figure2_metrics.json").write_text(json.dumps({"source_groups_full_cohort": dict(sources), "task_counts": tasks, "dimension_counts_n1_to_n10": dims, "accounting": accounting}, indent=2) + "\n")

plt.rcParams.update({"font.family": "serif", "font.serif": ["DejaVu Serif"], "mathtext.fontset": "stix", "font.size": 8.5, "axes.titlesize": 9.2, "axes.labelsize": 8.2, "xtick.labelsize": 7.2, "ytick.labelsize": 8.0, "pdf.fonttype": 42, "ps.fonttype": 42, "axes.linewidth": 0.45})
fig, axes = plt.subplots(1, 3, figsize=(8.4, 2.9), gridspec_kw={"width_ratios": [1.35, 1.25, 1.3]})
fig.subplots_adjust(left=0.148, right=0.992, top=0.86, bottom=0.31, wspace=0.69)
a, b, c = axes
def style(ax):
    ax.set_axisbelow(True)
    ax.grid(axis="x" if ax is not c else "y", color="#E3E8EE", linewidth=0.45)
    for edge in ["top", "right"]:
        ax.spines[edge].set_visible(False)
    ax.spines["left"].set_color("#AAB5C2")
    ax.spines["bottom"].set_color("#AAB5C2")
    ax.tick_params(width=0.4, length=2)
for ax in axes:
    style(ax)
y = np.arange(len(source_order))
v = [sources[s] for s in source_order]
a.barh(y, v, color=[colors[2] if s == "New / Ours" else colors[0] for s in source_order], height=0.64)
a.set_yticks(y, source_order)
a.tick_params(axis="y", length=0, pad=3)
a.invert_yaxis()
a.set_xlim(0, 40)
a.set_xticks([0, 20, 40])
a.set_xlabel("Systems")
for yi, value in zip(y, v):
    a.text(value + 0.6, yi, str(value), va="center", fontsize=7.4)
a.set_title("(a) Source groups", fontweight="bold", pad=8)

left = np.zeros(4)
for tier, color in zip(tiers, colors):
    values = np.array(tasks[tier])
    b.barh(np.arange(4), values, left=left, color=color, height=0.48)
    for i, (value, offset) in enumerate(zip(values, left)):
        if value:
            if value >= 4:
                b.text(offset + value / 2, i, str(value), ha="center", va="center", color="white" if color != colors[1] else "black", fontsize=7.4)
            else:
                b.annotate(str(value), xy=(offset + value / 2, i), xytext=(offset + value / 2 + 1.1, i - 0.3 if tier == "extended" else i + 0.29), fontsize=7.0, va="center", arrowprops={"arrowstyle": "-", "lw": 0.3, "color": "#666666"})
    left += values
b.set_yticks(np.arange(4), ["P1 Stability", "P2 ROA", "P3 Invariance", "P4 Safety"])
b.tick_params(axis="y", length=0, pad=3)
b.invert_yaxis()
b.set_xlim(0, 60)
b.set_xticks([0, 30, 60])
b.set_xlabel("Systems")
b.set_title("(b) Verification task", fontweight="bold", pad=8)

bottom = np.zeros(10)
for tier, color in zip(tiers, colors):
    values = np.array(dims[tier])
    c.bar(np.arange(1, 11), values, bottom=bottom, color=color, width=0.77)
    for d, (value, offset) in enumerate(zip(values, bottom), 1):
        if value >= 3:
            c.text(d, offset + value / 2, str(value), ha="center", va="center", color="white" if color != colors[1] else "black", fontsize=7.0)
    bottom += values
c.set_xlim(0.4, 10.6)
c.set_ylim(0, 41)
c.set_xticks(range(1, 11))
c.set_ylabel("Systems", labelpad=2)
c.set_title("(c) State dimensions", fontweight="bold", pad=8)
table = c.table(cellText=[[str(v) if v else "-" for v in dims[t]] for t in tiers], rowLabels=["L", "E", "N"], cellLoc="center", rowLoc="center", bbox=[0.0, -0.39, 1.0, 0.31])
table.auto_set_font_size(False)
table.set_fontsize(6.7)
for (row, col), cell in table.get_celld().items():
    cell.set_linewidth(0.25)
    cell.set_edgecolor("#D6DFE9")
    if col == -1:
        cell.set_facecolor(colors[row])
        cell.get_text().set_color("white" if row != 1 else "black")
    else:
        cell.set_facecolor("#F6F8FA")
c.set_xlabel("State dimension", labelpad=40)
handles = [plt.Rectangle((0, 0), 1, 1, color=color) for color in colors]
fig.legend(handles, ["Literature-derived", "Extended", "New"], loc="lower center", bbox_to_anchor=(0.55, 0.01), ncol=3, frameon=False, handlelength=1.1, columnspacing=1.5, fontsize=8.2)
figures = OUT
figures.mkdir(exist_ok=True)
fig.savefig(figures / "dataset.pdf", bbox_inches="tight", pad_inches=0.035)
fig.savefig(figures / "dataset.png", dpi=240, bbox_inches="tight", pad_inches=0.035)
print(json.dumps({"sources": dict(sources), "tiers": dict(Counter(r["tier"] for r in records)), "dimensions": dims}, indent=2))
