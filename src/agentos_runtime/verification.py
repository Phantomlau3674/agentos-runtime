"""Independent comparison of persisted output, fixture expectation and input versions."""
from __future__ import annotations
import csv
import io
import json


UNCHECKED = ["physical_durability_on_this_filesystem",
             "semantic_correctness_beyond_fixture_oracle",
             "isolation_from_hostile_host_processes",
             "live_model_integration"]
SCOPE = "synthetic fixture only; oracle supplied by trusted test owner"


def verify_tabular(persisted: dict[str, bytes], oracle: dict,
                   initial_hashes: dict[str, str], final_hashes: dict[str, str]) -> dict:
    # Deliberately does not call the aggregation or CSV serialization implementation.
    summary = json.loads(persisted['summary.json'])
    errors = json.loads(persisted['errors.json'])
    csv_rows = list(csv.DictReader(io.StringIO(persisted['summary.csv'].decode("utf-8"))))
    expected_csv = [{k: str(v) for k, v in group.items()} for group in oracle["groups"]]
    keys = ("total_rows", "valid_rows", "error_rows", "error_counts", "groups")
    checks = {"fixture_input_match": initial_hashes == oracle["input_hashes"],
              "source_unchanged": initial_hashes == final_hashes,
              "summary_exact": all(summary.get(k) == oracle.get(k) for k in keys),
              "error_locations_exact": errors == oracle["errors"],
              "csv_exact": csv_rows == expected_csv,
              "row_conservation": summary["valid_rows"] + summary["error_rows"] == summary["total_rows"]}
    return {"validator": "fixture_integer_cents.v0.1", "passed": all(checks.values()),
            "checks": checks, "unchecked": UNCHECKED, "scope": SCOPE}


def verify_dedup(persisted: dict[str, bytes], oracle: dict,
                 initial_hashes: dict[str, str], final_hashes: dict[str, str]) -> dict:
    # Independent: recomputes the expected duplicate CSV straight from the oracle,
    # not by calling files_dedup.duplicates_csv.
    report = json.loads(persisted['dedup_report.json'])
    csv_rows = list(csv.DictReader(io.StringIO(persisted['duplicates.csv'].decode("utf-8"))))
    expected_csv = [{'sha256': g['sha256'], 'file': name}
                    for g in oracle["duplicate_groups"] for name in g['files']]
    checks = {"fixture_input_match": initial_hashes == oracle["input_hashes"],
              "source_unchanged": initial_hashes == final_hashes,
              "report_exact": all(report.get(k) == oracle.get(k) for k in
                                  ("total_files", "unique_contents", "duplicate_files",
                                   "duplicate_groups")),
              "csv_exact": csv_rows == expected_csv,
              "file_conservation": report["total_files"] == len(oracle["input_hashes"])}
    return {"validator": "fixture_dedup_manifest.v1", "passed": all(checks.values()),
            "checks": checks, "unchecked": UNCHECKED, "scope": SCOPE}


def verify_drafts(persisted: dict[str, bytes], oracle: dict,
                  initial_hashes: dict[str, str], final_hashes: dict[str, str]) -> dict:
    # Independent: rebuilds expected keys/CSV from oracle fields alone --
    # draft_key = sha256(title + ':' + body_sha256), no call into mock_drafts.
    import hashlib
    manifest = json.loads(persisted['draft_manifest.json'])
    csv_rows = list(csv.DictReader(io.StringIO(persisted['drafts.csv'].decode("utf-8"))))
    expected = oracle["expected_drafts"]
    keys_ok = all(d['draft_key'] == hashlib.sha256(
        f"{d['title']}:{d['body_sha256']}".encode()).hexdigest() for d in expected)
    expected_csv = [{'draft_key': d['draft_key'], 'title': d['title'],
                     'bytes': str(d['bytes'])} for d in sorted(expected, key=lambda x: x['title'])]
    got = [{k: d[k] for k in ('draft_key', 'title', 'body_sha256', 'bytes')}
           for d in manifest.get('drafts', [])]
    want = [{k: d[k] for k in ('draft_key', 'title', 'body_sha256', 'bytes')}
            for d in sorted(expected, key=lambda x: x['title'])]
    checks = {"fixture_input_match": initial_hashes == oracle["input_hashes"],
              "source_unchanged": initial_hashes == final_hashes,
              "oracle_keys_wellformed": keys_ok,
              "manifest_exact": manifest.get('total_briefs') == oracle['total_briefs']
              and got == want,
              "csv_exact": csv_rows == expected_csv}
    return {"validator": "fixture_drafts_mock.v1", "passed": all(checks.values()),
            "checks": checks, "unchecked": UNCHECKED, "scope": SCOPE}


VERIFIERS = {'tabular.aggregate': verify_tabular,
             'files.dedup_manifest': verify_dedup,
             'drafts.mock_flow': verify_drafts}
ORACLE_SCHEMAS = {'tabular.aggregate': 'aor.fixture-oracle.v0.1',
                  'files.dedup_manifest': 'aor.fixture-oracle-dedup.v0.1',
                  'drafts.mock_flow': 'aor.fixture-oracle-drafts.v0.1'}


def run_verifier(compute_operation: str, persisted: dict[str, bytes], oracle: dict,
                 initial_hashes: dict[str, str], final_hashes: dict[str, str]) -> dict:
    return VERIFIERS[compute_operation](persisted, oracle, initial_hashes, final_hashes)
