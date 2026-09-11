"""Counterexample: per-file aggregate then merge loses cross-file duplicate IDs.

Rebuilds the historical counterexample for naive Map/Reduce over the tabular
kernel (REV-002): the real single-pass aggregation reports 10.00 CNY plus one
DUPLICATE_ID error; summing per-file partial results reports 30.00 CNY and no
error. This is a semantics proof, not a timing measurement.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentos_runtime.tabular import aggregate  # noqa: E402

HEADER = "item_id,category,quantity,unit_price,currency\n"
FILE_A = (HEADER + "item_x,alpha,2,5.00,CNY\n").encode("utf-8")
FILE_B = (HEADER + "item_x,beta,2,10.00,CNY\n").encode("utf-8")


def naive_per_file_merge(blobs: dict[str, bytes], max_rows: int) -> dict:
    """Wrong on purpose: aggregate each file alone, then add the groups."""
    groups: dict[tuple[str, str], dict] = {}
    total = valid = 0
    errors: list[dict] = []
    for name, data in sorted(blobs.items()):
        partial = aggregate({name: data}, max_rows)
        total += partial["total_rows"]
        valid += partial["valid_rows"]
        errors.extend(partial["errors"])
        for group in partial["groups"]:
            key = (group["currency"], group["category"])
            slot = groups.setdefault(key, {"currency": group["currency"],
                                           "category": group["category"],
                                           "rows": 0, "quantity": 0, "cents": 0})
            slot["rows"] += group["rows"]
            slot["quantity"] += group["quantity"]
            whole, frac = group["amount"].split(".")
            slot["cents"] += int(whole) * 100 + int(frac)
    return {"total_rows": total, "valid_rows": valid, "error_rows": len(errors),
            "groups": [{"currency": c, "category": k, "rows": v["rows"],
                        "quantity": v["quantity"],
                        "amount": f'{v["cents"] // 100}.{v["cents"] % 100:02d}'}
                       for (c, k), v in sorted(groups.items())],
            "errors": errors}


def run() -> dict:
    blobs = {"part_0001.csv": FILE_A, "part_0002.csv": FILE_B}
    whole = aggregate(blobs, 100_000)
    merged = naive_per_file_merge(blobs, 100_000)
    return {
        "schema_version": "aor.counterexample-duplicate-id.v1",
        "input_files": {"part_0001.csv": FILE_A.decode(), "part_0002.csv": FILE_B.decode()},
        "single_pass": {"groups": whole["groups"], "errors": whole["errors"]},
        "per_file_then_merge": {"groups": merged["groups"], "errors": merged["errors"]},
        "divergence": {
            "amount_cny": {"single_pass": "10.00", "per_file_then_merge": "30.00"},
            "duplicate_error_lost": merged["errors"] == [] and len(whole["errors"]) == 1,
        },
        "conclusion": "per-file partial results cannot be merged without a global "
                      "ID-arbitration rule; Map/Reduce over raw groups is unsafe",
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
