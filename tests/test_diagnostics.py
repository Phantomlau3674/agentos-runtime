from __future__ import annotations

import json
from contextlib import closing
import sqlite3

import pytest

from agentos_runtime.cli import main
from agentos_runtime.diagnostics import collect_diagnostics
from agentos_runtime.gateway import AgentGateway, initialize_demo


def setup(tmp_path):
    home=tmp_path/'private-home-marker'
    initialize_demo(home,files=2,rows=10)
    gateway=AgentGateway(home)
    task=gateway.call('task_submit',{'dataset_id':'demo','request_id':'request'})['data']['task_id']
    return home,task


def test_diagnostics_no_source_or_paths(tmp_path,monkeypatch):
    home,task=setup(tmp_path)
    monkeypatch.setenv('PRIVATE_API_KEY','NEVER_EXPORT_THIS_SECRET')
    with closing(sqlite3.connect(home/'tasks'/task/'run/journal.sqlite3')) as conn, conn:
        conn.execute("INSERT INTO events(run_id,at,kind,payload) VALUES ('x','now','secret_event','NEVER_EXPORT_THIS_SECRET')")
    diagnostic=collect_diagnostics(home,task)
    text=json.dumps(diagnostic)
    assert diagnostic['task']['status']=='SUCCEEDED'
    assert diagnostic['task']['verification_passed']
    assert diagnostic['event_counts']['other_event']==1
    assert str(home) not in text
    assert 'private-home-marker' not in text
    assert 'NEVER_EXPORT_THIS_SECRET' not in text
    assert 'secret_event' not in text
    assert 'unit_price' not in text


def test_tampered_output_produces_blocked_diagnostic(tmp_path):
    home,task=setup(tmp_path)
    (home/'tasks'/task/'run/outputs/errors.json').write_text('{}')
    diagnostic=collect_diagnostics(home,task)
    assert diagnostic['task']['status']=='INSPECTION_BLOCKED'
    assert diagnostic['task']['error_code']=='ARTIFACT_CHANGED'


def test_cli_export_new_diagnostic_file(tmp_path,capsys):
    home,task=setup(tmp_path)
    output=tmp_path/'diagnostic.json'
    assert main(['diagnose','--home',str(home),'--task',task,'--output',str(output)])==0
    assert json.loads(output.read_text())['schema_version']=='aor.diagnostics.v0.1'
    assert main(['diagnose','--home',str(home),'--task',task,'--output',str(output)])==2


def test_no_diagnostic_inside_live_workspace(tmp_path,capsys):
    home,task=setup(tmp_path)
    assert main(['diagnose','--home',str(home),'--task',task,'--output',str(home/'extra.json')])==2
    assert not (home/'extra.json').exists()


def test_diagnostic_unknown_task_not_created(tmp_path,capsys):
    home,_=setup(tmp_path)
    output=tmp_path/'diagnostic.json'
    assert main(['diagnose','--home',str(home),'--task','0'*32,'--output',str(output)])==2
    assert not output.exists()
