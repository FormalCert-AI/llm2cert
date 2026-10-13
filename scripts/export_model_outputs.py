"""Export saved prompts, responses, and repair logs as Markdown and CSV."""
import csv
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def load(path):
    return json.loads(path.read_text())


def fence(value, language="text"):
    text = str(value or "")
    ticks = "`" * max(3, max([len(s) for s in re.findall(r"`+", text)] or [0]) + 1)
    return f"{ticks}{language}\n{text}\n{ticks}\n"


def call_text(call, label):
    parts = [f"### {label}\n\n",
             f'Model: `{call.get("model_id", "not recorded")}`. '
             f'Status: `{call.get("status", "not recorded")}`.\n\n',
             "<details><summary>Prompt and recorded request settings</summary>\n\n",
             fence(call.get("prompt")),
             fence(json.dumps(call.get("parameters") or {}, ensure_ascii=False, indent=2), "json")]
    conversation = (call.get("call_info") or {}).get("conversation_messages")
    if conversation:
        parts += ["Recorded conversation:\n\n", fence(json.dumps(conversation, ensure_ascii=False, indent=2), "json")]
    parts += ["\n</details>\n\nResponse:\n\n"]
    if call.get("response"):
        parts += [fence(call["response"])]
    else:
        parts += ["No response was saved for this call.\n"]
    if call.get("error"):
        parts += ["\nRecorded error:\n\n", fence(call["error"])]
    return "".join(parts)


def write_index(group, rows):
    path = RESULTS / group / "calls.csv"
    fields = ["record_id", "strategy", "fixture_id", "role", "model", "status",
              "response_saved", "source", "model_outputs"]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def index_row(rid, strategy, path, call, transcript, fixture=""):
    group = path.relative_to(RESULTS).parts[0]
    return {"record_id": rid, "strategy": strategy, "fixture_id": fixture,
            "role": call.get("role", "lean"), "model": call.get("model_id", ""),
            "status": call.get("status", ""), "response_saved": bool(call.get("response")),
            "source": path.relative_to(RESULTS / group).as_posix(),
            "model_outputs": transcript.relative_to(RESULTS / group).as_posix()}


for group, strategies in [("main", ["full", "smt_only", "lean_only"]), ("rq1", ["all_lean"]),
                          ("rq2", [""])]:
    rows = []
    for strategy in strategies:
        base = RESULTS / group / "records" / strategy
        for record in sorted(base.iterdir()):
            if not record.is_dir():
                continue
            transcript = RESULTS / group / strategy / (record.name + ".md")
            transcript.parent.mkdir(parents=True, exist_ok=True)
            parts = [f'# {record.name}: {(strategy or "routed").replace("_", " ")}\n\n']
            for run in sorted(record.iterdir()):
                if not run.is_dir():
                    continue
                parts += [f"## {run.name}\n\n"]
                calls = []
                pattern = "candidates/**/calls/*.json" if group != "rq2" else "candidates/*/conditions/**/calls/*.json"
                for path in run.glob(pattern):
                    call = load(path)
                    stamp = (call.get("call_info") or {}).get("called_at_utc") or call.get("updated_at_utc") or ""
                    calls.append((stamp, path, call))
                for _, path, call in sorted(calls):
                    parts += [call_text(call, path.relative_to(run).as_posix()), "\n"]
                    rows.append(index_row(record.name, strategy or "routed", path, call, transcript))
                if not calls:
                    parts += ["This run contains no saved model calls.\n\n"]
            transcript.write_text("".join(parts))
    write_index(group, rows)
    print(f"{group}: {len(rows)} saved calls")

rows = []
for result_path in sorted((RESULTS / "rq3/records").glob("*/*/*/result.json")):
    directory = result_path.parent
    result = load(result_path)
    fixture = result["fixture"]
    relative = directory.relative_to(RESULTS / "rq3/records")
    transcript = (RESULTS / "rq3" / relative).with_suffix(".md")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    parts = [f'# {fixture["fixture_id"]}: {directory.name.replace("_", " ")}\n\n',
             f'Outcome: `{result["outcome"]}`. Repair rounds: {result["metrics"]["repair_turns"]}.\n\n']
    first = directory / "frozen/initial-call.json"
    parts += [call_text(load(first), "Frozen first attempt"), "\n"]
    for path in sorted((directory / "agents").glob("*.json")):
        call = load(path)
        parts += [call_text(call, "Repair " + path.stem), "\n"]
        rows.append(index_row(fixture["record_id"], directory.name, path, call, transcript, fixture["fixture_id"]))
    for path in sorted((directory / "compiler").glob("*-result.json")):
        parts += [f"### Compiler {path.stem}\n\n", fence(json.dumps(load(path), ensure_ascii=False, indent=2), "json")]
        source = path.with_name(path.name.replace("-result.json", "-source.lean"))
        if source.exists():
            parts += [fence(source.read_text(), "lean")]
    transcript.write_text("".join(parts))
write_index("rq3", rows)
print(f"rq3: {len(rows)} saved repair calls")
