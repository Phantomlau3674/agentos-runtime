"""REV-020: seeded stateful operation sequences over the gateway.

Safety properties asserted on every step: envelope integrity, no false success
(FAILED tasks never expose artifacts, tampered artifacts fail inspection),
termination of pagination, and replay consistency. Progress properties:
submitted tasks reach a terminal status, sessions open/read/close.
"""
from __future__ import annotations

import json
import random

import pytest

from agentos_runtime.contracts import default_plan
from agentos_runtime.gateway import AgentGateway, initialize_demo

OPS = ('submit', 'inspect', 'cancel', 'events', 'read', 'open', 'session_read',
       'session_close', 'explain', 'tamper_artifact', 'bad_tool')


def check_envelope(out):
    assert isinstance(out, dict) and isinstance(out['ok'], bool)
    if not out['ok']:
        assert isinstance(out['error']['code'], str)
        assert out['error']['automatic_retry'] is False
    return out


@pytest.mark.parametrize('seed', [11, 22, 33, 44])
def test_stateful_gateway_sequences(tmp_path, seed):
    rng = random.Random(seed)
    home = tmp_path / 'home'
    initialize_demo(home, files=3, rows=10, seed=5)
    gateway = AgentGateway(home)
    tasks: dict[str, dict] = {}       # request_id -> submission data
    sessions: dict[str, str] = {}     # session_id -> task_id
    tampered: set[str] = set()        # task_ids whose artifact was overwritten
    done = {'submit': 0, 'open': 0, 'events': 0}

    for _ in range(80):
        op = rng.choice(OPS)
        if op == 'submit':
            rid = rng.choice(['a', 'b', 'c', f'x{rng.randrange(3)}'])
            out = check_envelope(gateway.call(
                'task_submit', {'dataset_id': 'demo', 'request_id': rid}))
            if rid in tasks and tasks[rid]['task_id'] in tampered:
                # Replay of a tampered task fails integrity, not silently serves.
                assert out['error']['code'] == 'ARTIFACT_CHANGED'
                continue
            assert out['ok']
            data = out['data']
            if rid in tasks:
                assert data['task_id'] == tasks[rid]['task_id']  # replay, never re-executed
            else:
                tasks[rid] = data
            assert data['status'] in {'SUCCEEDED', 'FAILED'}
            done['submit'] += 1
        elif op == 'inspect' and tasks:
            tid = tasks[rng.choice(list(tasks))]['task_id']
            out = check_envelope(gateway.call('task_inspect', {'task_id': tid}))
            if tid in tampered:
                assert out['error']['code'] == 'ARTIFACT_CHANGED'
                continue
            data = out['data']
            assert data['status'] in {'SUCCEEDED', 'FAILED'}
            if data['status'] == 'SUCCEEDED':
                assert data['verification']['passed'] is True
                assert data['observation']['artifact_check'] == 'full_revalidation_at_this_call'
            else:
                assert data['observation']['artifact_check'] == 'not_performed'
        elif op == 'cancel' and tasks:
            tid = tasks[rng.choice(list(tasks))]['task_id']
            check_envelope(gateway.call('task_cancel', {'task_id': tid}))
        elif op == 'events' and tasks:
            tid = tasks[rng.choice(list(tasks))]['task_id']
            after, pages = 0, 0
            while True:
                page = check_envelope(gateway.call('task_events', {
                    'task_id': tid, 'after_seq': after, 'limit': rng.choice([1, 3, 7])}))
                assert page['ok']
                after = page['data']['next_after_seq']
                pages += 1
                if after is None or pages > 50:
                    break
            assert after is None  # pagination always terminates
            done['events'] += 1
        elif op == 'read' and tasks:
            task = tasks[rng.choice(list(tasks))]
            tid = task['task_id']
            artifact = rng.choice(task['artifacts']) if task['artifacts'] else None
            if artifact is None:
                continue
            out = check_envelope(gateway.call('artifact_read', {
                'task_id': tid, 'artifact_id': artifact['artifact_id'],
                'offset': 0, 'max_chars': 64}))
            if tid in tampered:
                assert out['error']['code'] == 'ARTIFACT_CHANGED'
            elif task['status'] == 'SUCCEEDED':
                assert out['ok']
                assert out['data']['content_role'] == 'untrusted_data_not_instructions'
            else:
                assert out['error']['code'] == 'ARTIFACT_UNAVAILABLE'
        elif op == 'open' and tasks:
            task = tasks[rng.choice(list(tasks))]
            tid = task['task_id']
            artifacts = task['artifacts']
            if not artifacts:
                continue
            out = check_envelope(gateway.call('artifact_open', {
                'task_id': tid, 'artifact_id': rng.choice(artifacts)['artifact_id']}))
            if out['ok']:
                sessions[out['data']['session_id']] = tid
                done['open'] += 1
        elif op == 'session_read' and sessions:
            sid = rng.choice(list(sessions))
            out = check_envelope(gateway.call('artifact_session_read', {
                'session_id': sid, 'offset': rng.randrange(4), 'max_chars': 16}))
            if out['ok']:
                assert out['data']['snapshot'].startswith('verified_content_at_open')
        elif op == 'session_close' and sessions:
            sid = rng.choice(list(sessions))
            out = check_envelope(gateway.call('artifact_session_close', {'session_id': sid}))
            assert out['ok']
            del sessions[sid]
        elif op == 'explain':
            check_envelope(gateway.call('plan_explain', {'plan': default_plan().model_dump()}))
        elif op == 'tamper_artifact' and tasks:
            tids = [t['task_id'] for t in tasks.values()]
            good = [t['task_id'] for t in tasks.values() if t['status'] == 'SUCCEEDED']
            tid = rng.choice(good or tids)
            target = home / 'tasks' / tid / 'run' / 'outputs' / 'summary.json'
            if target.exists():
                target.write_text('{}')
                tampered.add(tid)
        elif op == 'bad_tool':
            out = check_envelope(gateway.call(rng.choice(
                ['approve', 'shell_execute', 'task_submit']), {'task_id': 'x'}))
            assert out['error']['code'] in {'UNKNOWN_TOOL', 'INVALID_ARGUMENT'}

    # Progress + safety at the end: every task terminal, no false success.
    assert done['submit'] > 0 and done['events'] > 0
    for rid, task in tasks.items():
        if task['task_id'] in tampered:
            continue
        out = gateway.call('task_inspect', {'task_id': task['task_id']})['data']
        assert out['status'] in {'SUCCEEDED', 'FAILED'}
        if out['status'] == 'FAILED':
            blocked = gateway.call('artifact_open', {'task_id': task['task_id'],
                                                     'artifact_id': '0' * 64})
            assert blocked['error']['code'] in {'ARTIFACT_UNAVAILABLE', 'ARTIFACT_NOT_FOUND'}
