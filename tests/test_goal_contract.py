"""REV-009: goal contract + independent acceptance evidence."""
from __future__ import annotations

import pytest

from agentos_runtime.compiler import compile_plan
from agentos_runtime.contracts import GoalContract, PlanSpec, default_plan
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.fixtures import generate
from agentos_runtime.runtime import Runtime, engine_fingerprint
from agentos_runtime.storage import digest, json_bytes


def contract(**overrides) -> GoalContract:
    base = {"goal": "汇总合成 CSV 并独立验收", "invariants": ("inputs_read_only",),
            "unresolved": ("是否扩展第二任务族",), "human_judgment": ("金额异常是否需人工",)}
    return GoalContract(**(base | overrides))


def plan_with_contract(**overrides) -> PlanSpec:
    return PlanSpec(goal="汇总合成 CSV", nodes=default_plan().nodes,
                    goal_contract=contract(**overrides))


def test_plan_without_contract_keeps_stable_canonical_bytes():
    assert b"goal_contract" not in default_plan().canonical_bytes()
    with_contract = plan_with_contract()
    assert with_contract.plan_hash != default_plan().plan_hash
    assert compile_plan(with_contract).contract is not None
    assert compile_plan(default_plan()).contract is None


def test_contract_fields_are_tuples_after_wire_parse():
    parsed = PlanSpec.model_validate(plan_with_contract().model_dump())
    assert isinstance(parsed.goal_contract.invariants, tuple)
    assert isinstance(parsed.goal_contract.unresolved, tuple)


def test_contract_can_only_narrow_authorization(tmp_path):
    oracle = generate(tmp_path / "fx", 2, 2, seed=3)
    narrowed = plan_with_contract(allowed_operations=("inputs.snapshot",))
    with pytest.raises(RuntimeFault) as exc:
        Runtime().run(narrowed, tmp_path / "fx" / "inputs", tmp_path / "ws", oracle)
    assert exc.value.code == "CONTRACT_DENIED"


def test_acceptance_binds_verifier_version(tmp_path):
    oracle = generate(tmp_path / "fx", 2, 2, seed=3)
    bad = plan_with_contract(acceptance="unimplemented_verifier.v9")
    record = Runtime().run(bad, tmp_path / "fx" / "inputs", tmp_path / "ws", oracle)
    assert record["status"] == "FAILED"
    assert record["error_code"] == "ACCEPTANCE_MISMATCH"
    assert record["artifact_state"] == "not_delivered"


def test_successful_contract_binds_input_and_verifier(tmp_path):
    oracle = generate(tmp_path / "fx", 3, 5, seed=4)
    plan = plan_with_contract()
    workspace = tmp_path / "ws"
    record = Runtime().run(plan, tmp_path / "fx" / "inputs", workspace, oracle)
    assert record["status"] == "SUCCEEDED"
    acc = record["acceptance"]
    expected_contract = digest(plan.goal_contract.model_dump_json().encode())
    assert acc["contract_sha256"] == expected_contract
    assert acc["verifier_engine"] == engine_fingerprint()
    assert acc["validator"] == "fixture_integer_cents.v0.1"
    assert acc["input_version"] == digest(json_bytes(oracle["input_hashes"]))
    assert acc["unresolved"] == ["是否扩展第二任务族"]
    assert acc["human_judgment"] == ["金额异常是否需人工"]
    assert record["verification"]["unchecked"]


def test_wrong_result_never_delivered_even_if_tools_succeed(tmp_path):
    """A wrong oracle means the executed artifacts fail verification; the run
    still reports FAILED rather than letting tool-level success ship it."""
    oracle = generate(tmp_path / "fx", 3, 5, seed=4)
    corrupted = dict(oracle)
    corrupted["error_rows"] = oracle["error_rows"] + 1  # owner's claim diverges
    record = Runtime().run(default_plan(), tmp_path / "fx" / "inputs",
                           tmp_path / "ws", corrupted)
    assert record["status"] == "FAILED"
    assert record["error_code"] in {"ORACLE_MISMATCH", "VERIFICATION_FAILED"}
