"""Check the final dataset and release contents."""
from __future__ import annotations
import json
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/dynacertbench_by_problem.json'
records = json.loads(DATA.read_text())
assert records.get('meta', {}).get('record_count') == 105
all_records = [r for bucket in records['problems'].values() for r in bucket['records']]
assert len(all_records) == 105
assert {r['tier'] for r in all_records} == {'literature', 'extended', 'ours'}
private_patterns = [re.compile(r'sk-(?:or-v1-|ant-)?[A-Za-z0-9_-]{16,}'), re.compile('/'+'Users/'), re.compile('/'+'home/'), re.compile(r'^-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----$', re.M)]
skip_parts = {'.git', '__pycache__', '.pytest_cache', '.ruff_cache', '.venv', 'venv', '.lake', 'tests'}
skip_dirs = [ROOT / 'runs', ROOT / 'benchmark/experiments', ROOT / 'benchmark/analysis/figures', ROOT / 'llm2cert/formalization/work']
for p in ROOT.rglob('*'):
    rel = p.relative_to(ROOT).parts
    if not p.is_file() or skip_parts.intersection(rel) or any(part.endswith('.egg-info') for part in rel) or any(p.is_relative_to(d) for d in skip_dirs) or p.resolve() == Path(__file__).resolve() or p.suffix.lower() in {'.pdf', '.png', '.jpg', '.jpeg', '.gz'} or p.stat().st_size > 20_000_000: continue
    s=p.read_text(errors='replace')
    assert not any(pattern.search(s) for pattern in private_patterns), p
assert (ROOT/'llm2cert/formalization/lean/LeanBarrier/Continuous.lean').is_file()
assert (ROOT/'llm2cert/framework/lean_barrier/s16_workflow.py').is_file()
print(f'verified release: {len(all_records)} systems')
