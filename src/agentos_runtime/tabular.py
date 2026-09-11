"""Deterministic batch adapter: exact two-decimal prices, integral quantities."""
from __future__ import annotations

import csv
from collections import Counter
from decimal import Decimal, localcontext
import io
import re

from .errors import RuntimeFault

FIELDS = ["item_id", "category", "quantity", "unit_price", "currency"]
ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CATEGORY = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
QUANTITY = re.compile(r"^[0-9]{1,7}$")
PRICE = re.compile(r"^[0-9]{1,9}(?:\.[0-9]{1,2})?$")
CURRENCIES = {"CNY", "USD", "EUR", "SGD"}


def aggregate(blobs: dict[str, bytes], max_rows: int) -> dict:
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


def summary_csv(groups: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["currency", "category", "rows", "quantity", "amount"],
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(groups)
    return output.getvalue().encode("utf-8")
