"""REV-003: wire PlanSpec -> immutable CompiledPlan boundary tests."""
from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest
from pydantic import ValidationError

from agentos_runtime.compiler import CompiledPlan, compile_canonical, compile_plan
from agentos_runtime.contracts import ActionSpec, OPERATIONS, PlanSpec, default_plan
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.fixtures import generate
from agentos_runtime.runtime import Policy, Runtime, _preflight


def test_compiled_plan_is_deeply_immutable():
    compiled = compile_plan(default_plan())
    assert isinstance(compiled.nodes, tuple)
    assert all(isinstance(n.depends_on, tuple) for n in compiled.nodes)
    with pytest.raises(dataclasses.FrozenInstanceError):
        compiled.nodes[0].operation = "inputs.snapshot"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        compiled.nodes.append(compiled.nodes[0])  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        compiled.limits.max_files = 1  # type: ignore[misc]


def test_caller_mutation_cannot_alias_into_compiled_plan():
    plan = default_plan()
    compiled = compile_plan(plan)
    original_hash = compiled.plan_hash
    plan.nodes.append(ActionSpec(id="extra", operation="inputs.snapshot",
                                 depends_on=[plan.nodes[-1].id]))
    assert len(compiled.nodes) == len(OPERATIONS)
    assert compiled.plan_hash == original_hash


def test_equivalent_wire_forms_compile_identically():
    a = compile_plan(default_plan())
    via_json = PlanSpec.model_validate_json(
        json.dumps({"goal": "汇总合成 CSV，保留原始输入，独立核验金额和异常。",
                    "nodes": [{"id": "snapshot", "operation": "inputs.snapshot"},
                              {"id": "aggregate", "operation": "tabular.aggregate",
                               "depends_on": ["snapshot"]},
                              {"id": "export", "operation": "artifacts.export",
                               "depends_on": ["aggregate"]},
                              {"id": "verify", "operation": "verification.fixture",
                               "depends_on": ["export"]}]}))
    b = compile_plan(via_json)
    assert b.canonical_bytes == a.canonical_bytes
    assert b.plan_hash == a.plan_hash
    assert b.plan_hash == hashlib.sha256(b.canonical_bytes).hexdigest()


def test_invalid_plans_rejected_at_wire_and_compile():
    with pytest.raises(ValidationError):
        PlanSpec(goal="x", nodes=[
            ActionSpec(id="a", operation="inputs.snapshot"),
            ActionSpec(id="b", operation="inputs.snapshot", depends_on=["a"]),
            ActionSpec(id="c", operation="artifacts.export", depends_on=["b"]),
            ActionSpec(id="d", operation="verification.fixture", depends_on=["c"])])
    mutated = default_plan()
    mutated.nodes[0] = ActionSpec(id="snapshot", operation="artifacts.export")
    with pytest.raises(ValidationError):
        compile_plan(mutated)
    with pytest.raises(RuntimeFault):
        compile_plan({"not": "a plan"})  # type: ignore[arg-type]


def test_run_and_resume_recompile_and_revalidate(tmp_path):
    root = tmp_path / "fixture"
    oracle = generate(root, 3, 5, seed=11)
    plan = default_plan()
    compiled = compile_plan(plan)
    workspace = tmp_path / "run"
    record = Runtime().run(plan, root / "inputs", workspace, oracle)
    assert record["status"] == "SUCCEEDED"
    assert (workspace / "plan.json").read_bytes() == compiled.canonical_bytes
    assert record["plan_hash"] == compiled.plan_hash
    again = Runtime().resume(workspace, root / "inputs", oracle)
    assert again["status"] == "SUCCEEDED" and again["plan_hash"] == compiled.plan_hash


def test_canonical_bytes_compile_path_agrees_with_wire_path():
    plan = default_plan()
    via_wire = compile_plan(plan)
    via_bytes = compile_canonical(plan.canonical_bytes())
    assert via_bytes.plan_hash == via_wire.plan_hash
    assert via_bytes.canonical_bytes == plan.canonical_bytes()


def test_noncanonical_persisted_plan_fails_closed():
    pretty = json.dumps(default_plan().model_dump(), indent=2, ensure_ascii=False).encode()
    with pytest.raises(RuntimeFault) as exc:
        compile_canonical(pretty)
    assert exc.value.code == "PLAN_NONCANONICAL"


def test_resume_rejects_reformatted_plan_json(tmp_path):
    oracle = generate(tmp_path / "fx", 2, 2, seed=3)
    workspace = tmp_path / "ws"
    Runtime().run(default_plan(), tmp_path / "fx" / "inputs", workspace, oracle)
    target = workspace / "plan.json"
    target.chmod(0o666)
    target.write_bytes(json.dumps(default_plan().model_dump(), indent=2).encode())
    with pytest.raises(RuntimeFault) as exc:
        Runtime().resume(workspace, tmp_path / "fx" / "inputs", oracle)
    assert exc.value.code == "PLAN_NONCANONICAL"


def test_preflight_checks_policy_on_compiled_nodes(tmp_path):
    plan = default_plan()
    (tmp_path / "in").mkdir()
    compiled, _, _ = _preflight(plan, tmp_path / "in", tmp_path / "ws", Policy())
    assert compiled.plan_hash == plan.plan_hash
    denied = Policy(allowed_operations=frozenset(OPERATIONS[:2]))
    with pytest.raises(RuntimeFault) as exc:
        _preflight(default_plan(), tmp_path / "in", tmp_path / "ws", denied)
    assert exc.value.code == "POLICY_DENIED"
