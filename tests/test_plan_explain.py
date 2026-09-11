"""REV-013: plan_explain -- compile + explain without executing."""
from __future__ import annotations

from agentos_runtime.contracts import default_plan
from agentos_runtime.gateway import AgentGateway, initialize_demo


def setup(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3)
    return AgentGateway(home)


def test_explain_default_plan(tmp_path):
    gateway = setup(tmp_path)
    out = gateway.call('plan_explain', {})
    assert out['ok'], out
    data = out['data']
    assert data['valid'] and data['side_effects'].startswith('none')
    assert data['ir_version'] == 'aor.ir.v0.1'
    assert data['plan_hash'] == default_plan().plan_hash
    assert len(data['nodes']) == 4
    assert all(n['owner_policy'] and n['contract_scope'] is None for n in data['nodes'])
    assert data['nodes'][2]['effect'] == 'published_artifact'
    assert 'workspace://staging/*' in data['nodes'][2]['writes']


def test_explain_is_side_effect_free(tmp_path):
    gateway = setup(tmp_path)
    gateway.call('plan_explain', {'plan': default_plan().model_dump()})
    import sqlite3
    conn = sqlite3.connect(tmp_path / 'home' / 'registry.sqlite3')
    try:
        assert conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
    finally:
        conn.close()


def test_explain_shows_contract_and_policy_denial(tmp_path):
    gateway = setup(tmp_path)
    plan = default_plan().model_dump()
    plan['goal_contract'] = {'goal': 'x', 'allowed_operations': ['inputs.snapshot'],
                             'acceptance': 'fixture_integer_cents.v0.1'}
    out = gateway.call('plan_explain', {'plan': plan})['data']
    assert out['contract']['allowed_operations'] == ['inputs.snapshot']
    assert out['nodes'][1]['contract_scope'] is False  # tabular.aggregate excluded


def test_explain_rejects_invalid_plan(tmp_path):
    gateway = setup(tmp_path)
    out = gateway.call('plan_explain', {'plan': {'goal': 'x', 'nodes': []}})
    assert not out['ok']
    assert out['error']['code'] == 'INVALID_ARGUMENT'
