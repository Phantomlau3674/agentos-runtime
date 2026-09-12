"""DAT-006: storage quota and dry-run GC for task workspaces."""
from __future__ import annotations

import os
import time

import pytest

from agentos_runtime.errors import RuntimeFault
from agentos_runtime.gateway import AgentGateway, initialize_demo
from agentos_runtime.maintenance import enforce_task_quota, gc_apply, gc_plan, home_usage


def submit(gateway, rid):
    return gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': rid})['data']


def test_usage_and_dry_run_gc(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3)
    gateway = AgentGateway(home)
    task = submit(gateway, 'g1')
    usage = home_usage(home)
    assert usage['count'] == 1 and usage['total_bytes'] > 0
    plan = gc_plan(home, older_than_seconds=0)
    assert plan['dry_run'] and len(plan['eligible']) == 1
    # Dry run does not delete.
    assert (home / 'tasks' / task['task_id']).is_dir()


def test_gc_apply_removes_only_eligible(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3)
    gateway = AgentGateway(home)
    old = submit(gateway, 'old')
    new = submit(gateway, 'new')
    old_dir = home / 'tasks' / old['task_id']
    new_dir = home / 'tasks' / new['task_id']
    # Age the old task artificially.
    past = time.time() - 400_000
    for root, _, files in os.walk(old_dir):
        for name in files:
            os.utime(os.path.join(root, name), (past, past))
    os.utime(old_dir, (past, past))
    plan = gc_plan(home, older_than_seconds=3600)
    assert [e['task_id'] for e in plan['eligible']] == [old['task_id']]
    applied = gc_apply(home, plan)
    assert applied['removed'] == [old['task_id']]
    assert not old_dir.exists() and new_dir.exists()


def test_quota_refuses_new_tasks(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3)
    gateway = AgentGateway(home)
    submit(gateway, 'q1')
    with pytest.raises(RuntimeFault) as exc:
        enforce_task_quota(home, max_tasks=1, max_total_bytes=10**12)
    assert exc.value.code == 'TASK_BUDGET'
    with pytest.raises(RuntimeFault) as exc:
        enforce_task_quota(home, max_tasks=100, max_total_bytes=home_usage(home)['total_bytes'])
    assert exc.value.code == 'TASK_BUDGET'


def test_submit_respects_owner_quota(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3)
    policy = (home / 'owner_policy.json').read_text(encoding='utf-8')
    import json
    data = json.loads(policy)
    data['max_task_bytes'] = 1_048_576  # 1 MiB floor
    import os as _os
    _os.chmod(home / 'owner_policy.json', 0o666)
    (home / 'owner_policy.json').write_text(json.dumps(data), encoding='utf-8')
    gateway = AgentGateway(home)
    # Inflate usage past the 1 MiB owner cap, then a new submit must be refused.
    filler = home / 'tasks' / 'pad'
    filler.mkdir()
    (filler / 'blob.bin').write_bytes(b'x' * 1_100_000)
    out = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 'a'})
    assert out['error']['code'] == 'TASK_BUDGET'
