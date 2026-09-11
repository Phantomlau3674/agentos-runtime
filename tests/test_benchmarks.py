"""Tests for the REV-001/REV-002 measurement harness.

These verify that the probes and candidate kernels behave correctly. They
assert structure and equivalence, never timing thresholds -- wall-clock
numbers from a local machine are exploratory, not gates.
"""
from __future__ import annotations

import json
import math

import counterexample_duplicate_id
import environment
import kernel_benchmark
import probe_logical_reads
import probe_plan_freeze
from kernels import aggregate_lazy, reference_decimal

from agentos_runtime.errors import RuntimeFault
from agentos_runtime.tabular import aggregate


def test_environment_capture_pins_baseline():
    record = environment.capture()
    assert record["schema_version"] == "aor.repro-env.v1"
    assert len(record["git"]["commit"]) == 40
    assert len(record["engine_fingerprint"]) == 64
    assert "runtime.py" in record["source_sha256"]
    assert record["dependencies"]["pydantic"] is not None


def test_duplicate_id_counterexample_diverges():
    result = counterexample_duplicate_id.run()
    single = result["single_pass"]
    merged = result["per_file_then_merge"]
    assert single["groups"] == [{"currency": "CNY", "category": "alpha", "rows": 1,
                                 "quantity": 2, "amount": "10.00"}]
    assert single["errors"] == [{"file": "part_0002.csv", "row": 2, "code": "DUPLICATE_ID"}]
    assert sum(float(g["amount"]) for g in merged["groups"]) == 30.00
    assert merged["errors"] == []
    assert result["divergence"]["duplicate_error_lost"] is True


def test_plan_freeze_probe_shows_shallow_freeze():
    result = probe_plan_freeze.run()
    assert result["frozen_blocks_attribute_assignment"] is True
    assert result["nested_list_mutation_succeeded"] is True
    assert result["plan_hash_changed"] is True
    assert result["revalidation_rejected"] is True
    assert result["preflight_rejected"] is True


def test_equivalence_corpus_has_no_mismatch():
    cases = kernel_benchmark.equivalence_corpus()
    assert len(cases) >= 62
    assert kernel_benchmark.check_equivalence(cases) == []


def test_equivalence_includes_accumulation_past_int64():
    cases = {c["name"]: c for c in kernel_benchmark.equivalence_corpus()}
    case = cases["accumulation_past_int64_cents"]
    result = aggregate(case["blobs"], case["max_rows"])
    whole, frac = result["groups"][0]["amount"].split(".")
    assert int(whole) * 100 + int(frac) > 2**63 - 1
    assert reference_decimal(case["blobs"], case["max_rows"]) == result
    assert aggregate_lazy(case["blobs"], case["max_rows"]) == result


def test_fault_cases_raise_same_code():
    cases = {c["name"]: c for c in kernel_benchmark.equivalence_corpus()}
    for name, code in (("row_budget", "ROW_BUDGET"), ("bad_header", "CSV_SCHEMA"),
                       ("bad_utf8", "CSV_PARSE")):
        for kernel in (aggregate, reference_decimal, aggregate_lazy):
            try:
                kernel(cases[name]["blobs"], cases[name]["max_rows"])
            except RuntimeFault as exc:
                assert exc.code == code
            else:
                raise AssertionError(f"{kernel.__name__} did not raise {code} on {name}")


def test_logical_reads_probe_counts_all_phases():
    result = probe_logical_reads.measure(files=5, rows=2, seed=7)
    run = result["phases"]["run"]
    assert run["status"] == "SUCCEEDED"
    # snapshot pass + per-node re-checks + final re-check: at least 4 full passes
    assert run["source_passes"]["calls"] >= 4
    assert all(d["files"] == 5 for d in run["source_passes"]["detail"])
    one_char = result["phases"]["artifact_read_one_char"]
    assert one_char["returned_chars"] == 1
    # verified manifest (4 artifacts) + target read: still >= 5 logical reads
    assert one_char["read_bounded_total"]["calls"] >= 5
    assert result["phases"]["task_inspect"]["read_bounded_total"]["calls"] >= 4


def test_benchmark_output_schema_and_seeded_samples():
    result = kernel_benchmark.run_benchmark(total_rows=400, files=4, rounds=2, seed=3)
    assert result["schema_version"] == "aor.kernel-benchmark.v1"
    assert result["config"]["seed"] == 3
    assert result["equivalence"]["mismatches"] == []
    for name, stats in result["timing_ms"].items():
        assert len(stats["samples"]) == 2
        assert all(isinstance(s, float) and not math.isnan(s) for s in stats["samples"])
        assert stats["min"] <= stats["median"] <= stats["max"]
    json.dumps(result)  # serialisable as committed evidence
