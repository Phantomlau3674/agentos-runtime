"""REV-014: compile key vs result key separation and invalidation matrix."""
from __future__ import annotations

import sqlite3

import pytest

from agentos_runtime.contracts import default_plan
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.fixtures import generate
from agentos_runtime.gateway import AgentGateway, initialize_demo
from agentos_runtime.runtime import Runtime


def test_result_key_vs_compile_key(tmp_path):
    """request_id dedups on the result key (dataset+oracle+plan); a different
    plan under the same request_id is a conflict, not a cache hit."""
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3)
    gateway = AgentGateway(home)
    first = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 'k1'})['data']
    again = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 'k1'})['data']
    assert again['task_id'] == first['task_id'] and again['replayed_request']
    different = default_plan().model_dump()
    different['goal'] = 'different goal changes compile key'
    conflict = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 'k1',
                                            'plan': different})
    assert conflict['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_engine_version_invalidates_receipts(tmp_path):
    oracle = generate(tmp_path / 'fx', 2, 2, seed=3)
    workspace = tmp_path / 'ws'

    class Crash(BaseException):
        pass

    def kill(current, _):
        if current == 'aggregate_saved':
            raise Crash()

    with pytest.raises(Crash):
        Runtime().run(default_plan(), tmp_path / 'fx' / 'inputs', workspace, oracle,
                      phase_hook=kill)
    conn = sqlite3.connect(workspace / 'journal.sqlite3')
    try:
        conn.execute("UPDATE metadata SET engine='tampered-engine'")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace, tmp_path / 'fx' / 'inputs', oracle)
    assert exc.value.code == 'ENGINE_CHANGED'


def test_session_close_frees_memory_not_recovery_artifacts(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3)
    gateway = AgentGateway(home)
    task = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 's1'})['data']
    artifact = task['artifacts'][0]
    opened = gateway.call('artifact_open', {'task_id': task['task_id'],
                                            'artifact_id': artifact['artifact_id']})['data']
    gateway.call('artifact_session_close', {'session_id': opened['session_id']})
    workspace = home / 'tasks' / task['task_id'] / 'run'
    assert (workspace / 'snapshots').is_dir() and any((workspace / 'snapshots').iterdir())
    assert (workspace / 'outputs' / 'summary.json').exists()
    assert (workspace / 'journal.sqlite3').exists()


def test_irrelevant_change_does_not_invalidate(tmp_path):
    """Reading artifacts / inspecting does not disturb the stored run; a second
    inspect returns the identical record."""
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3)
    gateway = AgentGateway(home)
    task = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 'r1'})['data']
    one = gateway.call('task_inspect', {'task_id': task['task_id']})['data']
    gateway.call('artifact_read', {'task_id': task['task_id'],
                                   'artifact_id': task['artifacts'][0]['artifact_id']})
    two = gateway.call('task_inspect', {'task_id': task['task_id']})['data']
    assert one['plan_hash'] == two['plan_hash']
    assert one['observation']['stale'] == two['observation']['stale']
