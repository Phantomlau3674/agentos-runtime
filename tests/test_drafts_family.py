"""ADP-005: third task family -- local mock draft site (idempotent keys, readback)."""
from __future__ import annotations

import json
import sqlite3

import pytest

from agentos_runtime.contracts import PlanSpec, default_drafts_plan, default_plan
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.fixtures import generate_dedup, generate_drafts
from agentos_runtime.gateway import AgentGateway, initialize_demo
from agentos_runtime.runtime import Runtime


def test_mock_draft_flow_end_to_end(tmp_path):
    oracle = generate_drafts(tmp_path / 'fx', briefs=8, seed=4)
    record = Runtime().run(default_drafts_plan(), tmp_path / 'fx' / 'inputs',
                           tmp_path / 'ws', oracle)
    assert record['status'] == 'SUCCEEDED'
    assert record['verification']['validator'] == 'fixture_drafts_mock.v1'
    assert set(record['artifacts']) == {'draft_manifest.json', 'drafts.csv',
                                        'verification.json'}
    manifest = json.loads((tmp_path / 'ws' / 'outputs' / 'draft_manifest.json').read_bytes())
    assert manifest['total_briefs'] == oracle['total_briefs']
    # Drafts live in the workspace-local mock site, keyed idempotently.
    site = tmp_path / 'ws' / 'mock_site' / 'drafts'
    assert site.is_dir()
    assert len(list(site.iterdir())) == oracle['total_briefs']


def test_draft_reconcile_is_idempotent_no_duplicates(tmp_path):
    """Crash after drafts written, before commit: re-running the compute node
    reuses the same idempotent keys instead of duplicating drafts."""
    oracle = generate_drafts(tmp_path / 'fx', briefs=6, seed=4)
    workspace = tmp_path / 'ws'

    class Crash(BaseException):
        pass

    def kill(current, _):
        if current == 'aggregate_saved':
            raise Crash()

    with pytest.raises(Crash):
        Runtime().run(default_drafts_plan(), tmp_path / 'fx' / 'inputs', workspace, oracle,
                      phase_hook=kill)
    record = Runtime().resume(workspace, tmp_path / 'fx' / 'inputs', oracle)
    assert record['status'] == 'SUCCEEDED'
    site = workspace / 'mock_site' / 'drafts'
    # Each idempotent key produced exactly one draft -- no duplicates created.
    assert len(list(site.iterdir())) == oracle['total_briefs']


def test_drafts_rejects_wrong_oracle_and_inputs(tmp_path):
    oracle = generate_dedup(tmp_path / 'fx', files=8, duplicate_groups=2, seed=4)
    record = Runtime().run(default_drafts_plan(), tmp_path / 'fx' / 'inputs',
                           tmp_path / 'ws', oracle)
    assert record['status'] == 'FAILED'  # oracle schema mismatch fails closed


def test_drafts_via_gateway(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=2, rows=2, seed=3, drafts=True, drafts_count=6)
    gateway = AgentGateway(home)
    datasets = gateway.call('datasets_list', {})['data']['datasets']
    assert {d['dataset_id'] for d in datasets} == {'demo', 'drafts'}
    out = gateway.call('task_submit', {'dataset_id': 'drafts', 'request_id': 'w1',
                                       'plan': default_drafts_plan().model_dump()})
    assert out['ok'] and out['data']['status'] == 'SUCCEEDED'


def test_plan_spec_three_families():
    assert default_plan().nodes[1].operation == 'tabular.aggregate'
    assert default_drafts_plan().nodes[1].operation == 'drafts.mock_flow'
    bad = default_drafts_plan().model_dump()
    bad['nodes'][1]['operation'] = 'artifacts.export'
    with pytest.raises(Exception):
        PlanSpec.model_validate(bad)
