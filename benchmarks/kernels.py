"""Kernel variants for the REV-002/REV-005 differential benchmark.

``agentos_runtime.tabular.aggregate`` is the ADOPTED integer-cents kernel.
``reference_decimal`` below is the pre-REV-005 Decimal implementation kept
verbatim as the differential-test oracle; ``aggregate_lazy`` is a candidate
that keeps Decimal accumulation but skips redundant group construction.
Candidates must match the reference byte-for-byte on the equivalence corpus.
"""
from __future__ import annotations

import csv
from collections import Counter
from decimal import Decimal, localcontext
import io

from agentos_runtime.errors import RuntimeFault
from agentos_runtime.tabular import CATEGORY, CURRENCIES, FIELDS, ID, PRICE, QUANTITY


def reference_decimal(blobs: dict[str, bytes], max_rows: int) -> dict:
    """The pre-REV-005 Decimal kernel, preserved as the equivalence oracle."""
    groups: dict[tuple[str, str], dict] = {}
    errors: list[dict] = []
    seen: set[str] = set()
    total = valid = 0
    for filename, data in sorted(blobs.items()):
        try:
            reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
            header = next(reader, None)
            if header != FIELDS:
                raise RuntimeFault("CSV_SCHEMA", "CSV 表头与合成任务契约不符。")
            for row_number, row in enumerate(reader, 2):
                total += 1
                if total > max_rows:
                    raise RuntimeFault("ROW_BUDGET", "输入行数超过预算。")
                code = None
                if len(row) != len(FIELDS):
                    code = "COLUMN_COUNT"
                else:
                    item, category, quantity, price, currency = row
                    if not ID.fullmatch(item):
                        code = "INVALID_ID"
                    elif item in seen:
                        code = "DUPLICATE_ID"
                    else:
                        # IDs are reserved by the first syntactically valid occurrence,
                        # including a row whose other fields are invalid.
                        seen.add(item)
                        if not CATEGORY.fullmatch(category):
                            code = "INVALID_CATEGORY"
                        elif not QUANTITY.fullmatch(quantity) or not 1 <= int(quantity) <= 1_000_000:
                            code = "INVALID_QUANTITY"
                        elif not PRICE.fullmatch(price):
                            code = "INVALID_PRICE"
                        elif currency not in CURRENCIES:
                            code = "INVALID_CURRENCY"
                if code:
                    errors.append({"file": filename, "row": row_number, "code": code})
                    continue
                key = (currency, category)
                group = groups.setdefault(key, {"currency": currency, "category": category,
                                                "rows": 0, "quantity": 0, "amount": Decimal(0)})
                q = int(quantity)
                with localcontext() as ctx:
                    ctx.prec = 40
                    group["amount"] += Decimal(price) * q
                group["quantity"] += q
                group["rows"] += 1
                valid += 1
        except (UnicodeDecodeError, csv.Error) as exc:
            raise RuntimeFault("CSV_PARSE", "CSV 编码或引号结构无效。") from exc
    result_groups = []
    for key in sorted(groups):
        group = dict(groups[key])
        group["amount"] = format(group["amount"], ".2f")
        result_groups.append(group)
    return {"total_rows": total, "valid_rows": valid, "error_rows": len(errors),
            "error_counts": dict(sorted(Counter(e["code"] for e in errors).items())),
            "groups": result_groups, "errors": errors}


def aggregate_lazy(blobs: dict[str, bytes], max_rows: int) -> dict:
    """Candidate: Decimal accumulation, default group built only when absent."""
    groups: dict[tuple[str, str], dict] = {}
    errors: list[dict] = []
    seen: set[str] = set()
    total = valid = 0
    for filename, data in sorted(blobs.items()):
        try:
            reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
            header = next(reader, None)
            if header != FIELDS:
                raise RuntimeFault("CSV_SCHEMA", "CSV 表头与合成任务契约不符。")
            for row_number, row in enumerate(reader, 2):
                total += 1
                if total > max_rows:
                    raise RuntimeFault("ROW_BUDGET", "输入行数超过预算。")
                code = None
                if len(row) != len(FIELDS):
                    code = "COLUMN_COUNT"
                else:
                    item, category, quantity, price, currency = row
                    if not ID.fullmatch(item):
                        code = "INVALID_ID"
                    elif item in seen:
                        code = "DUPLICATE_ID"
                    else:
                        seen.add(item)
                        if not CATEGORY.fullmatch(category):
                            code = "INVALID_CATEGORY"
                        elif not QUANTITY.fullmatch(quantity) or not 1 <= int(quantity) <= 1_000_000:
                            code = "INVALID_QUANTITY"
                        elif not PRICE.fullmatch(price):
                            code = "INVALID_PRICE"
                        elif currency not in CURRENCIES:
                            code = "INVALID_CURRENCY"
                if code:
                    errors.append({"file": filename, "row": row_number, "code": code})
                    continue
                key = (currency, category)
                group = groups.get(key)
                if group is None:
                    groups[key] = group = {"currency": currency, "category": category,
                                           "rows": 0, "quantity": 0, "amount": Decimal(0)}
                q = int(quantity)
                with localcontext() as ctx:
                    ctx.prec = 40
                    group["amount"] += Decimal(price) * q
                group["quantity"] += q
                group["rows"] += 1
                valid += 1
        except (UnicodeDecodeError, csv.Error) as exc:
            raise RuntimeFault("CSV_PARSE", "CSV 编码或引号结构无效。") from exc
    result_groups = []
    for key in sorted(groups):
        group = dict(groups[key])
        group["amount"] = format(group["amount"], ".2f")
        result_groups.append(group)
    return {"total_rows": total, "valid_rows": valid, "error_rows": len(errors),
            "error_counts": dict(sorted(Counter(e["code"] for e in errors).items())),
            "groups": result_groups, "errors": errors}
