"""Independent comparison of persisted output, fixture expectation and input versions."""
from __future__ import annotations
import csv
import io
import json


def verify(summary_blob: bytes, errors_blob: bytes, csv_blob: bytes, oracle: dict,
           initial_hashes: dict[str, str], final_hashes: dict[str, str]) -> dict:
    # Deliberately does not call the aggregation or CSV serialization implementation.
    summary, errors = json.loads(summary_blob), json.loads(errors_blob)
    csv_rows = list(csv.DictReader(io.StringIO(csv_blob.decode("utf-8"))))
    expected_csv = [{k: str(v) for k, v in group.items()} for group in oracle["groups"]]
    keys = ("total_rows", "valid_rows", "error_rows", "error_counts", "groups")
    checks = {"fixture_input_match": initial_hashes == oracle["input_hashes"],
              "source_unchanged": initial_hashes == final_hashes,
              "summary_exact": all(summary.get(k) == oracle.get(k) for k in keys),
              "error_locations_exact": errors == oracle["errors"],
              "csv_exact": csv_rows == expected_csv,
              "row_conservation": summary["valid_rows"] + summary["error_rows"] == summary["total_rows"]}
    return {"validator": "fixture_integer_cents.v0.1", "passed": all(checks.values()), "checks": checks,
            "unchecked": ["physical_durability_on_this_filesystem",
                          "semantic_correctness_beyond_fixture_oracle",
                          "isolation_from_hostile_host_processes",
                          "live_model_integration"],
            "scope": "synthetic fixture only; oracle supplied by trusted test owner"}
