"""REV-011: trusted action registry, declared read/write/effect sets."""
from __future__ import annotations

import sqlite3

import pytest

from agentos_runtime.actions import ACTION_CONTRACTS, action_contract
from agentos_runtime.contracts import COMPUTE_OPERATIONS, OPERATIONS, default_plan
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.fixtures import generate
from agentos_runtime.gateway import AgentGateway, initialize_demo
from agentos_runtime.runtime import Runtime


def test_registry_covers_exactly_the_managed_operations():
    assert set(ACTION_CONTRACTS) == set(OPERATIONS) | set(COMPUTE_OPERATIONS)
    for contract in ACTION_CONTRACTS.values():
        assert contract.operation and contract.reads and contract.writes
        assert contract.effect in {'internal', 'published_artifact', 'attestation'}


def test_unregistered_operation_is_denied():
    with pytest.raises(RuntimeFault) as exc:
        action_contract('shell.execute')
    assert exc.value.code == 'ACTION_UNREGISTERED'


def test_capabilities_expose_declared_effects(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3)
    gateway = AgentGateway(home)
    info = gateway.call('runtime_capabilities', {})['data']
    declared = {c['operation']: c for c in info['action_contracts']}
    assert set(declared) == set(OPERATIONS) | set(COMPUTE_OPERATIONS)
    assert declared['files.dedup_manifest']['effect'] == 'internal'
    assert declared['artifacts.export']['effect'] == 'published_artifact'
    assert declared['verification.fixture']['effect'] == 'attestation'
    assert 'workspace://staging/*' in declared['artifacts.export']['writes']


def test_intent_events_carry_effect_class(tmp_path):
    oracle = generate(tmp_path / 'fx', 2, 2, seed=3)
    workspace = tmp_path / 'ws'
    Runtime().run(default_plan(), tmp_path / 'fx' / 'inputs', workspace, oracle)
    conn = sqlite3.connect(workspace / 'journal.sqlite3')
    try:
        intents = conn.execute(
            "SELECT payload FROM events WHERE kind='operation_intent'").fetchall()
    finally:
        conn.close()
    import json
    effects = {json.loads(payload)['effect'] for (payload,) in intents}
    assert effects == {'internal', 'published_artifact', 'attestation'}
