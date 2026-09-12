"""A deliberately small executable contract, separate from the full design API."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

Operation = Literal["inputs.snapshot", "tabular.aggregate", "files.dedup_manifest",
                    "drafts.mock_flow", "artifacts.export", "verification.fixture"]
OPERATIONS = ("inputs.snapshot", "tabular.aggregate", "artifacts.export", "verification.fixture")
COMPUTE_OPERATIONS = ("tabular.aggregate", "files.dedup_manifest", "drafts.mock_flow")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Limits(StrictModel):
    max_files: Annotated[int, Field(ge=1, le=1000)] = 1000
    max_input_bytes: Annotated[int, Field(ge=1, le=16_777_216)] = 16_777_216
    max_rows: Annotated[int, Field(ge=1, le=100_000)] = 100_000
    max_artifact_bytes: Annotated[int, Field(ge=1, le=16_777_216)] = 16_777_216
    max_seconds: Annotated[int, Field(ge=1, le=300)] = 60


class ActionSpec(StrictModel):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    operation: Operation
    depends_on: list[str] = Field(default_factory=list, max_length=3)


def _as_tuple(value):
    """Wire JSON uses arrays; the validated contract stores immutable tuples."""
    return tuple(value) if isinstance(value, list) else value


class GoalContract(StrictModel):
    """Owner-declared success conditions attached to a plan (REV-009).

    Tuple fields keep the contract deeply immutable once validated. This is a
    declaration enforced at execution/publish boundaries -- not proof that the
    declared invariants are true.
    """

    schema_version: Literal["aor.goal-contract.v0.1"] = "aor.goal-contract.v0.1"
    goal: Annotated[str, Field(min_length=1, max_length=1000)]
    invariants: Annotated[tuple[str, ...], BeforeValidator(_as_tuple)] = ()
    # Narrows the owner policy for this plan only; never widens it.
    allowed_operations: Annotated[tuple[Operation, ...] | None, BeforeValidator(_as_tuple)] = None
    acceptance: Annotated[str, Field(min_length=1, max_length=64)] = "fixture_integer_cents.v0.1"
    unresolved: Annotated[tuple[str, ...], BeforeValidator(_as_tuple)] = ()
    human_judgment: Annotated[tuple[str, ...], BeforeValidator(_as_tuple)] = ()


class PlanSpec(StrictModel):
    schema_version: Literal["aor.fixture-plan.v0.1"] = "aor.fixture-plan.v0.1"
    goal: Annotated[str, Field(min_length=1, max_length=1000)]
    nodes: list[ActionSpec] = Field(min_length=4, max_length=4)
    limits: Limits = Field(default_factory=Limits)
    goal_contract: GoalContract | None = None

    @model_validator(mode="after")
    def validate_chain(self) -> PlanSpec:
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate node identifiers")
        # Fixed four-stage linear pipeline; only the compute stage varies by family.
        ops = tuple(n.operation for n in self.nodes)
        if ops[0] != "inputs.snapshot" or ops[1] not in COMPUTE_OPERATIONS \
                or ops[2] != "artifacts.export" or ops[3] != "verification.fixture":
            raise ValueError("unsupported operation sequence")
        for i, node in enumerate(self.nodes):
            expected = [] if i == 0 else [self.nodes[i - 1].id]
            if node.depends_on != expected:
                raise ValueError("each node must depend on the preceding node only")
        return self

    def canonical_bytes(self) -> bytes:
        # exclude_none keeps plans without a contract byte-identical to before
        # the field existed, so their plan_hash stays stable.
        return json.dumps(self.model_dump(exclude_none=True), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    @property
    def plan_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def default_plan() -> PlanSpec:
    names = ("snapshot", "aggregate", "export", "verify")
    return PlanSpec(goal="汇总合成 CSV，保留原始输入，独立核验金额和异常。", nodes=[
        ActionSpec(id=name, operation=operation, depends_on=[] if i == 0 else [names[i - 1]])
        for i, (name, operation) in enumerate(zip(names, OPERATIONS))
    ])


def default_dedup_plan() -> PlanSpec:
    """Second file family (ADP-006): content-hash manifest and duplicate groups."""
    names = ("snapshot", "dedup", "export", "verify")
    operations = ("inputs.snapshot", "files.dedup_manifest", "artifacts.export",
                  "verification.fixture")
    return PlanSpec(goal="合成文件清单与去重：按内容哈希分组定位重复副本，独立核验。", nodes=[
        ActionSpec(id=name, operation=operation, depends_on=[] if i == 0 else [names[i - 1]])
        for i, (name, operation) in enumerate(zip(names, operations))
    ])


def default_drafts_plan() -> PlanSpec:
    """Third family (ADP-005): mock draft fill/readback against a local site."""
    names = ("snapshot", "drafts", "export", "verify")
    operations = ("inputs.snapshot", "drafts.mock_flow", "artifacts.export",
                  "verification.fixture")
    return PlanSpec(goal="向本地模拟草稿站填写合成 brief、幂等回读并独立核验。", nodes=[
        ActionSpec(id=name, operation=operation, depends_on=[] if i == 0 else [names[i - 1]])
        for i, (name, operation) in enumerate(zip(names, operations))
    ])
