"""Recompute coverage from the saved Main and RQ1-RQ3 records."""
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def load(path):
    return json.loads(path.read_text())


main = load(RESULTS / "main/data/full.json")
assert len(main) == 105
full_ok = {r["record_id"] for r in main if r["status"] == "verified"}
assert len(full_ok) == 81
smt = {p.stem: load(p) for p in (RESULTS / "rq1/data/all_smt").glob("*.json")}
selected = {}
records = load(RESULTS / "rq1/data/lean_records.json")
for row in sorted(records, key=lambda r: r["verification_started_at_utc"]):
    selected[row["record_id"]] = row
assert set(selected) == set(smt) == full_ok
assert sum(r["verified"] for r in selected.values()) == 64
composed = set()
for rid, record in smt.items():
    conditions = {c["condition_id"]: c for c in selected[rid]["conditions"] if c["active"]}
    accepted = True
    for cid, outcome in record["cutoff_replay"]["30"]["obligations"].items():
        if outcome["status"] == "verified":
            continue
        condition = conditions[cid]
        formal = condition.get("formal_result") or {}
        lean = condition.get("lean_result") or {}
        if not (formal.get("passed") and formal.get("source") == "lean"
                and (not lean or (lean.get("compiled") and lean.get("audit_passed")))):
            accepted = False
    if accepted:
        composed.add(rid)
assert len(composed) == 80
repair = {}
for path in sorted((RESULTS / "rq3/records").glob("*/*/*/result.json")):
    row = load(path)
    repair.setdefault(row["arm"], []).append(row)
assert {arm: len(rows) for arm, rows in repair.items()} == {
    "failure_only": 26, "verbatim_diagnostics": 26, "current_guided": 26}
result = {
    "main": {"systems": 105, "full_verified": len(full_ok)},
    "fixed_certificates": {
        "systems": 81,
        "all_smt": sum(r["cutoff_replay"]["900"]["status"] == "verified" for r in smt.values()),
        "all_lean": sum(r["verified"] for r in selected.values()),
        "smt_first_plus_lean": len(composed),
        "certificate_attempts": len(records),
    },
    "rq3": {arm: {
        "obligations": len(rows),
        "repaired": sum(r["outcome"] == "verified" for r in rows),
        "mean_rounds": mean(r["metrics"]["repair_turns"] for r in rows),
        "mean_charged_seconds": mean(r["metrics"]["charged_time_seconds"] for r in rows),
    } for arm, rows in repair.items()},
}
(RESULTS / "recomputed_statistics.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
