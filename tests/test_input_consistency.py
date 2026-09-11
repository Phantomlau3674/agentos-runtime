"""REV-008: input consistency contract -- snapshot semantics, defined behaviors."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentos_runtime.contracts import default_plan
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.fixtures import generate
from agentos_runtime.runtime import Runtime


def test_mutation_after_snapshot_fails_verification(tmp_path):
    """Source drift between snapshot and publish must fail, never deliver a
    result computed from bytes that no longer match the current source."""
    oracle = generate(tmp_path / 'fx', 3, 5, seed=4)
    source = tmp_path / 'fx' / 'inputs' / 'part_0000.csv'

    def tamper(current, _):
        if current == 'node_committed:snapshot':
            source.write_text(source.read_text() + '#drift\n')

    record = Runtime().run(default_plan(), tmp_path / 'fx' / 'inputs',
                           tmp_path / 'ws', oracle, phase_hook=tamper)
    assert record['status'] == 'FAILED'
    assert record['error_code'] == 'INPUT_CHANGED'
    assert record['artifact_state'] == 'not_delivered'


@pytest.mark.parametrize('kind,expected', [
    ('modified', 'INPUT_CHANGED'), ('deleted', 'INPUT_CHANGED'), ('added', 'INPUT_CHANGED'),
    ('dir_at_same_path', 'UNSUPPORTED_FILE'),  # same path replaced by a directory
])
def test_source_drift_blocks_resume(tmp_path, kind, expected):
    oracle = generate(tmp_path / 'fx', 3, 5, seed=4)
    inputs = tmp_path / 'fx' / 'inputs'
    workspace = tmp_path / 'ws'

    class Crash(BaseException):
        pass

    def kill(current, _):
        if current == 'aggregate_saved':
            raise Crash()

    with pytest.raises(Crash):
        Runtime().run(default_plan(), inputs, workspace, oracle, phase_hook=kill)

    if kind == 'modified':
        target = inputs / 'part_0000.csv'
        target.write_text(target.read_text() + 'x')
    elif kind == 'deleted':
        (inputs / 'part_0000.csv').unlink()
    elif kind == 'added':
        (inputs / 'part_extra.csv').write_text('item_id,category,quantity,unit_price,currency\n')
    else:
        (inputs / 'part_0000.csv').unlink()
        (inputs / 'part_0000.csv').mkdir()  # same path, now a directory

    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace, inputs, oracle)
    assert exc.value.code == expected


def test_snapshot_bytes_survive_source_removal(tmp_path):
    oracle = generate(tmp_path / 'fx', 2, 2, seed=3)
    inputs = tmp_path / 'fx' / 'inputs'
    workspace = tmp_path / 'ws'
    original = (inputs / 'part_0000.csv').read_bytes()
    Runtime().run(default_plan(), inputs, workspace, oracle)
    (inputs / 'part_0000.csv').unlink()
    snapshot = workspace / 'snapshots' / 'part_0000.csv'
    assert snapshot.read_bytes() == original
    # but recovery correctly refuses to continue on the changed input version
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace, inputs, oracle)
    assert exc.value.code == 'INPUT_CHANGED'
