"""Differential benchmark for tabular kernel candidates (REV-002).

Two parts, both mandatory:

1. Equivalence corpus: every candidate must match the Decimal reference on
   every field, error and ordering -- including placeholder-ID reservation,
   leading zeros, file ordering and accumulation beyond int64.
2. Timing: same blob corpus, kernels interleaved in seeded random order,
   raw per-sample milliseconds saved. Local compute only; NOT a runtime,
   end-to-end or model-side claim, and historical numbers are not targets.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from time import perf_counter

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentos_runtime.errors import RuntimeFault  # noqa: E402
from agentos_runtime.tabular import aggregate  # noqa: E402

from kernels import aggregate_lazy, reference_decimal  # noqa: E402

HEADER = b"item_id,category,quantity,unit_price,currency\n"

# reference_decimal is the pre-REV-005 oracle; "adopted_int_cents" is the
# kernel now shipping in agentos_runtime.tabular.aggregate.
KERNELS = {"reference_decimal": reference_decimal,
           "adopted_int_cents": aggregate,
           "lazy_groups_decimal": aggregate_lazy}


def _csv(rows: list[list[str]], *, bom: bool = False) -> bytes:
    body = "".join(",".join(row) + "\n" for row in rows).encode("utf-8")
    return (b"\xef\xbb\xbf" if bom else b"") + HEADER + body


def _case(name: str, files: dict[str, bytes], max_rows: int = 100_000) -> dict:
    return {"name": name, "blobs": files, "max_rows": max_rows}


def equivalence_corpus() -> list[dict]:
    """Hand-built edge cases plus seeded random cases (>= 62 total)."""
    cases = [
        _case("minimal_valid", {"a.csv": _csv([["i1", "alpha", "1", "1.00", "CNY"]])}),
        _case("cross_file_duplicate", {
            "part_0001.csv": _csv([["item_x", "alpha", "2", "5.00", "CNY"]]),
            "part_0002.csv": _csv([["item_x", "beta", "2", "10.00", "CNY"]])}),
        _case("placeholder_reserves_id", {
            "a.csv": _csv([["item_p", "alpha", "1", "1.00", "BAD"]]),
            "b.csv": _csv([["item_p", "beta", "1", "2.00", "CNY"]])}),
        _case("leading_zeros", {"a.csv": _csv([["i1", "alpha", "0005", "007.50", "USD"]])}),
        _case("extreme_single_row_past_int64_cents",
              {"a.csv": _csv([["i1", "alpha", "1000000", "999999999.99", "CNY"]])}),
        _case("accumulation_past_int64_cents",
              {"a.csv": _csv([[f"i{n:03d}", "alpha", "1000000", "999999999.99", "CNY"]
                              for n in range(100)])}),
        _case("column_count_short", {"a.csv": _csv([["i1", "alpha", "1", "1.00"]])}),
        _case("column_count_long", {"a.csv": _csv([["i1", "alpha", "1", "1.00", "CNY", "x"]])}),
        _case("invalid_id_space", {"a.csv": _csv([["bad id", "alpha", "1", "1.00", "CNY"]])}),
        _case("invalid_category_empty", {"a.csv": _csv([["i1", "", "1", "1.00", "CNY"]])}),
        _case("quantity_zero", {"a.csv": _csv([["i1", "alpha", "0", "1.00", "CNY"]])}),
        _case("quantity_over_range", {"a.csv": _csv([["i1", "alpha", "1000001", "1.00", "CNY"]])}),
        _case("quantity_max_valid", {"a.csv": _csv([["i1", "alpha", "1000000", "1.00", "CNY"]])}),
        _case("price_three_decimals", {"a.csv": _csv([["i1", "alpha", "1", "1.234", "CNY"]])}),
        _case("price_ten_digits", {"a.csv": _csv([["i1", "alpha", "1", "1234567890.00", "CNY"]])}),
        _case("price_one_decimal", {"a.csv": _csv([["i1", "alpha", "3", "3.5", "EUR"]])}),
        _case("price_integer", {"a.csv": _csv([["i1", "alpha", "2", "12", "SGD"]])}),
        _case("invalid_currency", {"a.csv": _csv([["i1", "alpha", "1", "1.00", "XXX"]])}),
        _case("currency_lowercase", {"a.csv": _csv([["i1", "alpha", "1", "1.00", "cny"]])}),
        _case("header_only", {"a.csv": HEADER}),
        _case("file_ordering_errors_sorted", {
            "part_0010.csv": _csv([["i1", "", "1", "1.00", "CNY"]]),
            "part_0002.csv": _csv([["i2", "alpha", "0", "1.00", "CNY"]])}),
        _case("row_budget", {"a.csv": _csv([["i1", "alpha", "1", "1.00", "CNY"],
                                            ["i2", "alpha", "1", "1.00", "CNY"]])}, max_rows=1),
        _case("bad_header", {"a.csv": b"x,y,z\n1,2,3\n"}),
        _case("bad_utf8", {"a.csv": HEADER + b"i1,alpha,1,\xff\xfe,CNY\n"}),
        _case("bom_file", {"a.csv": _csv([["i1", "alpha", "1", "1.00", "CNY"]], bom=True)}),
        _case("empty_blobs", {}),
    ]
    rng = random.Random(20260911)
    error_rows = [
        lambda n: [f"r{n:02d}", "alpha", "0", "1.00", "CNY"],
        lambda n: [f"r{n:02d}", "alpha", "1", "1.00", "BAD"],
        lambda n: ["dup", "alpha", "1", "1.00", "CNY"],
        lambda n: [f"r{n:02d}", "", "1", "1.00", "CNY"],
        lambda n: [f"r{n:02d}", "alpha", "1", "oops", "CNY"],
    ]
    for index in range(36):
        files = {}
        for f in range(rng.randint(1, 3)):
            rows = []
            for n in range(rng.randint(0, 20)):
                if rng.random() < 0.3:
                    rows.append(rng.choice(error_rows)(n))
                else:
                    cents = rng.randint(1, 100_000)
                    rows.append([f"item_{index}_{f}_{n}", ("alpha", "beta", "gamma")[n % 3],
                                 str(rng.randint(1, 20)), f"{cents // 100}.{cents % 100:02d}",
                                 ("CNY", "USD", "EUR", "SGD")[n % 4]])
            files[f"rnd_{index}_{f}.csv"] = _csv(rows)
        cases.append(_case(f"random_{index}", files))
    return cases


def check_equivalence(cases: list[dict]) -> list[dict]:
    """Return one entry per case where any candidate diverges from the reference."""
    mismatches = []
    for case in cases:
        def outcome(fn):
            try:
                return {"ok": fn(case["blobs"], case["max_rows"])}
            except RuntimeFault as exc:
                return {"fault": exc.code}
        expected = outcome(reference_decimal)
        for name, fn in KERNELS.items():
            if name == "reference_decimal":
                continue
            actual = outcome(fn)
            if actual != expected:
                mismatches.append({"case": case["name"], "kernel": name,
                                   "expected": expected, "actual": actual})
    return mismatches


def build_timing_corpus(total_rows: int, files: int, seed: int) -> dict[str, bytes]:
    rng = random.Random(seed)
    blobs: dict[str, bytes] = {}
    serial = 0
    for f in range(files):
        count = total_rows // files + (1 if f < total_rows % files else 0)
        rows = []
        for _ in range(count):
            cents = rng.randint(1, 100_000)
            rows.append([f"item_{serial:07d}", ("alpha", "beta", "gamma")[serial % 3],
                         str(rng.randint(1, 20)), f"{cents // 100}.{cents % 100:02d}",
                         ("CNY", "USD", "EUR", "SGD")[serial % 4]])
            serial += 1
        blobs[f"bench_{f:04d}.csv"] = _csv(rows)
    return blobs


def run_benchmark(total_rows: int = 20_000, files: int = 200,
                  rounds: int = 7, seed: int = 7) -> dict:
    cases = equivalence_corpus()
    mismatches = check_equivalence(cases)
    corpus = build_timing_corpus(total_rows, files, seed)
    corpus_bytes = sum(len(b) for b in corpus.values())

    for fn in KERNELS.values():  # warmup: one full pass each, same order
        fn(corpus, 100_000)
    order_rng = random.Random(seed)
    samples: dict[str, list[float]] = {name: [] for name in KERNELS}
    for _ in range(rounds):
        order = list(KERNELS)
        order_rng.shuffle(order)
        for name in order:
            started = perf_counter()
            KERNELS[name](corpus, 100_000)
            samples[name].append((perf_counter() - started) * 1000)

    return {"schema_version": "aor.kernel-benchmark.v1",
            "config": {"total_rows": total_rows, "files": files, "rounds": rounds,
                       "seed": seed, "warmup_passes": 1, "corpus_bytes": corpus_bytes},
            "equivalence": {"cases": len(cases), "mismatches": mismatches},
            "timing_ms": {name: {"samples": [round(s, 4) for s in values],
                                 "median": round(statistics.median(values), 4),
                                 "min": round(min(values), 4), "max": round(max(values), 4)}
                          for name, values in samples.items()},
            "scope": ["local compute kernel only; logical timing on this machine",
                      "not a runtime, end-to-end or model-side claim",
                      "historical 59.89/55.61/39.22 ms are not thresholds to meet"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=20_000)
    parser.add_argument("--files", type=int, default=200)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    text = json.dumps(run_benchmark(args.rows, args.files, args.rounds, args.seed),
                      ensure_ascii=False, sort_keys=True, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
