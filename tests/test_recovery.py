"""Process-crash regression tests. These deliberately kill actual child processes."""
from __future__ import annotations

import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from conftest import kill_process_tree

from agentos_runtime.contracts import default_plan
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.fixtures import generate
from agentos_runtime.journal import Journal
from agentos_runtime.locking import workspace_lock
from agentos_runtime.runtime import Policy, Runtime
from agentos_runtime.storage import digest


class Crash(BaseException):
    """Simulates exit without normal error handling; process-kill tests below are separate."""


def setup(tmp_path):
    root = tmp_path / 'fixture'
    oracle = generate(root, 3, 10, seed=19)
    return root, oracle, tmp_path / 'run'


def crash_run(tmp_path, phase='node_committed:export'):
    root, oracle, workspace = setup(tmp_path)
    def fail(current, _):
        if current == phase:
            raise Crash()
    with pytest.raises(Crash):
        Runtime().run(default_plan(), root / 'inputs', workspace, oracle, phase_hook=fail)
    return root, oracle, workspace


def event_counts(workspace):
    with closing(sqlite3.connect(workspace / 'journal.sqlite3')) as conn, conn:
        return dict(conn.execute('SELECT kind,COUNT(*) FROM events GROUP BY kind'))


def assert_recovered(root, oracle, workspace):
    result = Runtime().resume(workspace, root / 'inputs', oracle)
    assert result['status'] == 'SUCCEEDED'
    assert result['verification']['passed'] is True
    assert json.loads((workspace / 'outputs' / 'summary.json').read_text())['groups'] == oracle['groups']
    assert {p.name: digest(p.read_bytes()) for p in (root / 'inputs').iterdir()} == oracle['input_hashes']
    counts = event_counts(workspace)
    assert counts['operation_completed'] == 4
    assert counts['operation_intent'] == 4
    assert not (workspace / 'staging').exists()
    return result


PHASES = ['intent:snapshot', 'snapshot_file:part_0000.csv', 'node_committed:snapshot',
          'intent:aggregate', 'aggregate_saved', 'node_committed:aggregate', 'intent:export',
          'export_file:summary.json', 'export_file:summary.csv', 'node_committed:export',
          'intent:verify', 'publication_prepared', 'publication_renamed',
          'node_committed:verify', 'run_committed', 'record_written']


@pytest.mark.parametrize('phase', PHASES)
def test_recover_every_instrumented_boundary(tmp_path, phase):
    root, oracle, workspace = crash_run(tmp_path, phase)
    result = assert_recovered(root, oracle, workspace)
    if phase not in {'run_committed', 'record_written'}:
        assert result['attempt'] == 2
        assert result['recovery']['resumed'] is True


def test_completed_stages_not_reexecuted(tmp_path, monkeypatch):
    root, oracle, workspace = crash_run(tmp_path)
    # A crash after export must not rerun the deterministic aggregation.
    monkeypatch.setattr('agentos_runtime.runtime.aggregate', lambda *_: pytest.fail('aggregation was replayed'))
    result = assert_recovered(root, oracle, workspace)
    assert result['metrics']['reused_nodes'] == ['snapshot', 'aggregate', 'export']
    assert result['metrics']['executed_nodes'] == ['verify']


def test_publication_not_repeated(tmp_path, monkeypatch):
    root, oracle, workspace = crash_run(tmp_path, 'publication_renamed')
    before = {p.name: (p.stat().st_ino, p.stat().st_mtime_ns, digest(p.read_bytes())) for p in (workspace/'outputs').iterdir()}
    monkeypatch.setattr('agentos_runtime.runtime.os.rename', lambda *_: pytest.fail('publication repeated'))
    result = assert_recovered(root, oracle, workspace)
    after = {p.name: (p.stat().st_ino, p.stat().st_mtime_ns, digest(p.read_bytes())) for p in (workspace/'outputs').iterdir()}
    assert before == after
    assert result['metrics']['reconciled_nodes'] == ['verify']


def test_success_resume_idempotent(tmp_path):
    root, oracle, workspace = crash_run(tmp_path, 'run_committed')
    counts = event_counts(workspace)
    first = assert_recovered(root, oracle, workspace)
    second = assert_recovered(root, oracle, workspace)
    assert first == second
    assert event_counts(workspace) == counts
    assert json.loads((workspace/'run.json').read_text()) == first


@pytest.mark.parametrize('kind', ['changed', 'added', 'removed'])
def test_changed_inputs_block_before_resumption(tmp_path, kind):
    root, oracle, workspace = crash_run(tmp_path)
    if kind == 'changed': (root/'inputs/part_0000.csv').write_text('changed')
    elif kind == 'added': (root/'inputs/new.csv').write_text('new')
    else: (root/'inputs/part_0000.csv').unlink()
    old = event_counts(workspace)
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace, root/'inputs', oracle)
    assert exc.value.code == 'INPUT_CHANGED'
    assert event_counts(workspace) == old
    assert not (workspace/'outputs').exists()


@pytest.mark.parametrize('kind,code', [('plan','PLAN_CHANGED'), ('oracle','ORACLE_CHANGED'),
    ('engine','ENGINE_CHANGED'), ('input_binding','INPUT_BINDING_CHANGED')])
def test_changed_bindings_block(tmp_path, kind, code):
    root, oracle, workspace = crash_run(tmp_path)
    input_root = root / 'inputs'
    if kind == 'plan':
        plan = json.loads((workspace/'plan.json').read_text(encoding='utf-8')); plan['goal'] = 'changed'
        (workspace/'plan.json').write_text(json.dumps(plan), encoding='utf-8')
    elif kind == 'oracle': oracle['total_rows'] += 1
    elif kind == 'engine':
        with closing(sqlite3.connect(workspace/'journal.sqlite3')) as conn, conn:
            conn.execute("UPDATE metadata SET engine='different'")
    else:
        import shutil
        shutil.copytree(input_root, tmp_path/'other_inputs')
        input_root = tmp_path/'other_inputs'
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace, input_root, oracle)
    assert exc.value.code == code
    assert not (workspace/'outputs').exists()


@pytest.mark.parametrize('kind', ['deny', 'cancel'])
def test_resume_rechecks_current_policy(tmp_path, kind):
    root, oracle, workspace = crash_run(tmp_path)
    policy = Policy(allowed_operations=frozenset()) if kind == 'deny' else Policy(cancelled=True)
    old = event_counts(workspace)
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace, root/'inputs', oracle, policy=policy)
    assert exc.value.code == ('POLICY_DENIED' if kind == 'deny' else 'CANCELLED')
    assert event_counts(workspace) == old
    assert not (workspace/'outputs').exists()


@pytest.mark.parametrize('target,code', [('snapshots/part_0000.csv','SNAPSHOT_CHANGED'),
    ('input_manifest.json','CHECKPOINT_INVALID'), ('checkpoints/aggregate.json','CHECKPOINT_CHANGED'),
    ('staging/summary.json','ARTIFACT_CHANGED')])
def test_tampering_never_silently_repaired(tmp_path, target, code):
    root, oracle, workspace = crash_run(tmp_path)
    (workspace/target).write_text('{}')
    result = Runtime().resume(workspace, root/'inputs', oracle)
    assert result['status'] == 'FAILED'
    assert result['error_code'] == code
    assert not (workspace/'outputs').exists()
    assert (workspace/target).read_text() == '{}'


def test_missing_receipted_file_not_regenerated(tmp_path):
    root, oracle, workspace = crash_run(tmp_path)
    (workspace/'staging/summary.json').unlink()
    result = Runtime().resume(workspace, root/'inputs', oracle)
    assert result['error_code'] == 'ARTIFACT_MISSING'
    assert not (workspace/'staging/summary.json').exists()


def test_unknown_file_blocks_resume(tmp_path):
    root, oracle, workspace = crash_run(tmp_path, 'export_file:summary.json')
    (workspace/'staging/unexpected.txt').write_text('preserve')
    result = Runtime().resume(workspace, root/'inputs', oracle)
    assert result['error_code'] == 'UNEXPECTED_FILE'
    assert (workspace/'staging/unexpected.txt').read_text() == 'preserve'


def test_partial_file_is_blocked_not_overwritten(tmp_path):
    root, oracle, workspace = crash_run(tmp_path, 'export_file:summary.json')
    (workspace/'staging/summary.json').write_text('{')
    result = Runtime().resume(workspace, root/'inputs', oracle)
    assert result['error_code'] == 'ARTIFACT_CHANGED'
    assert (workspace/'staging/summary.json').read_text() == '{'


def test_outputs_without_prepared_receipt_blocked(tmp_path):
    root, oracle, workspace = crash_run(tmp_path)
    (workspace/'staging').rename(workspace/'outputs')
    result = Runtime().resume(workspace, root/'inputs', oracle)
    assert result['error_code'] == 'UNKNOWN_EFFECT'
    assert result['artifact_state'] == 'published_unconfirmed'


def test_both_staging_and_outputs_blocked(tmp_path):
    root, oracle, workspace = crash_run(tmp_path, 'publication_renamed')
    (workspace/'staging').mkdir()
    result = Runtime().resume(workspace, root/'inputs', oracle)
    assert result['error_code'] == 'PUBLICATION_CONFLICT'


def test_failed_run_not_retried(tmp_path):
    root, oracle, workspace = setup(tmp_path)
    oracle['total_rows'] += 1
    assert Runtime().run(default_plan(),root/'inputs',workspace,oracle)['status'] == 'FAILED'
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace,root/'inputs',oracle)
    assert exc.value.code == 'TERMINAL_RUN'


def test_recovery_attempts_bounded(tmp_path):
    root, oracle, workspace = crash_run(tmp_path)
    def stop(*_): raise Crash()
    for _ in range(3):
        with pytest.raises(Crash):
            Runtime().resume(workspace,root/'inputs',oracle,phase_hook=stop)
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace,root/'inputs',oracle)
    assert exc.value.code == 'RECOVERY_BUDGET'


def test_checkpoint_order_validated(tmp_path):
    root, oracle, workspace = crash_run(tmp_path)
    with closing(sqlite3.connect(workspace/'journal.sqlite3')) as conn, conn:
        conn.execute("DELETE FROM checkpoints WHERE node='snapshot'")
    result = Runtime().resume(workspace,root/'inputs',oracle)
    assert result['error_code'] == 'CHECKPOINT_ORDER'


def test_old_journal_refused(tmp_path):
    workspace=tmp_path/'old'; workspace.mkdir()
    with closing(sqlite3.connect(workspace/'journal.sqlite3')) as conn, conn:
        conn.execute('CREATE TABLE runs (id TEXT, status TEXT)')
    with pytest.raises(RuntimeFault) as exc:
        Journal(workspace/'journal.sqlite3', create=False)
    assert exc.value.code == 'JOURNAL_VERSION'


def test_cooperating_workers_cannot_overlap(tmp_path):
    root, oracle, workspace = crash_run(tmp_path)
    with workspace_lock(workspace):
        with pytest.raises(RuntimeFault) as exc:
            Runtime().resume(workspace,root/'inputs',oracle)
        assert exc.value.code == 'WORKSPACE_BUSY'
    assert_recovered(root,oracle,workspace)


@pytest.mark.parametrize('phase', ['snapshot_file:part_0000.csv', 'aggregate_saved', 'export_file:summary.json',
    'node_committed:export', 'publication_prepared', 'publication_renamed', 'node_committed:verify', 'run_committed'])
def test_actual_kill_and_restart(tmp_path, phase):
    root, oracle, workspace = setup(tmp_path)
    marker=tmp_path/'ready'
    code='''
import json,sys,time
from pathlib import Path
from agentos_runtime.contracts import default_plan
from agentos_runtime.runtime import Runtime
root,work,marker=map(Path,sys.argv[1:4]); target=sys.argv[4]
def pause(phase,workspace):
    if phase == target:
        marker.write_text('ready')
        time.sleep(60)
Runtime().run(default_plan(),root/'inputs',work,json.loads((root/'oracle.json').read_text()),phase_hook=pause)
'''
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    process=subprocess.Popen([sys.executable,'-c',code,str(root),str(workspace),str(marker),phase],env=env)
    try:
        deadline=time.monotonic()+8
        while not marker.exists() and time.monotonic()<deadline:
            if process.poll() is not None: pytest.fail('worker exited before selected boundary')
            time.sleep(.02)
        assert marker.exists()
        # A live worker may not be mistaken for an abandoned one.
        with pytest.raises(RuntimeFault) as exc:
            Runtime().resume(workspace,root/'inputs',oracle)
        assert exc.value.code == 'WORKSPACE_BUSY'
        kill_process_tree(process)
        assert_recovered(root,oracle,workspace)
    finally:
        kill_process_tree(process)


def test_cancel_before_publish_keeps_staging(tmp_path):
    root,oracle,workspace=setup(tmp_path)
    policy=Policy()
    def change(phase,_):
        if phase=='publication_prepared': policy.cancelled=True
    result=Runtime().run(default_plan(),root/'inputs',workspace,oracle,policy=policy,phase_hook=change)
    assert result['status']=='CANCELLED'
    assert (workspace/'staging').exists()
    assert not (workspace/'outputs').exists()


def test_changed_source_before_publish_blocks(tmp_path):
    root,oracle,workspace=setup(tmp_path)
    def change(phase,_):
        if phase=='publication_prepared': (root/'inputs/part_0000.csv').write_text('changed')
    result=Runtime().run(default_plan(),root/'inputs',workspace,oracle,phase_hook=change)
    assert result['error_code']=='INPUT_CHANGED'
    assert not (workspace/'outputs').exists()


def test_actual_two_competing_resume_processes(tmp_path):
    root, oracle, workspace=crash_run(tmp_path)
    marker=tmp_path/'resuming'
    code='''
import json,sys,time
from pathlib import Path
from agentos_runtime.runtime import Runtime
root,work,marker=map(Path,sys.argv[1:])
def pause(phase,_):
    if phase=='intent:verify':
        marker.write_text('ready'); time.sleep(60)
Runtime().resume(work,root/'inputs',json.loads((root/'oracle.json').read_text()),phase_hook=pause)
'''
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    proc=subprocess.Popen([sys.executable,'-c',code,str(root),str(workspace),str(marker)],env=env)
    try:
        deadline=time.monotonic()+8
        while not marker.exists() and time.monotonic()<deadline:
            if proc.poll() is not None: pytest.fail('resume process exited prematurely')
            time.sleep(.02)
        assert marker.exists()
        with pytest.raises(RuntimeFault) as exc:
            Runtime().resume(workspace,root/'inputs',oracle)
        assert exc.value.code=='WORKSPACE_BUSY'
        kill_process_tree(proc)
        assert_recovered(root,oracle,workspace)
    finally:
        kill_process_tree(proc)


def test_input_path_binding_is_explicit_even_for_identical_bytes(tmp_path):
    import shutil
    root,oracle,workspace=crash_run(tmp_path)
    shutil.copytree(root/'inputs',tmp_path/'copy')
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace,tmp_path/'copy',oracle)
    assert exc.value.code=='INPUT_BINDING_CHANGED'
