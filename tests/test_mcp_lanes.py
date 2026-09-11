"""REV-007: separate bounded lanes for long executions vs short control calls."""
from __future__ import annotations

import threading
import time

import pytest

mcp = pytest.importorskip('mcp', reason='mcp optional extra not installed')

import anyio  # noqa: E402

from agentos_runtime.mcp_server import ToolLanes  # noqa: E402


def make_call(gate: threading.Event, record: list):
    def call(name, arguments):
        if name in ('task_submit', 'task_resume'):
            gate.wait(10)
            return {'ok': True, 'data': 'executed'}
        return {'ok': True, 'data': f'control:{name}'}
    record.append  # silence linters; record used by caller
    return call


def test_control_lane_stays_responsive_while_execution_saturated():
    gate, record = threading.Event(), []
    lanes = ToolLanes(make_call(gate, record), execution_slots=1, execution_queue=0,
                      control_slots=1, control_queue=0)
    results = {}

    async def main():
        async with anyio.create_task_group() as tg:
            async def run_exec():
                results['exec'] = await lanes.dispatch('task_submit', {})
            tg.start_soon(run_exec)
            await anyio.sleep(0.1)  # let the execution occupy its slot
            started = time.monotonic()
            results['ctrl'] = await lanes.dispatch('task_inspect', {})
            results['ctrl_seconds'] = time.monotonic() - started
            results['overflow'] = await lanes.dispatch('task_submit', {})
            gate.set()
    anyio.run(main)

    assert results['ctrl']['ok'] and results['ctrl']['data'] == 'control:task_inspect'
    assert results['ctrl_seconds'] < 5  # did not wait behind the execution
    assert results['overflow']['error']['code'] == 'QUEUE_FULL'
    assert results['overflow']['error']['automatic_retry'] is False
    assert results['exec']['data'] == 'executed'
    assert lanes._inflight == {'execution': 0, 'control': 0}


def test_queue_boundary_counts_queued_calls():
    gate, record = threading.Event(), []
    lanes = ToolLanes(make_call(gate, record), execution_slots=1, execution_queue=1,
                      control_slots=1, control_queue=0)
    results = []

    async def main():
        async with anyio.create_task_group() as tg:
            for _ in range(2):
                async def run():
                    results.append(await lanes.dispatch('task_submit', {}))
                tg.start_soon(run)
            await anyio.sleep(0.1)
            # slot + queue seat both taken -> third submission is rejected
            results.append(await lanes.dispatch('task_submit', {}))
            gate.set()
    anyio.run(main)

    codes = [r.get('error', {}).get('code') for r in results]
    assert codes.count('QUEUE_FULL') == 1
    assert sum(1 for r in results if r.get('ok')) == 2


def test_rpc_cancel_stops_waiting_but_business_state_untouched():
    gate, record = threading.Event(), []
    started = threading.Event()

    def call(name, arguments):
        started.set()
        gate.wait(10)
        record.append('worker_finished')
        return {'ok': True, 'data': 'executed'}

    lanes = ToolLanes(call, execution_slots=1, execution_queue=0,
                      control_slots=1, control_queue=0)
    outcome = {}

    async def main():
        async with anyio.create_task_group() as tg:
            async def run():
                outcome['dispatch'] = await lanes.dispatch('task_submit', {})
            tg.start_soon(run)
            for _ in range(200):
                if started.is_set():
                    break
                await anyio.sleep(0.01)
            tg.cancel_scope.cancel()  # RPC-level cancel while the worker runs
        outcome['cancelled'] = 'dispatch' not in outcome
        gate.set()
        for _ in range(200):
            if record:
                break
            await anyio.sleep(0.01)
    anyio.run(main)

    assert started.is_set()
    assert outcome['cancelled'] is True
    assert 'dispatch' not in outcome  # caller stopped waiting
    assert record == ['worker_finished']  # worker ran to completion anyway
    assert lanes._inflight['execution'] == 0  # counter released on cancel
