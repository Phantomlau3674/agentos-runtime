"""A deliberately small executable contract, separate from the full design API."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Operation = Literal["inputs.snapshot", "tabular.aggregate", "artifacts.export", "verification.fixture"]
OPERATIONS = ("inputs.snapshot", "tabular.aggregate", "artifacts.export", "verification.fixture")


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


class PlanSpec(StrictModel):
    schema_version: Literal["aor.fixture-plan.v0.1"] = "aor.fixture-plan.v0.1"
    goal: Annotated[str, Field(min_length=1, max_length=1000)]
    nodes: list[ActionSpec] = Field(min_length=4, max_length=4)
    limits: Limits = Field(default_factory=Limits)

    @model_validator(mode="after")
    def validate_chain(self) -> PlanSpec:
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate node identifiers")
        # This spike supports exactly one ordered four-stage pipeline, not a generic DAG.
        if tuple(n.operation for n in self.nodes) != OPERATIONS:
            raise ValueError("unsupported operation sequence")
        for i, node in enumerate(self.nodes):
            expected = [] if i == 0 else [self.nodes[i - 1].id]
            if node.depends_on != expected:
                raise ValueError("each node must depend on the preceding node only")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")

    @property
    def plan_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def default_plan() -> PlanSpec:
    names = ("snapshot", "aggregate", "export", "verify")
    return PlanSpec(goal="汇总合成 CSV，保留原始输入，独立核验金额和异常。", nodes=[
        ActionSpec(id=name, operation=operation, depends_on=[] if i == 0 else [names[i - 1]])
        for i, (name, operation) in enumerate(zip(names, OPERATIONS))
    ])
