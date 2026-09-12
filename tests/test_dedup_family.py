"""ADP-006: second independent file task family -- content-hash dedup manifest."""
from __future__ import annotations

import json
import sqlite3

import pytest

from agentos_runtime.contracts import GoalContract, PlanSpec, default_dedup_plan, default_plan
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.fixtures import generate, generate_dedup
from agentos_runtime.gateway import AgentGateway, initialize_demo
from agentos_runtime.runtime import Runtime


def dedup_contract(**overrides):
    base = {'goal': '去重合成文件', 'acceptance': 'fixture_dedup_manifest.v1'}
    base.update(overrides)
    return GoalContract(**base)


def test_dedup_pipeline_end_to_end(tmp_path):
    oracle = generate_dedup(tmp_path / 'fx', files=20, duplicate_groups=3, seed=4)
    record = Runtime().run(default_dedup_plan(), tmp_path / 'fx' / 'inputs',
                           tmp_path / 'ws', oracle)
    assert record['status'] == 'SUCCEEDED'
    assert record['verification']['validator'] == 'fixture_dedup_manifest.v1'
    assert record['verification']['passed'] is True
    assert set(record['artifacts']) == {'dedup_report.json', 'duplicates.csv',
                                        'verification.json'}
    report = json.loads((tmp_path / 'ws' / 'outputs' / 'dedup_report.json').read_bytes())
    assert report['total_files'] == oracle['total_files']
    assert report['duplicate_groups'] == oracle['duplicate_groups']


def test_dedup_rejects_wrong_family_oracle(tmp_path):
    """Dedup plan on the tabular dataset fails closed before any node runs."""
    oracle = generate(tmp_path / 'fx', 2, 2, seed=3)
    record = Runtime().run(default_dedup_plan(), tmp_path / 'fx' / 'inputs',
                           tmp_path / 'ws', oracle)
    assert record['status'] == 'FAILED'
    assert record['error_code'] == 'ORACLE_MISMATCH'
    assert record['artifact_state'] == 'not_delivered'


def test_dedup_crash_reconcile_and_resume(tmp_path):
    oracle = generate_dedup(tmp_path / 'fx', files=12, duplicate_groups=2, seed=4)
    workspace = tmp_path / 'ws'

    class Crash(BaseException):
        pass

    def kill(current, _):
        if current == 'aggregate_saved':
            raise Crash()

    with pytest.raises(Crash):
        Runtime().run(default_dedup_plan(), tmp_path / 'fx' / 'inputs', workspace, oracle,
                      phase_hook=kill)
    record = Runtime().resume(workspace, tmp_path / 'fx' / 'inputs', oracle)
    assert record['status'] == 'SUCCEEDED'
    assert record['metrics']['reconciled_nodes'] == ['dedup']


def test_dedup_via_gateway_and_contract_acceptance(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3, dedup=True, dedup_files=12)
    gateway = AgentGateway(home)
    datasets = gateway.call('datasets_list', {})['data']['datasets']
    assert {d['dataset_id'] for d in datasets} == {'demo', 'dedup'}
    assert next(d for d in datasets if d['dataset_id'] == 'dedup')['family'] == \
        'aor.fixture-oracle-dedup.v0.1'

    plan = default_dedup_plan().model_dump()
    out = gateway.call('task_submit', {'dataset_id': 'dedup', 'request_id': 'd1',
                                       'plan': plan})
    assert out['ok'] and out['data']['status'] == 'SUCCEEDED'

    plan['goal_contract'] = {'goal': 'x', 'acceptance': 'fixture_dedup_manifest.v1'}
    bound = gateway.call('task_submit', {'dataset_id': 'dedup', 'request_id': 'd2',
                                         'plan': plan})
    assert bound['data']['status'] == 'SUCCEEDED'
    record = json.loads((home / 'tasks' / bound['data']['task_id']
                         / 'run' / 'run.json').read_text(encoding='utf-8'))
    assert record['acceptance']['validator'] == 'fixture_dedup_manifest.v1'

    plan['goal_contract'] = {'goal': 'x', 'acceptance': 'fixture_integer_cents.v0.1'}
    wrong = gateway.call('task_submit', {'dataset_id': 'dedup', 'request_id': 'd3',
                                         'plan': plan})
    assert wrong['data']['status'] == 'FAILED'
    assert wrong['data']['error_code'] == 'ACCEPTANCE_MISMATCH'


def test_dedup_intent_events_carry_effect(tmp_path):
    oracle = generate_dedup(tmp_path / 'fx', files=8, duplicate_groups=1, seed=4)
    workspace = tmp_path / 'ws'
    Runtime().run(default_dedup_plan(), tmp_path / 'fx' / 'inputs', workspace, oracle)
    conn = sqlite3.connect(workspace / 'journal.sqlite3')
    try:
        intents = [json.loads(p) for (p,) in conn.execute(
            "SELECT payload FROM events WHERE kind='operation_intent'")]
    finally:
        conn.close()
    assert {i['operation'] for i in intents} == {
        'inputs.snapshot', 'files.dedup_manifest', 'artifacts.export', 'verification.fixture'}
    assert all(i['effect'] for i in intents)


def test_plan_spec_accepts_both_families():
    assert default_plan().nodes[1].operation == 'tabular.aggregate'
    assert default_dedup_plan().nodes[1].operation == 'files.dedup_manifest'
    bad = default_dedup_plan().model_dump()
    bad['nodes'][1]['operation'] = 'verification.fixture'
    with pytest.raises(Exception):
        PlanSpec.model_validate(bad)
