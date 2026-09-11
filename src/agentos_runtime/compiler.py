"""Trusted compile boundary: external wire PlanSpec -> immutable CompiledPlan.

The wire model stays a normal (validating, shallowly frozen) Pydantic model
at the API edge. Everything the executor iterates over is a recursively
immutable CompiledPlan built only here: canonical bytes and plan_hash are
computed after the frozen structure exists, never cached on the mutable
wire model.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .contracts import OPERATIONS, GoalContract, Limits, PlanSpec
from .errors import RuntimeFault


@dataclass(frozen=True, slots=True)
class CompiledNode:
    id: str
    operation: str
    depends_on: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompiledPlan:
    """Deeply immutable plan. Only compile_plan() may build a trusted one.

    Callers can still construct this type, but nothing downstream accepts a
    CompiledPlan from outside: the public runtime API takes the wire
    PlanSpec and compiles it internally on every entry (run and resume),
    so loading from another process always re-validates.
    """

    schema_version: str
    goal: str
    nodes: tuple[CompiledNode, ...]
    limits: Limits
    contract: GoalContract | None
    canonical_bytes: bytes
    plan_hash: str


def compile_plan(plan: PlanSpec) -> CompiledPlan:
    """Compile a caller-held wire plan: serialize once, then the canonical
    bytes path is the single validation boundary."""
    if not isinstance(plan, PlanSpec):
        raise RuntimeFault('PLAN_INVALID', '内部编译入口只接受受信 wire 计划类型。')
    return compile_canonical(plan.canonical_bytes())


def compile_canonical(data: bytes) -> CompiledPlan:
    """The single trusted boundary: canonical bytes -> immutable CompiledPlan.

    Parses exactly once. The stored bytes must already be canonical
    (sha256(canonical_bytes) == plan_hash by construction), so a hand-edited
    or differently-serialized document fails closed as PLAN_NONCANONICAL
    rather than silently re-normalizing.
    """
    detached = PlanSpec.model_validate_json(data)
    if detached.canonical_bytes() != data:
        raise RuntimeFault('PLAN_NONCANONICAL', '持久化计划不是规范化字节，拒绝沿用。')
    nodes = tuple(CompiledNode(id=node.id, operation=node.operation,
                               depends_on=tuple(node.depends_on))
                  for node in detached.nodes)
    # Defense in depth on the frozen structure: the wire validator owns these
    # rules today; the compiled form must keep holding them if the contract
    # ever grows beyond the fixed four-stage pipeline.
    if len(nodes) != len(OPERATIONS):
        raise RuntimeFault('PLAN_INVALID', '已编译计划的节点数不符合当前契约。')
    if len({node.id for node in nodes}) != len(nodes):
        raise RuntimeFault('PLAN_INVALID', '已编译计划存在重复节点标识。')
    ids = {node.id for node in nodes}
    for index, node in enumerate(nodes):
        if node.operation != OPERATIONS[index]:
            raise RuntimeFault('PLAN_INVALID', '已编译计划包含不支持的动作或顺序。')
        expected = () if index == 0 else (nodes[index - 1].id,)
        if node.depends_on != expected or any(dep not in ids for dep in node.depends_on):
            raise RuntimeFault('PLAN_INVALID', '已编译计划的依赖关系不合法。')
    canonical = detached.canonical_bytes()
    return CompiledPlan(schema_version=detached.schema_version, goal=detached.goal,
                        nodes=nodes, limits=detached.limits,
                        contract=detached.goal_contract,
                        canonical_bytes=canonical,
                        plan_hash=hashlib.sha256(canonical).hexdigest())
