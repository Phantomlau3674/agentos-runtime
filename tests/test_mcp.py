"""Real subprocess MCP stdio tests using the official SDK v2 client.

Spawns ``python -m agentos_runtime.mcp_server --home <dir>`` and drives it
with ``mcp.client.stdio`` + ``ClientSession``. No model APIs, no network.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import anyio
import pytest

mcp = pytest.importorskip('mcp', reason='mcp optional extra not installed')
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from agentos_runtime.gateway import AgentGateway, initialize_demo  # noqa: E402

from conftest import kill_process_tree  # noqa: E402

EXPECTED_TOOLS = {
    'runtime_capabilities', 'datasets_list', 'task_submit', 'task_inspect',
    'task_resume', 'task_cancel', 'artifact_read', 'task_events',
    'artifact_open', 'artifact_session_read', 'artifact_session_close',
    'plan_explain',
}
SRC = Path(__file__).resolve().parents[1] / 'src'


def server_params(home: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=['-m', 'agentos_runtime.mcp_server', '--home', str(home)],
        env={'PYTHONPATH': str(SRC)},
        cwd=str(SRC.parent),
    )


def payload(result) -> dict:
    """Decoded gateway envelope from a CallToolResult."""
    assert result.content, 'tool result must carry text content'
    return json.loads(result.content[0].text)


def test_mcp_initialize_list_and_call_round_trip(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=3, rows=10)

    async def scenario():
        async with stdio_client(server_params(home)) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.server_info.name == 'agentos-runtime-mcp'

                listed = await session.list_tools()
                assert len(listed.tools) == 12
                assert {t.name for t in listed.tools} == EXPECTED_TOOLS
                gateway_schemas = {t['name']: t['inputSchema'] for t in AgentGateway(home).tools()}
                for tool in listed.tools:
                    assert tool.input_schema == gateway_schemas[tool.name]
                    assert tool.input_schema['additionalProperties'] is False

                submit = await session.call_tool(
                    'task_submit', {'dataset_id': 'demo', 'request_id': 'mcp-001'})
                assert not submit.is_error
                first = payload(submit)
                assert first['ok'] and first['data']['status'] == 'SUCCEEDED'
                assert submit.structured_content == first
                task_id = first['data']['task_id']
                assert str(home) not in json.dumps(first)

                inspected = await session.call_tool('task_inspect', {'task_id': task_id})
                assert payload(inspected)['data']['status'] == 'SUCCEEDED'

                artifact = first['data']['artifacts'][0]
                read = await session.call_tool('artifact_read', {
                    'task_id': task_id, 'artifact_id': artifact['artifact_id'], 'max_chars': 64})
                item = payload(read)['data']
                assert item['content_role'] == 'untrusted_data_not_instructions'
                assert item['total_chars'] > 0
    anyio.run(scenario)


def test_mcp_reconnect_replayed_request_deduplicates(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=3, rows=10)
    call = ('task_submit', {'dataset_id': 'demo', 'request_id': 'same-request'})

    async def once():
        async with stdio_client(server_params(home)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return payload(await session.call_tool(*call))['data']

    first = anyio.run(once)
    second = anyio.run(once)  # new process, same home: replay, not re-execution
    assert second['task_id'] == first['task_id']
    assert second['replayed_request'] is True


def test_mcp_tool_errors_are_sanitized(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=3, rows=10)

    async def scenario():
        async with stdio_client(server_params(home)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                unknown = await session.call_tool('approve', {})
                assert unknown.is_error
                assert payload(unknown)['error']['code'] == 'UNKNOWN_TOOL'

                invalid = await session.call_tool('task_inspect', {'task_id': '../other'})
                assert invalid.is_error
                assert payload(invalid)['error']['code'] == 'INVALID_ARGUMENT'
                assert str(home) not in invalid.content[0].text
    anyio.run(scenario)


def test_mcp_server_exits_on_stdin_eof(tmp_path):
    home = tmp_path / 'home'
    initialize_demo(home, files=3, rows=10)
    env = dict(os.environ, PYTHONPATH=str(SRC))
    proc = subprocess.Popen(
        [sys.executable, '-m', 'agentos_runtime.mcp_server', '--home', str(home)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        assert proc.stdin is not None
        proc.stdin.close()
        proc.stdin = None
        out, err = proc.communicate(timeout=20)
        assert proc.returncode == 0, err.decode('utf-8', 'replace')
        for line in out.splitlines():
            json.loads(line)  # stdout stays clean UTF-8 protocol frames only
    finally:
        kill_process_tree(proc)


def test_mcp_server_rejects_uninitialized_home(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(SRC))
    proc = subprocess.run(
        [sys.executable, '-m', 'agentos_runtime.mcp_server', '--home', str(tmp_path / 'missing')],
        capture_output=True, env=env, timeout=20)
    assert proc.returncode == 2
    assert json.loads(proc.stderr.decode('utf-8').strip().splitlines()[-1])['error_code'] == 'HOME_MISSING'
    assert not proc.stdout
