"""REV-010: observation provenance, explicit staleness, conflict audit events."""
from __future__ import annotations

import sqlite3

import pytest

from agentos_runtime.contracts import default_plan
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.fixtures import generate
from agentos_runtime.gateway import AgentGateway, initialize_demo
from agentos_runtime.runtime import Runtime


def setup(tmp_path, files=4, rows=10):
    home = tmp_path / 'home'
    initialize_demo(home, files=files, rows=rows, seed=5)
    return home, AgentGateway(home)


def submit(gateway, request_id='req-1'):
    return gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': request_id})['data']


def test_succeeded_observation_has_provenance_and_staleness(tmp_path):
    _, gateway = setup(tmp_path)
    task = submit(gateway)
    out = gateway.call('task_inspect', {'task_id': task['task_id']})['data']
    obs = out['observation']
    assert obs['artifact_check'] == 'full_revalidation_at_this_call'
    assert obs['result_binding'] == 'historical_result_for_recorded_input_version'
    assert obs['stale'] is False


def test_inputs_changed_marks_result_stale_not_still_fresh(tmp_path):
    home, gateway = setup(tmp_path)
    task = submit(gateway)
    fixture_input = next((home / 'fixtures' / 'demo' / 'inputs').glob('*.csv'))
    fixture_input.write_text(fixture_input.read_text() + '#tampered\n')
    out = gateway.call('task_inspect', {'task_id': task['task_id']})['data']
    assert out['status'] == 'SUCCEEDED'  # historical record is honest
    assert out['observation']['stale'] is True  # but explicitly marked stale


def test_missing_dataset_marks_staleness_unknown(tmp_path):
    home, gateway = setup(tmp_path)
    task = submit(gateway)
    import shutil
    shutil.rmtree(home / 'fixtures' / 'demo' / 'inputs')
    out = gateway.call('task_inspect', {'task_id': task['task_id']})['data']
    assert out['observation']['stale'] == 'unknown'


def test_failed_task_observation_is_explicit(tmp_path):
    _, gateway = setup(tmp_path)
    plan = default_plan().model_dump()
    plan['limits']['max_rows'] = 1
    failed = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 'f',
                                          'plan': plan})['data']
    out = gateway.call('task_inspect', {'task_id': failed['task_id']})['data']
    assert out['status'] == 'FAILED'
    obs = out['observation']
    assert obs['artifact_check'] == 'not_performed'
    assert obs['stale'] == 'not_applicable'


def test_idempotent_conflict_writes_audit_event(tmp_path):
    _, gateway = setup(tmp_path)
    task = submit(gateway)
    plan = default_plan().model_dump()
    plan['limits']['max_rows'] = 1  # different plan, same request_id
    out = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 'req-1',
                                       'plan': plan})
    assert out['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    events = gateway.call('task_events', {'task_id': task['task_id'], 'limit': 100})['data']
    kinds = [e['kind'] for e in events['events']]
    assert 'audit.idempotent_conflict' in kinds


def test_plan_changed_resume_writes_audit_event(tmp_path):
    oracle = generate(tmp_path / 'fx', 2, 2, seed=3)
    workspace = tmp_path / 'ws'
    Runtime().run(default_plan(), tmp_path / 'fx' / 'inputs', workspace, oracle)
    from agentos_runtime.contracts import PlanSpec
    plan = default_plan().model_dump()
    plan['goal'] = 'changed goal text'
    mutated = PlanSpec.model_validate(plan).canonical_bytes()
    target = workspace / 'plan.json'
    target.chmod(0o666)  # plan.json is created read-only by new_file
    target.write_bytes(mutated)
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace, tmp_path / 'fx' / 'inputs', oracle)
    assert exc.value.code == 'PLAN_CHANGED'
    conn = sqlite3.connect(workspace / 'journal.sqlite3')
    try:
        kinds = [r[0] for r in conn.execute('SELECT kind FROM events')]
    finally:
        conn.close()
    assert 'audit.plan_changed' in kinds
