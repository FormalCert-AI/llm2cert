"""Export the paper results by experiment and research question."""
import csv
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results"


def write_csv(relative, rows):
    path = OUT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    runpy.run_path(str(ROOT / "scripts/recompute_statistics.py"))
    g = runpy.run_path(str(ROOT / "scripts/recompute_paper_tables.py"))
    tables = g["output"]
    data = json.loads((ROOT / "data/dynacertbench_by_problem.json").read_text())
    tiers = {r["record_id"]: r["tier"] for bucket in data["problems"].values()
             for r in bucket["records"]}

    # Select the latest complete compatible certificate attempt.
    selected = g["selected"]
    full = g["full"]
    smt = g["smt"]
    original = g["original"]
    fixed = []
    for rid in sorted(smt):
        lean = selected[rid]
        fixed.append({
            "record_id": rid,
            "task": g["task"](rid),
            "tier": tiers[rid],
            "certificate_class": g["cert_class"](rid),
            "all_smt_verified": smt[rid]["cutoff_replay"]["900"]["status"] == "verified",
            "all_smt_seconds": smt[rid]["cutoff_replay"]["900"]["duration_seconds"],
            "all_lean_verified": lean["verified"],
            "all_lean_seconds": lean["verification_wall_seconds"],
            "all_lean_tokens": lean["total_tokens"],
            "all_lean_attempts": len(g["attempts"][rid]),
            "selected_run_path": lean["run_path"],
            "selected_attempt_started_at_utc": lean["verification_started_at_utc"],
            "routed_verified": True,
            "routed_seconds": full[rid]["verification_seconds"],
            "smt_first_plus_lean_verified": g["composite"][rid]["verified"],
        })
    assert len(fixed) == 81
    assert sum(r["all_smt_verified"] for r in fixed) == 59
    assert sum(r["all_lean_verified"] for r in fixed) == 64
    write_csv("rq1/certificates.csv", fixed)

    e2e = []
    strategies = {"Full": "full", "SMT-only": "smt_only", "Lean-only": "lean_only"}
    for configuration, strategy in strategies.items():
        merged = g["merge_runs"](strategy)
        for rid in sorted(merged):
            row = merged[rid]
            e2e.append({"configuration": configuration, "record_id": rid,
                        "tier": tiers[rid], "task": row["problem_class"],
                        "status": row["status"], "seconds": row["total_wall_seconds"],
                        "tokens": row["total_tokens"],
                        "model_outputs": f"{strategy}/{rid}.md",
                        "run_path": row["run_path"]})
    assert len(e2e) == 315
    write_csv("main/systems.csv", e2e)
    write_csv("main/summary.csv", [
        {"configuration": name, "systems": 105, "verified": count}
        for name, count in tables["table2_end_to_end"].items()
    ])

    backend = []
    for category in ["polynomial", "non_polynomial"]:
        rows = [r for r in fixed if r["certificate_class"] == category]
        for name, prefix in [("All-SMT", "all_smt"), ("All-Lean", "all_lean"),
                             ("Routed", "routed")]:
            ok = [r for r in rows if r[prefix + "_verified"]]
            backend.append({"certificate_class": category, "strategy": name,
                            "systems": len(rows), "verified": len(ok),
                            "mean_seconds_per_verified":
                                sum(r[prefix + "_seconds"] for r in ok) / len(ok)})
    write_csv("rq1/summary.csv", backend)

    obligations = []
    for rid in sorted(full):
        for condition in full[rid]["conditions"]:
            obligations.append({"record_id": rid, "task": g["task"](rid),
                                "condition_id": condition["condition_id"],
                                "condition_kind": condition["kind"],
                                "verification_path": condition["path"],
                                "model_outputs": f"{rid}.md"})
    assert len(obligations) == 296
    write_csv("rq2/obligations.csv", obligations)
    write_csv("rq2/summary.csv", tables["table9_and_table10"])

    repair = []
    for path in sorted((g["RQ3"] / "records").glob("*/*/*/result.json")):
        row = json.loads(path.read_text())
        repair.append({"fixture_id": row["fixture"]["fixture_id"], "strategy": row["arm"],
                       "outcome": row["outcome"],
                       "repair_rounds": row["metrics"]["repair_turns"],
                       "charged_seconds": row["metrics"]["charged_time_seconds"],
                       "source": path.relative_to(ROOT).as_posix(),
                       "model_outputs": path.parent.relative_to(g["RQ3"] / "records").with_suffix(".md").as_posix()})
    assert len(repair) == 78
    write_csv("rq3/obligations.csv", repair)
    summary = json.loads((OUT / "recomputed_statistics.json").read_text())["rq3"]
    write_csv("rq3/summary.csv", [
        {"strategy": name, **values} for name, values in summary.items()
    ])
    print("Exported Main and RQ1-RQ3 results.")
