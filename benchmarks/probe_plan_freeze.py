"""Probe: PlanSpec is shallow-frozen, not deep-frozen (REV-002).

``frozen=True`` blocks attribute assignment but the ``nodes`` list itself
stays mutable. This probe demonstrates: append succeeds, ``plan_hash``
changes, and re-validation rejects the mutated plan. The runtime's existing
re-validation is what makes this a design smell, not a proven privilege
escalation -- which is exactly what the evidence record must say.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pydantic import ValidationError  # noqa: E402

from agentos_runtime.contracts import ActionSpec, PlanSpec, default_plan  # noqa: E402


def run() -> dict:
    plan = default_plan()
    hash_before = plan.plan_hash
    bytes_before = plan.canonical_bytes()

    assignment_blocked = False
    try:
        plan.nodes = []  # type: ignore[misc]
    except ValidationError:
        assignment_blocked = True

    plan.nodes.append(ActionSpec(id="extra", operation="inputs.snapshot",
                                 depends_on=[plan.nodes[-1].id]))
    mutation_succeeded = len(plan.nodes) == 5
    hash_after = plan.plan_hash

    revalidation_rejected = False
    revalidation_error = None
    try:
        PlanSpec.model_validate_json(plan.model_dump_json())
    except (ValidationError, ValueError) as exc:
        revalidation_rejected = True
        revalidation_error = exc.__class__.__name__

    preflight_rejected = False
    preflight_error = None
    with tempfile.TemporaryDirectory(prefix="aor-freeze-") as tmp:
        from agentos_runtime.runtime import Policy, _preflight
        try:
            _preflight(plan, Path(tmp) / "in", Path(tmp) / "ws", Policy())
        except (ValidationError, ValueError) as exc:
            preflight_rejected = True
            preflight_error = exc.__class__.__name__

    return {
        "schema_version": "aor.probe-plan-freeze.v1",
        "frozen_blocks_attribute_assignment": assignment_blocked,
        "nested_list_mutation_succeeded": mutation_succeeded,
        "plan_hash_before": hash_before,
        "plan_hash_after": hash_after,
        "plan_hash_changed": hash_before != hash_after,
        "canonical_bytes_changed": plan.canonical_bytes() != bytes_before,
        "revalidation_rejected": revalidation_rejected,
        "revalidation_error": revalidation_error,
        "preflight_rejected": preflight_rejected,
        "preflight_error": preflight_error,
        "conclusion": "PlanSpec is not deep-frozen; existing re-validation "
                      "rejects the mutated plan. Evidence for REV-003, not an "
                      "exploited authorization bypass.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    text = json.dumps(run(), ensure_ascii=False, sort_keys=True, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
