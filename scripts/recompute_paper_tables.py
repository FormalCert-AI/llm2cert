#!/usr/bin/env python3
"""Recompute the final paper's experiment tables from archived evidence."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark/analysis"))
from figure2_record_accounting import load_records, source_group

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "results/main"
RQ1 = ROOT / "results/rq1"
RQ3 = ROOT / "results/rq3"

def load(path):
    return json.loads(path.read_text())

trace = {"full_trace": load(MAIN / "data/traces.json")}
supp = load(MAIN / "data/model_usage.json")
supp["rq3_calls"] = load(RQ3 / "data/model_usage.json")
full_summary = load(MAIN / "data/full.json")
original = {r["record_id"]: r for r in load(RQ1 / "data/initial_records.json")}
full = {r["record_id"]: r for r in trace["full_trace"] if r["status"] == "verified"}
smt = {p.stem: load(p) for p in sorted((RQ1 / "data/all_smt").glob("*.json"))}
assert len(full) == len(original) == len(smt) == 81
assert set(full) == set(original) == set(smt)
configurations = load(RQ1 / "data/configurations.json")
reference = configurations[0]
ref_strategy = {k: v for k, v in reference["strategy"].items() if k != "fixed_certificate_workers"}
for conf in configurations[1:]:
    assert conf["source_rq1_lean_configuration"] == reference["source_rq1_lean_configuration"]
    assert conf["timeouts"] == reference["timeouts"]
    assert {k: v for k, v in conf["strategy"].items() if k != "fixed_certificate_workers"} == ref_strategy
    assert conf["model"] == "openai/gpt-5.6-sol"
records = load(RQ1 / "data/lean_records.json")
assert len(records) == 106
recorded_starts = {r["verification_started_at_utc"] for r in original.values()}
later_records = [r for r in records if r["verification_started_at_utc"] not in recorded_starts]
for r in later_records:
    rid = r["record_id"]
    assert r["candidate_hash"] == smt[rid]["audit"]["candidate_hash"]
    assert r["budget_seconds"] == 900
    assert {c["condition_id"] for c in r["conditions"] if c["active"]} == set(smt[rid]["cutoff_replay"]["900"]["obligations"])
    if r["verified"]:
        assert all((c.get("formal_result") or {}).get("passed") and (c.get("lean_result") or {}).get("compiled") and (c.get("lean_result") or {}).get("audit_passed") for c in r["conditions"] if c["active"])
assert len(later_records) == 25

selected = dict(original)
for r in sorted(later_records, key=lambda r: r["verification_started_at_utc"]):
    selected[r["record_id"]] = r
attempts = defaultdict(list)
for r in records:
    attempts[r["record_id"]].append(r)
complete_successes = {rid for rid, rows in attempts.items() if any(r["verified"] for r in rows)}
assert complete_successes == {rid for rid, r in selected.items() if r["verified"]}
assert len(complete_successes) == 64

obligation_checks = load(RQ1 / "data/obligations.json")
assert len(obligation_checks) == 5
for j in obligation_checks:
    assert j["status"] == "verified_obligation"
    assert j["metrics"]["lean_result"]["compiled"] and j["metrics"]["lean_result"]["audit_passed"]
    assert j["target"]["candidate_hash"] == smt[j["target"]["record_id"]]["audit"]["candidate_hash"]

def task(rid):
    return smt[rid]["source_summary_row"]["problem_class"]

def cert_class(rid):
    return smt[rid]["audit"]["certificate_class"]

def lean_pass(c):
    return bool((c.get("formal_result") or {}).get("passed") and
                (c.get("formal_result") or {}).get("source") == "lean" and
                ("lean_result" not in c or
                 ((c.get("lean_result") or {}).get("compiled") and (c.get("lean_result") or {}).get("audit_passed"))))

def category(kind):
    groups = {
        "Equilibrium/value": ["equilibrium_fixed", "v_at_equilibrium"],
        "Positivity/quadratic bounds": ["positive_definite", "quadratic_lower", "quadratic_upper"],
        "Set containment": ["initial_containment", "certified_set_in_X", "sublevel_in_neighborhood", "sublevel_contains_initial"],
        "Unsafe separation": ["unsafe_separation"],
        "Control admissibility": ["control_admissible"],
        "Continuous decrease/exp. decay": ["lie_strict", "lie_negative", "lie_nonpositive", "exponential_decay"],
        "Discrete inductiveness": ["discrete_inductive"],
        "Radial unboundedness": ["radial_unbounded"],
    }
    return next(name for name, kinds in groups.items() if kind in kinds)

composite = {}
for rid, sm in smt.items():
    lc = {c["condition_id"]: c for c in selected[rid]["conditions"] if c["active"]}
    fc = {c["condition_id"]: c for c in full[rid]["conditions"]}
    conditions = {}
    for cid, outcome in sm["cutoff_replay"]["30"]["obligations"].items():
        need = outcome["status"] != "verified"
        c = lc[cid]
        if need:
            assert c.get("timing") is not None, (rid, cid)
        conditions[cid] = {
            "kind": fc[cid]["kind"], "category": category(fc[cid]["kind"]),
            "lean": need, "passed": not need or lean_pass(c),
            "tokens": c["total_tokens"] if need else 0,
            "seconds": outcome["duration_seconds"] + (c["timing"]["wall_seconds"] if need else 0),
        }
    duration = max([conditions[c]["seconds"] for c in sm["audit"]["parallel_condition_ids"]] or [0]) + sum(conditions[c]["seconds"] for c in sm["audit"]["sequential_condition_ids"])
    composite[rid] = {"verified": all(c["passed"] for c in conditions.values()), "seconds": duration, "tokens": sum(c["tokens"] for c in conditions.values()), "conditions": conditions}
assert sum(r["verified"] for r in composite.values()) == 80
assert sum(len(r["conditions"]) for r in composite.values()) == 296
assert sum(c["lean"] for r in composite.values() for c in r["conditions"].values()) == 26
assert [(rid, cid) for rid, r in composite.items() for cid, c in r["conditions"].items() if not c["passed"]] == [("DCB-EXT-P1-001", "96dae1d24041:05:radial_unbounded")]

classes = {}
for cl in ["polynomial", "non_polynomial", "overall"]:
    ids = [rid for rid in smt if cl == "overall" or cert_class(rid) == cl]
    passed = [rid for rid in ids if selected[rid]["verified"]]
    classes[cl] = {
        "systems": len(ids), "verified": len(passed),
        "seconds_per_verified": mean(selected[rid]["verification_wall_seconds"] for rid in passed),
        "selected_record_tokens_all": sum(selected[rid]["total_tokens"] for rid in ids),
        "tokens_per_cohort_system_k": sum(selected[rid]["total_tokens"] for rid in ids) / len(ids) / 1000,
    }
task_rows = []
for t in sorted({task(rid) for rid in smt}) + ["overall"]:
    ids = [rid for rid in smt if t == "overall" or task(rid) == t]
    sm_pass = [rid for rid in ids if smt[rid]["cutoff_replay"]["900"]["status"] == "verified"]
    l_pass = [rid for rid in ids if selected[rid]["verified"]]
    c_pass = [rid for rid in ids if composite[rid]["verified"]]
    task_rows.append({
        "task": t, "systems": len(ids), "all_smt_verified": len(sm_pass), "all_lean_verified": len(l_pass),
        "full_verified": len(ids), "composite_verified": len(c_pass),
        "active": sum(len(full[rid]["conditions"]) for rid in ids),
        "full_lean": sum(c["path"] != "smt" for rid in ids for c in full[rid]["conditions"]),
        "composite_lean": sum(c["lean"] for rid in ids for c in composite[rid]["conditions"].values()),
        "all_smt_seconds": mean(smt[rid]["cutoff_replay"]["900"]["duration_seconds"] for rid in sm_pass),
        "all_lean_seconds": mean(selected[rid]["verification_wall_seconds"] for rid in l_pass),
        "full_seconds": mean(full[rid]["verification_seconds"] for rid in ids),
        "composite_seconds": mean(composite[rid]["seconds"] for rid in c_pass),
    })
condition_rows = []
flat = [c for r in composite.values() for c in r["conditions"].values()]
for cat in dict.fromkeys(c["category"] for c in flat):
    rows = [c for c in flat if c["category"] == cat]
    condition_rows.append({"category": cat, "active": len(rows), "lean": sum(c["lean"] for c in rows), "seconds": sum(c["seconds"] for c in rows)})
full_verification_calls = [c for rid, r in full.items() for c in supp["full_calls"] if c["path"].startswith(r["candidate_path"] + "/") and c["role"] != "proposal"]
full_tokens = sum((c["usage"] or {}).get("total_tokens", 0) for c in full_verification_calls)
assert full_tokens == 675198
cost = {
    "all_lean_selected_tokens": classes["overall"]["selected_record_tokens_all"],
    "all_lean_tokens_k": classes["overall"]["tokens_per_cohort_system_k"],
    "full_selected_tokens": full_tokens, "full_tokens_k": full_tokens / 81000,
    "composite_selected_tokens": sum(r["tokens"] for r in composite.values()),
    "composite_tokens_k": sum(r["tokens"] for r in composite.values()) / 81000,
    "all_attempt_all_lean_tokens": sum(r["total_tokens"] for rows in attempts.values() for r in rows) + sum(j["metrics"]["total_tokens"] for j in obligation_checks),
}
assert cost["all_lean_selected_tokens"] == 2014717 and cost["composite_selected_tokens"] == 740900
e2e_rows = []
for t in sorted({r["problem_class"] for r in full_summary}) + ["overall"]:
    rows = [r for r in full_summary if t == "overall" or r["problem_class"] == t]
    ok = [r for r in rows if r["status"] == "verified"]
    e2e_rows.append({"task": t, "systems": len(rows), "verified": len(ok), "tokens_per_verified_k": mean(r["total_tokens"] for r in ok) / 1000, "seconds_per_verified": mean(r["total_wall_seconds"] for r in ok)})
agent_rows = []
for role in ["proposal", "router", "lean"]:
    calls = [c for c in supp["full_calls"] if c["role"] == role]
    usages = [c["usage"] for c in calls if c["usage"]]
    agent_rows.append({
        "role": role, "calls": len(calls), "with_usage": len(usages),
        "input_k": mean(u["prompt_tokens"] for u in usages) / 1000,
        "reasoning_k": mean((u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) for u in usages) / 1000,
        "visible_output_k": mean(u["completion_tokens"] - (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) for u in usages) / 1000,
    })
assert [r["with_usage"] for r in agent_rows] == [119, 170, 199]
rq3_usage = []
for arm in ["failure_only", "verbatim_diagnostics", "current_guided"]:
    calls = [c for c in supp["rq3_calls"] if c["arm"] == arm]
    u = [c["usage"] for c in calls if c["usage"]]
    rq3_usage.append({
        "arm": arm, "calls": len(calls), "with_usage": len(u),
        "input": sum(z["prompt_tokens"] for z in u),
        "reasoning": sum((z.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) for z in u),
        "visible_output": sum(z["completion_tokens"] - (z.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) for z in u),
        "total": sum(z["total_tokens"] for z in u),
    })

def merge_runs(strategy):
    rows = {row["record_id"]: row for row in load(MAIN / "data" / (strategy + ".json"))}
    assert len(rows) == 105
    return rows

smt_end = merge_runs("smt_only")
lean_end = merge_runs("lean_only")
waterfall = Counter(r["waterfall_bucket"] for r in trace["full_trace"] if r["status"] == "verified")
assert dict(waterfall) == {"one_shot": 63, "lean_repair": 12, "new_candidate": 2, "smt_sat": 4}
end_counts = {"Full": len(full), "SMT-only": sum(r["status"] == "verified" for r in smt_end.values()), "Lean-only": sum(r["status"] == "verified" for r in lean_end.values()), "One-shot": waterfall["one_shot"]}
assert end_counts == {"Full": 81, "SMT-only": 57, "Lean-only": 60, "One-shot": 63}
rq3_repair = {}
for p in sorted((RQ3 / "records").glob("*/*/*/result.json")):
    row = load(p)
    rq3_repair.setdefault(row["arm"], []).append(row)
rq3_repair = {arm: rq3_repair[arm] for arm in ["current_guided", "verbatim_diagnostics", "failure_only"]}
rq3_repair = {arm: {"obligations": len(rows), "repaired": sum(r["outcome"] == "verified" for r in rows), "rounds": mean(r["metrics"]["repair_turns"] for r in rows), "seconds": mean(r["metrics"]["charged_time_seconds"] for r in rows)} for arm, rows in rq3_repair.items()}
initial_tokens = sum(r["total_tokens"] for r in full_summary) + sum(r["total_tokens"] for r in original.values()) + sum(r["total"] for r in rq3_usage)
added_tokens = sum(r["total_tokens"] for r in later_records) + sum(j["metrics"]["total_tokens"] for j in obligation_checks)
assert initial_tokens == 6749725 and initial_tokens + added_tokens == 7826960
baseline = load(MAIN / "baselines/baseline_summary.json")
native_summary = load(MAIN / "baselines/native_acceptance_summary.json")["methods"]
native_sets = {name: set(native_summary[key]["accepted_cases"]) for name, key in {"fossil": "fossil_generic", "cbf": "cbf", "analytical_rl": "analytical_rl", "synnlf": "synnlf"}.items()}
strict_records = {}
for p in sorted((MAIN / "baselines/strict_results").glob("*/summary.json")):
    for name, row in load(p)["methods"].items():
        strict_records[name] = row
strict_sets = {name: {r["case_id"] for r in row["cases"] if r["passed"]} for name, row in strict_records.items()}
assert {name: len(ids) for name, ids in strict_sets.items()} == baseline["strict_counts"]
assert len(set().union(*native_sets.values())) == baseline["native_union"] == 19
assert len(set().union(*strict_sets.values())) == baseline["strict_union"] == 11
assert all(strict_sets[name] <= native_sets[name] for name in strict_sets)

for v in baseline["subsets"].values():
    assert v["full_verified"] == len(set(v["ids"]) & set(full))
union = set().union(*(set(v["ids"]) for v in baseline["subsets"].values()))
assert len(union) == 51 and len(union & set(full)) == 40
assert round(classes["overall"]["seconds_per_verified"], 2) == 579.17
assert round(task_rows[-1]["full_seconds"], 2) == 119.31
assert round(task_rows[-1]["composite_seconds"], 2) == 94.28
assert round(cost["composite_tokens_k"], 2) == 9.15
last_events = Counter()
for run in supp["unresolved"]:
    if not run["lean_results"]:
        event = "No parsed candidate before the shared deadline"
    else:
        last = max(run["lean_results"], key=lambda x: x["mtime"])
        reason = last.get("blocking_reason") or ""
        if "HTTP 429" in reason:
            event = "API rate limit during a Lean call"
        elif "Lean helper module timed out" in reason:
            event = "Lean helper-module timeout"
        elif "Lean compiler timed out" in reason:
            event = "Lean compiler timeout"
        elif "no LeanAgentOutput object" in reason:
            event = "Invalid Lean proof output"
        elif "call exceeded 600s" in reason or "wall-clock budget exhausted" in reason:
            event = "Lean call timeout or shared-deadline exhaustion"
        else:
            event = "Lean agent returned cannot_complete"
    last_events[event] += 1
assert sorted(last_events.values()) == [1, 1, 1, 2, 3, 6, 10]
figure_records, dimension_accounting = load_records()
figure2 = {
    "sources": dict(Counter(source_group(r) for r in figure_records)),
    "dimensions": {tier: [sum(r["tier"] == tier and r["figure2_dimension"] == n for r in figure_records) for n in range(1, 11)] for tier in ["literature", "extended", "ours"]},
    "dimension_accounting": dimension_accounting,
}
source_rows = {}
for record in figure_records:
    if record["tier"] != "literature":
        continue
    reference = record["source"]["citations"][0]
    row = source_rows.setdefault(reference, {"retained": 0, "task_counts": {}, "high_dimension": 0})
    row["retained"] += 1
    task_name = "P" + str(record["problem"])
    row["task_counts"][task_name] = row["task_counts"].get(task_name, 0) + 1
    row["high_dimension"] += int(record["figure2_dimension"] >= 5)
assert sum(r["retained"] for r in source_rows.values()) == 80
curation = load(ROOT / "data/benchmark_curation_counts.json")
assert sum(row["total"] for row in curation["rows"]) == 233
assert curation["retained_total"] == 80
class_rows = {}
for cl in ["polynomial", "non_polynomial"]:
    ids = [rid for rid in smt if cert_class(rid) == cl]
    smt_ok = [smt[rid]["cutoff_replay"]["900"] for rid in ids if smt[rid]["cutoff_replay"]["900"]["status"] == "verified"]
    class_rows[cl] = {
        "systems": len(ids), "all_smt_verified": len(smt_ok),
        "all_smt_seconds": mean(x["duration_seconds"] for x in smt_ok),
        "full_verified": len(ids), "full_seconds": mean(full[rid]["verification_seconds"] for rid in ids),
        "full_systems_with_lean": sum(any(c["path"] != "smt" for c in full[rid]["conditions"]) for rid in ids),
    }

output = {
    "selection_rule": "Use the latest complete compatible certificate attempt. Costs are never minimized across attempts.",
    "table2_end_to_end": end_counts,
    "table2_baseline": baseline,
    "figure3_decomposition": dict(waterfall),
    "figure2_accounting": figure2,
    "table3_all_lean_classes": classes,
    "table3_smt_and_full_classes": class_rows,
    "table4_repair": rq3_repair,
    "table7_full_cost_by_task": e2e_rows,
    "table8_agent_usage": agent_rows,
    "table9_and_table10": task_rows,
    "table11_tokens": cost,
    "table12_condition_groups": condition_rows,
    "table13_rq3_usage": rq3_usage,
    "resource_ledger": {"all_tokens": initial_tokens + added_tokens},
    "obligation_checks_verified": len(obligation_checks),
    "table14_last_events": dict(last_events),
    "table15_reported_curation": curation,
    "table16_retained_by_reference": source_rows,
    "full_verification_paths": dict(Counter(c["path"] for r in full.values() for c in r["conditions"])),
}
(ROOT / "results/paper_tables.json").write_text(json.dumps(output, indent=2) + "\n")
print("Recomputed paper tables, Figure 3 counts, and recorded resource usage.")
print(json.dumps({"end_to_end": end_counts, "mean_seconds": {k: task_rows[-1][k] for k in ["all_lean_seconds", "full_seconds", "composite_seconds"]}, "tokens_per_certificate_k": {k: cost[k] for k in ["all_lean_tokens_k", "full_tokens_k", "composite_tokens_k"]}}, indent=2))
