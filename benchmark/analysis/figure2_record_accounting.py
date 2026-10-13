"""Reconcile Figure 2 dimensions and source groups with the benchmark inputs."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

def load_records():
    descriptive_path = DATA / "dynacertbench_by_problem.json"
    executable_path = DATA / "dynacertbench_executable.json"
    descriptions = json.loads(descriptive_path.read_text())
    records = [r for bucket in descriptions["problems"].values() for r in bucket["records"]]
    execution = {r["record_id"]: r for r in json.loads(executable_path.read_text())["records"]}
    assert len(records) == len(execution) == 105
    assert {r["record_id"] for r in records} == set(execution)
    reconciliations = []
    for r in records:
        rid = r["record_id"]
        problem = execution[rid]["problem"]
        dynamics = problem["dynamics"]
        names = re.findall(r"(?:^|,)\s*d([A-Za-z][A-Za-z_0-9]*)/dt\s*=", dynamics)
        if not names:
            names = re.findall(r"(?:^|,)\s*([A-Za-z][A-Za-z_0-9]*)\[k\+1\]\s*=", dynamics)
        assert names and len(names) == len(set(names)), (rid, dynamics)
        n = len(names)
        if "equilibrium" in problem:
            assert len(problem["equilibrium"]) == n, rid
        if n != r["system"]["dimension"]["value"]:
            reconciliations.append({
                "record_id": rid, "title": r["source"]["title_latex"],
                "archived_descriptive_dimension": r["system"]["dimension"]["value"],
                "actual_state_dimension": n, "state_variables": names,
                "executable_dynamics": dynamics,
                "paper_declares_reduced_state": r["system"]["specification_latex"],
            })
        r["figure2_dimension"] = n
    assert [(r["record_id"], r["archived_descriptive_dimension"], r["actual_state_dimension"]) for r in reconciliations] == [
        ("DCB-LIT-P1-015", 4, 3), ("DCB-LIT-P1-018", 6, 5)
    ]
    evidence = {
        "dimension_definition": "Number of independent state variables in the archived executable question. Original coordinate count before the documented center-of-inertia reduction is not used.",
        "reconciliations": reconciliations,
        "source_group_policy": "Preserve original grouped Figure 2: three Samanipour ReLU cases plus the Wu 2023 PVTOL case form the explicitly named Samanipour/PVTOL group. Table 16 remains per-paper provenance.",
        "input_files": [
            str(p.relative_to(ROOT))
            for p in [descriptive_path, executable_path]
        ],
    }
    return records, evidence

def source_group(r):
    if r["tier"] == "ours":
        return "New / Ours"
    if r["record_id"] == "DCB-LIT-P3-001":
        assert r["source"]["citations"] == ["wu2023neural"]
        return "Samanipour/PVTOL"
    cites = r["source"]["citations"]
    assert len(cites) == 1, r["record_id"]
    groups = {
        "taheri2025barrierbench": "BarrierBench",
        "abate2021fossil": "FOSSIL papers",
        "edwards2024fossil": "FOSSIL papers",
        "zou2025analytical": "Zou et al.",
        "liu2023towards": "Jun Liu et al.",
        "liu2024tool": "Jun Liu et al.",
        "liu2026globally": "Jun Liu et al.",
        "samanipour2026relu": "Samanipour/PVTOL",
        "wu2024completeness": "Wu et al.",
        "zhou2022neural": "Zhou et al.",
        "liu2015abstraction": "Jiang Liu et al.",
    }
    return groups.get(cites[0], "Other literature")
