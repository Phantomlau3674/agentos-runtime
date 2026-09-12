"""REV-015: resource keys, conflict control, bounded queues, budget propagation."""
from __future__ import annotations

import pytest

from agentos_runtime.contracts import default_plan
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.fixtures import generate
from agentos_runtime.gateway import AgentGateway, initialize_demo
from agentos_runtime.journal import MAX_ATTEMPTS
from agentos_runtime.locking import workspace_lock
from agentos_runtime.runtime import Policy, Runtime


class Crash(BaseException):
    pass


def crash_run(tmp_path):
    oracle = generate(tmp_path / 'fx', 2, 2, seed=3)
    workspace = tmp_path / 'ws'

    def kill(current, _):
        if current == 'aggregate_saved':
            raise Crash()

    with pytest.raises(Crash):
        Runtime().run(default_plan(), tmp_path / 'fx' / 'inputs', workspace, oracle,
                      phase_hook=kill)
    return oracle, tmp_path / 'fx' / 'inputs', workspace


def test_resume_attempt_budget_enforced(tmp_path):
    oracle, inputs, workspace = crash_run(tmp_path)

    def kill(current, _):
        if current == 'aggregate_saved':
            raise Crash()

    for _ in range(MAX_ATTEMPTS - 1):
        with pytest.raises(Crash):
            Runtime().resume(workspace, inputs, oracle, phase_hook=kill)
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace, inputs, oracle, phase_hook=kill)
    assert exc.value.code == 'RECOVERY_BUDGET'


def test_same_workspace_cannot_run_concurrently(tmp_path):
    oracle, inputs, workspace = crash_run(tmp_path)
    with workspace_lock(workspace):
        with pytest.raises(RuntimeFault) as exc:
            Runtime().resume(workspace, inputs, oracle)
        assert exc.value.code == 'WORKSPACE_BUSY'


def test_same_dataset_independent_tasks_do_not_conflict(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3)
    gateway = AgentGateway(home)
    a = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 'a'})['data']
    b = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 'b'})['data']
    assert a['status'] == 'SUCCEEDED' and b['status'] == 'SUCCEEDED'
    assert a['task_id'] != b['task_id']


def test_parallel_snapshot_reads_deterministic(tmp_path):
    """EXE-003: >=8 files take the bounded parallel read path; output identical."""
    oracle = generate(tmp_path / 'fx', 20, 10, seed=9)
    inputs = tmp_path / 'fx' / 'inputs'
    a = Runtime().run(default_plan(), inputs, tmp_path / 'a', oracle)
    b = Runtime().run(default_plan(), inputs, tmp_path / 'b', oracle)
    assert a['status'] == b['status'] == 'SUCCEEDED'
    assert {k: v['sha256'] for k, v in a['artifacts'].items()} == \
        {k: v['sha256'] for k, v in b['artifacts'].items()}


def test_cancel_mid_run_stops_at_action_boundary(tmp_path):
    """EXE-004: flipping the owner policy's cancel flag stops dispatch at the
    next action boundary; the task is terminal CANCELLED, not retried."""
    oracle = generate(tmp_path / 'fx', 4, 2, seed=3)
    workspace = tmp_path / 'ws'
    policy = Policy()

    def cancel_after_snapshot(current, _):
        if current == 'node_committed:snapshot':
            policy.cancelled = True

    record = Runtime().run(default_plan(), tmp_path / 'fx' / 'inputs', workspace,
                           oracle, policy=policy, phase_hook=cancel_after_snapshot)
    assert record['status'] == 'CANCELLED' and record['error_code'] == 'CANCELLED'
    assert record['artifact_state'] == 'not_delivered'
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace, tmp_path / 'fx' / 'inputs', oracle)
    assert exc.value.code == 'TERMINAL_RUN'


def test_no_retry_multiplication_across_layers(tmp_path):
    """Errors carry automatic_retry:false; nothing retries internally."""
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3)
    gateway = AgentGateway(home)
    out = gateway.call('task_inspect', {'task_id': '0' * 32})
    assert out['error']['code'] == 'TASK_NOT_FOUND'
    assert out['error']['automatic_retry'] is False
    plan = default_plan().model_dump()
    plan['limits']['max_rows'] = 1
    failed = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 'f',
                                          'plan': plan})['data']
    assert failed['status'] == 'FAILED'
    again = gateway.call('task_inspect', {'task_id': failed['task_id']})['data']
    assert again['status'] == 'FAILED'  # terminal: no silent retry
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(home / 'tasks' / failed['task_id'] / 'run',
                         home / 'fixtures' / 'demo' / 'inputs',
                         __import__('json').loads(
                             (home / 'fixtures' / 'demo' / 'oracle.json').read_text()))
    assert exc.value.code == 'TERMINAL_RUN'
