"""BEN-005 (partial): A/B cost comparison -- governed runtime vs bare batch.

A: bare batch path (read -> aggregate -> write -> verify; no journal, snapshot,
   checkpoint, lock, receipt or audit events).
B: the governed Runtime().run on the same fixture.

This measures the LOCAL cost of governance machinery on a synthetic fixture.
It is NOT a live-model, end-to-end agent, or production performance claim.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from time import perf_counter
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from agentos_runtime.contracts import default_plan
from agentos_runtime.fixtures import generate
from agentos_runtime.runtime import Runtime
from agentos_runtime.storage import digest, input_paths, json_bytes, new_file, read_bounded
from agentos_runtime.tabular import aggregate, summary_csv
from agentos_runtime.verification import verify_tabular


def bare_batch(fixture: Path, output: Path) -> float:
    plan = default_plan()
    t0 = perf_counter()
    remaining = plan.limits.max_input_bytes
    blobs = {}
    for path in input_paths(fixture / 'inputs', plan.limits.max_files):
        blob = read_bounded(path, remaining)
        remaining -= len(blob)
        blobs[path.name] = blob
    hashes = {n: digest(b) for n, b in blobs.items()}
    oracle = json.loads(read_bounded(fixture / 'oracle.json', 16_777_216))
    if hashes != oracle.get('input_hashes'):
        raise RuntimeError('oracle mismatch')
    result = aggregate(blobs, plan.limits.max_rows)
    output.mkdir(parents=True)
    data = {'summary.json': json_bytes({k: v for k, v in result.items() if k != 'errors'}),
            'errors.json': json_bytes(result['errors']),
            'summary.csv': summary_csv(result['groups'])}
    for n, b in data.items():
        new_file(output / n, b)
    persisted = {n: read_bounded(output / n, plan.limits.max_artifact_bytes) for n in data}
    report = verify_tabular(persisted, oracle, hashes, hashes)
    if not report['passed']:
        raise RuntimeError('verification failed')
    return perf_counter() - t0


def governed(fixture: Path, workspace: Path, oracle: dict) -> float:
    t0 = perf_counter()
    record = Runtime().run(default_plan(), fixture / 'inputs', workspace, oracle)
    assert record['status'] == 'SUCCEEDED'
    return perf_counter() - t0


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('ab_compare.json')
    files, rows, runs = 50, 10, 3
    results = {'fixture': {'files': files, 'rows': rows}, 'runs': runs, 'samples': {}}
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        fixture = root / 'fx'
        oracle = generate(fixture, files, rows, seed=7)
        results['samples']['A_bare_batch'] = [
            bare_batch(fixture, root / f'a{i}') for i in range(runs)]
        results['samples']['B_governed_runtime'] = [
            governed(fixture, root / f'b{i}', oracle) for i in range(runs)]
    for name, samples in results['samples'].items():
        samples[:] = [round(s, 4) for s in samples]
    med = {k: statistics.median(v) for k, v in results['samples'].items()}
    results['median_seconds'] = med
    results['overhead_ratio'] = round(med['B_governed_runtime'] / med['A_bare_batch'], 3)
    results['scope'] = ('offline synthetic fixture; governance-cost comparison only; '
                        'not a live-model or production claim')
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(results['median_seconds']), 'overhead_ratio=', results['overhead_ratio'])


if __name__ == '__main__':
    main()
