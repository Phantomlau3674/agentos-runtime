"""REV-004: version-bound artifact read sessions, separated from inspect."""
from __future__ import annotations

import json

import pytest

from instrument import ReadLog

from agentos_runtime.contracts import default_plan
from agentos_runtime.gateway import AgentGateway, initialize_demo


def setup(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=4, rows=10, seed=5)
    return home, AgentGateway(home)


def submit(gateway, request_id='req-1'):
    out = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': request_id})
    assert out['ok'], out
    return out['data']


def open_errors(gateway, task):
    artifact = next(a for a in task['artifacts'] if a['name'] == 'errors.json')
    out = gateway.call('artifact_open', {'task_id': task['task_id'],
                                         'artifact_id': artifact['artifact_id']})
    assert out['ok'], out
    return artifact['artifact_id'], out['data']


def read_all(gateway, session_id, max_chars=64):
    offset, chunks = 0, []
    while True:
        out = gateway.call('artifact_session_read',
                           {'session_id': session_id, 'offset': offset, 'max_chars': max_chars})
        assert out['ok'], out
        page = out['data']
        chunks.append(page['content'])
        offset = page['next_offset']
        if offset is None:
            return ''.join(chunks), page


def test_session_pages_equal_one_shot_and_touch_disk_once(tmp_path):
    _, gateway = setup(tmp_path)
    task = submit(gateway)
    artifact = next(a for a in task['artifacts'] if a['name'] == 'errors.json')
    with ReadLog() as log:
        _, session = open_errors(gateway, task)
    # open verifies only the target artifact, not the whole manifest
    assert log.report()['read_bounded_total']['calls'] == 1
    with ReadLog() as log:
        text, _ = read_all(gateway, session['session_id'])
    assert log.report()['read_bounded_total']['calls'] == 0  # snapshot in memory
    one_shot = gateway.call('artifact_read', {'task_id': task['task_id'],
                                              'artifact_id': artifact['artifact_id'],
                                              'max_chars': 8000})
    assert one_shot['ok'] and one_shot['data']['content'].startswith(text[:100])
    assert session['total_chars'] == one_shot['data']['total_chars']
    parsed = json.loads(text)
    assert parsed and parsed[0]['code'] == 'INVALID_QUANTITY'  # errors.json parses


def test_session_close_and_unknown_ids(tmp_path):
    _, gateway = setup(tmp_path)
    task = submit(gateway)
    _, session = open_errors(gateway, task)
    out = gateway.call('artifact_session_close', {'session_id': session['session_id']})
    assert out['ok'] and out['data']['closed']
    for tool in ('artifact_session_read', 'artifact_session_close'):
        out = gateway.call(tool, {'session_id': session['session_id']})
        assert out['error']['code'] == 'SESSION_NOT_FOUND'
        out = gateway.call(tool, {'session_id': '0' * 32})
        assert out['error']['code'] == 'SESSION_NOT_FOUND'


def test_session_expiry(tmp_path):
    _, gateway = setup(tmp_path)
    gateway._session_ttl = -1.0  # already expired at creation
    task = submit(gateway)
    _, session = open_errors(gateway, task)
    out = gateway.call('artifact_session_read', {'session_id': session['session_id']})
    assert out['error']['code'] == 'SESSION_EXPIRED'


def test_session_budget(tmp_path):
    _, gateway = setup(tmp_path)
    task = submit(gateway)
    artifact = next(a for a in task['artifacts'] if a['name'] == 'errors.json')
    for _ in range(AgentGateway.MAX_SESSIONS):
        open_errors(gateway, task)
    out = gateway.call('artifact_open', {'task_id': task['task_id'],
                                         'artifact_id': artifact['artifact_id']})
    assert out['error']['code'] == 'SESSION_BUDGET'


def test_open_checks_target_version_not_siblings(tmp_path):
    home, gateway = setup(tmp_path)
    task = submit(gateway)
    # Corrupt a sibling artifact: open() verifies only the requested content
    # version. task_inspect still catches the tamper on its full sweep.
    sibling = home / 'tasks' / task['task_id'] / 'run' / 'outputs' / 'summary.json'
    sibling.write_text('{}')
    _, session = open_errors(gateway, task)
    text, _ = read_all(gateway, session['session_id'])
    assert json.loads(text)  # verified snapshot content still parses
    assert gateway.call('task_inspect', {'task_id': task['task_id']})['error']['code'] == 'ARTIFACT_CHANGED'


def test_open_rejects_changed_target(tmp_path):
    home, gateway = setup(tmp_path)
    task = submit(gateway)
    target = home / 'tasks' / task['task_id'] / 'run' / 'outputs' / 'errors.json'
    target.write_text('[]')
    out = gateway.call('artifact_open', {'task_id': task['task_id'],
                                         'artifact_id': '0' * 64})
    assert out['error']['code'] == 'ARTIFACT_NOT_FOUND'
    artifact = next(a for a in task['artifacts'] if a['name'] == 'errors.json')
    out = gateway.call('artifact_open', {'task_id': task['task_id'],
                                         'artifact_id': artifact['artifact_id']})
    assert out['error']['code'] == 'ARTIFACT_CHANGED'


def test_session_serves_snapshot_after_late_tamper(tmp_path):
    """Session semantics: fixed verified snapshot, not a live disk check."""
    home, gateway = setup(tmp_path)
    task = submit(gateway)
    _, session = open_errors(gateway, task)
    verified, _ = read_all(gateway, session['session_id'])
    (home / 'tasks' / task['task_id'] / 'run' / 'outputs' / 'errors.json').write_text('[]')
    out = gateway.call('artifact_session_read', {'session_id': session['session_id'],
                                                 'max_chars': 8000})
    assert out['ok'] and out['data']['snapshot'].startswith('verified_content_at_open')
    assert out['data']['content'] == verified[:8000]  # still the verified bytes


def test_open_requires_verified_task_and_owned_artifact(tmp_path):
    _, gateway = setup(tmp_path)
    plan = default_plan().model_dump()
    plan['limits']['max_rows'] = 1
    failed = gateway.call('task_submit', {'dataset_id': 'demo', 'request_id': 'short',
                                          'plan': plan})['data']
    assert failed['status'] == 'FAILED'
    out = gateway.call('artifact_open', {'task_id': failed['task_id'], 'artifact_id': '0' * 64})
    assert out['error']['code'] == 'ARTIFACT_UNAVAILABLE'
    a, b = submit(gateway, 'a'), submit(gateway, 'b')
    out = gateway.call('artifact_open', {'task_id': b['task_id'],
                                         'artifact_id': a['artifacts'][0]['artifact_id']})
    assert out['error']['code'] == 'ARTIFACT_NOT_FOUND'


def test_session_offset_range(tmp_path):
    _, gateway = setup(tmp_path)
    task = submit(gateway)
    _, session = open_errors(gateway, task)
    out = gateway.call('artifact_session_read', {'session_id': session['session_id'],
                                                 'offset': session['total_chars'] + 1})
    assert out['error']['code'] == 'OFFSET_RANGE'
