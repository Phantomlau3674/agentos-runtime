"""Synthetic benchmark fixtures; expected values computed in INTEGER cents.

The oracle is derived at generation time, not by calling the adapter under test.
It verifies this fixture family, not arbitrary documents or business data.
"""
from __future__ import annotations

import csv
from collections import Counter
import io
from pathlib import Path
import random

from .errors import RuntimeFault
from .storage import checked_path, digest, json_bytes, new_file


def generate(root: Path, files: int = 100, rows_per_file: int = 10, seed: int = 7) -> dict:
    if type(files) is not int or type(rows_per_file) is not int or not 1 <= files <= 1000 or not 1 <= rows_per_file <= 100:
        raise RuntimeFault("FIXTURE_SIZE", "合成任务只支持 1–1000 个文件，每文件 1–100 行。")
    root = checked_path(root)
    root.mkdir(parents=True, exist_ok=False)
    inputs = root / "inputs"
    inputs.mkdir()
    rng = random.Random(seed)
    sums: dict[tuple[str, str], dict] = {}
    errors, hashes = [], {}
    total = files * rows_per_file
    for file_index in range(files):
        filename = f"part_{file_index:04d}.csv"
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["item_id", "category", "quantity", "unit_price", "currency"])
        first_id = f"item_{file_index * rows_per_file:07d}"
        for offset in range(rows_per_file):
            serial = file_index * rows_per_file + offset
            item = f"item_{serial:07d}"
            category = ("alpha", "beta", "gamma")[serial % 3]
            currency = ("CNY", "USD", "EUR", "SGD")[serial % 4]
            qty, cents = rng.randint(1, 20), rng.randint(1, 100_000)
            row = [item, category, str(qty), f"{cents // 100}.{cents % 100:02d}", currency]
            code = None
            # Each ten-row block includes five distinct invalid-row cases.
            if offset % 10 == 5:
                row[2], code = "0", "INVALID_QUANTITY"
            elif offset % 10 == 6:
                row[4], code = "XXX", "INVALID_CURRENCY"
            elif offset % 10 == 7:
                row[0], code = first_id, "DUPLICATE_ID"
            elif offset % 10 == 8:
                row[3], code = "NaN", "INVALID_PRICE"
            elif offset % 10 == 9:
                row[1], code = "", "INVALID_CATEGORY"
            writer.writerow(row)
            if code:
                errors.append({"file": filename, "row": offset + 2, "code": code})
            else:
                group = sums.setdefault((currency, category), {"rows": 0, "quantity": 0, "cents": 0})
                group["rows"] += 1
                group["quantity"] += qty
                group["cents"] += qty * cents
        blob = buffer.getvalue().encode("utf-8")
        new_file(inputs / filename, blob)
        hashes[filename] = digest(blob)
    groups = [dict(currency=c, category=k, rows=v["rows"], quantity=v["quantity"],
                   amount=f'{v["cents"] // 100}.{v["cents"] % 100:02d}')
              for (c, k), v in sorted(sums.items())]
    oracle = {"fixture_schema": "aor.fixture-oracle.v0.1", "seed": seed, "input_hashes": hashes,
              "total_rows": total, "valid_rows": total-len(errors), "error_rows": len(errors),
              "error_counts": dict(sorted(Counter(e["code"] for e in errors).items())),
              "groups": groups, "errors": errors}
    new_file(root / "oracle.json", json_bytes(oracle))
    return oracle
