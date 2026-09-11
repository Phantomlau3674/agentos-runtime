"""Trusted action registry: declared read/write sets and effect class.

Every managed action must appear here with an honest declaration of what it
reads, what it writes, and what effect class it can produce. Unregistered
operations are denied at the broker boundary. Declarations are constraints on
what the runtime may do -- they do not claim the runtime is sandboxed against
hostile host-process code.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import RuntimeFault


@dataclass(frozen=True, slots=True)
class ActionContract:
    operation: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    effect: str  # 'internal' | 'published_artifact' | 'attestation'
    summary: str


ACTION_CONTRACTS: dict[str, ActionContract] = {
    'inputs.snapshot': ActionContract(
        operation='inputs.snapshot',
        reads=('dataset://inputs/*',),
        writes=('workspace://snapshots/*', 'workspace://input_manifest.json'),
        effect='internal',
        summary='有界枚举输入并落只读快照与清单。'),
    'tabular.aggregate': ActionContract(
        operation='tabular.aggregate',
        reads=('workspace://snapshots/*',),
        writes=('workspace://checkpoints/aggregate.json',),
        effect='internal',
        summary='整数分聚合快照内容到检查点。'),
    'artifacts.export': ActionContract(
        operation='artifacts.export',
        reads=('workspace://checkpoints/aggregate.json',),
        writes=('workspace://staging/*', 'workspace://outputs/*'),
        effect='published_artifact',
        summary='把检查点发布为带清单的产物。'),
    'verification.fixture': ActionContract(
        operation='verification.fixture',
        reads=('workspace://outputs/*', 'oracle://', 'workspace://input_manifest.json'),
        writes=('workspace://outputs/verification.json', 'journal://record'),
        effect='attestation',
        summary='独立核验产物并出具核验报告。'),
}


def action_contract(operation: str) -> ActionContract:
    contract = ACTION_CONTRACTS.get(operation)
    if contract is None:
        raise RuntimeFault('ACTION_UNREGISTERED', '动作不在可信注册表内。')
    return contract
