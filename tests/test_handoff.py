"""REV-016: agent handoff and compatibility regression.

An external agent that receives only a task_id must be able to continue:
inspect status, page the event journal, read verified artifacts, and resume
interrupted work -- across processes, and over the real MCP stdio transport.
Scripted protocol tests, not a live-model integration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agentos_runtime.contracts import default_plan
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.fixtures import generate
from agentos_runtime.gateway import AgentGateway, initialize_demo
from agentos_runtime.runtime import Runtime

SRC = Path(__file__).resolve().parents[1] / 'src'


def cli(home: Path, call: dict) -> dict:
    env = dict(os.environ, PYTHONPATH=str(SRC))
    response = subprocess.run([sys.executable, '-m', 'agentos_runtime', 'tool',
                               '--home', str(home)],
                              input=json.dumps(call), capture_output=True, text=True,
                              encoding='utf-8', env=env, timeout=30)
    assert response.returncode in (0, 1), response.stderr
    return json.loads(response.stdout)


def test_cross_process_handoff_via_cli(tmp_path):
    """Process A delegates; process B continues from task_id + events only."""
    home = tmp_path / 'home'
    result = subprocess.run([sys.executable, '-m', 'agentos_runtime', 'init-demo',
                             '--home', str(home), '--files', '3'],
                            capture_output=True, text=True, encoding='utf-8',
                            env=dict(os.environ, PYTHONPATH=str(SRC)), timeout=30)
    assert result.returncode == 0, result.stderr
    submitted = cli(home, {'tool': 'task_submit',
                           'arguments': {'dataset_id': 'demo', 'request_id': 'handoff-1'}})
    assert submitted['ok']
    task_id = submitted['data']['task_id']

    # A fresh process: everything below is a different "agent" continuing work.
    inspected = cli(home, {'tool': 'task_inspect', 'arguments': {'task_id': task_id}})['data']
    assert inspected['status'] == 'SUCCEEDED'
    assert inspected['observation']['stale'] is False

    events, after = [], 0
    while True:
        page = cli(home, {'tool': 'task_events',
                          'arguments': {'task_id': task_id, 'after_seq': after, 'limit': 5}})['data']
        events.extend(page['events'])
        if page['next_after_seq'] is None:
            break
        after = page['next_after_seq']
    kinds = {e['kind'] for e in events}
    assert {'operation_intent', 'operation_completed'} <= kinds
    assert any(e['payload'].get('effect') for e in events if e['kind'] == 'operation_intent')

    artifact = next(a for a in inspected['artifacts'] if a['name'] == 'errors.json')
    opened = cli(home, {'tool': 'artifact_open',
                        'arguments': {'task_id': task_id,
                                      'artifact_id': artifact['artifact_id']}})
    # CLI calls are separate processes: sessions do not survive process exit.
    if opened['ok']:
        session = opened['data']
        offset, chunks = 0, []
        # Sessions are process-local; a fresh CLI process cannot see them.
        page = cli(home, {'tool': 'artifact_session_read',
                          'arguments': {'session_id': session['session_id'],
                                        'offset': 0, 'max_chars': 32}})
        assert page['error']['code'] == 'SESSION_NOT_FOUND'
    fallback = cli(home, {'tool': 'artifact_read',
                          'arguments': {'task_id': task_id,
                                        'artifact_id': artifact['artifact_id'],
                                        'max_chars': 8000}})
    assert fallback['ok'] and json.loads(fallback['data']['content'])


def test_handoff_resume_after_crash_with_fresh_runtime(tmp_path):
    """Interrupted work is resumed by a different runtime instance."""
    oracle = generate(tmp_path / 'fx', 3, 5, seed=4)
    workspace = tmp_path / 'ws'

    class Crash(BaseException):
        pass

    def kill(current, _):
        if current == 'export_file:summary.json':  # after intent, before commit
            raise Crash()

    with pytest.raises(Crash):
        Runtime().run(default_plan(), tmp_path / 'fx' / 'inputs', workspace, oracle,
                      phase_hook=kill)
    record = Runtime().resume(workspace, tmp_path / 'fx' / 'inputs', oracle)
    assert record['status'] == 'SUCCEEDED'
    assert record['metrics']['reconciled_nodes'] == ['export']
    assert record['recovery']['resumed'] is True


def test_mcp_session_tools_over_real_stdio(tmp_path):
    mcp = pytest.importorskip('mcp', reason='mcp optional extra not installed')
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    home = tmp_path / 'home'
    initialize_demo(home, files=3, rows=10)
    params = StdioServerParameters(
        command=sys.executable,
        args=['-m', 'agentos_runtime.mcp_server', '--home', str(home)],
        env={'PYTHONPATH': str(SRC)}, cwd=str(SRC.parent))

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                submit = await session.call_tool(
                    'task_submit', {'dataset_id': 'demo', 'request_id': 'mcp-sess'})
                data = json.loads(submit.content[0].text)['data']
                task_id = data['task_id']
                artifact = data['artifacts'][0]
                opened = await session.call_tool('artifact_open', {
                    'task_id': task_id, 'artifact_id': artifact['artifact_id']})
                session_data = json.loads(opened.content[0].text)['data']
                page = await session.call_tool('artifact_session_read', {
                    'session_id': session_data['session_id'], 'offset': 0, 'max_chars': 32})
                item = json.loads(page.content[0].text)['data']
                assert item['snapshot'].startswith('verified_content_at_open')
                closed = await session.call_tool('artifact_session_close', {
                    'session_id': session_data['session_id']})
                assert json.loads(closed.content[0].text)['data']['closed']
    anyio.run(scenario)
