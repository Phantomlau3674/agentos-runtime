"""Tests for AgentOS offline synthetic demo app and HTML report generation."""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import urllib.request
import webbrowser

import pytest

from agentos_runtime.demo_app import (
    META_FILENAME,
    REPORT_FILENAME,
    STABLE_REQUEST_ID,
    main,
    render_html_report,
    run_demo,
)
from agentos_runtime.errors import RuntimeFault
from agentos_runtime.gateway import initialize_demo, AgentGateway


def test_first_execution(tmp_path: Path):
    """Owner-initialize a NEW synthetic demo if absent, submit, and verify HTML output."""
    home = tmp_path / "home"
    output = tmp_path / "demo_report"

    result = run_demo(home, output, files=3, rows=5, seed=7)

    assert result["status"] == "SUCCEEDED"
    assert result["verification_passed"] is True
    assert result["replayed_request"] is False
    assert result["total_rows"] == 15
    assert result["live_model_calls"] == 0

    report_file = output / REPORT_FILENAME
    meta_file = output / META_FILENAME

    assert report_file.exists()
    assert meta_file.exists()

    # Verify metadata contents
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta["request_id"] == STABLE_REQUEST_ID
    assert meta["task_id"] == result["task_id"]
    assert meta["dataset_id"] == "demo"
    assert meta["home"] == str(home.resolve())
    assert meta["report_file"] == REPORT_FILENAME

    # Verify HTML contents
    html_text = report_file.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_text
    assert "AgentOS 离线合成数据处理报告" in html_text
    assert "纯本地离线运行声明" in html_text
    assert "未调用任何在线大语言模型" in html_text
    assert "SUCCEEDED" in html_text
    assert "summary.json" in html_text
    assert "errors.json" in html_text
    assert "summary.csv" in html_text
    assert "verification.json" in html_text
    assert "币种 (Currency)" in html_text
    assert "品类 (Category)" in html_text


def test_repeat_execution_safely_reuses_registered_demo(tmp_path: Path):
    """Repeat execution safely reuses matching demo and request without re-executing."""
    home = tmp_path / "home"
    output = tmp_path / "demo_report"

    # First run
    res1 = run_demo(home, output, files=3, rows=5, seed=7)
    assert res1["replayed_request"] is False
    task_id = res1["task_id"]

    # Verify task count in SQLite registry is 1
    with closing(sqlite3.connect(home / "registry.sqlite3")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1

    # Second run (repeat)
    res2 = run_demo(home, output, files=3, rows=5, seed=7)
    assert res2["replayed_request"] is True
    assert res2["task_id"] == task_id
    assert res2["status"] == "SUCCEEDED"
    assert res2["verification_passed"] is True

    # Verify task count in registry remains 1 (no extra task created)
    with closing(sqlite3.connect(home / "registry.sqlite3")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1

    # Report file is intact
    assert (output / REPORT_FILENAME).exists()


def test_html_escaping_for_untrusted_strings(tmp_path: Path):
    """HTML escaping ensures untrusted data strings cannot inject markup."""
    synthetic_result = {
        "task_id": "task<script>123</script>",
        "dataset_id": "data&name",
        "dataset_version": "v1.0",
        "plan_hash": "hash<foo>",
        "status": "SUCCEEDED",
        "verification": {"passed": True},
        "artifacts": [{"name": "evil<img src=x>.json", "sha256": "1234567890abcdef", "bytes": 100, "artifact_id": "art<id>"}],
    }
    synthetic_summary = {
        "total_rows": 10,
        "valid_rows": 8,
        "error_rows": 2,
        "error_counts": {"<script>": 2},
        "groups": [
            {
                "currency": "<tag>USD</tag>",
                "category": "cat&dog",
                "rows": 5,
                "quantity": 10,
                "amount": "99.99",
            }
        ],
    }
    synthetic_errors = [
        {"file": "<evil>.csv", "row": 3, "code": "ERR<1>"}
    ]

    rendered = render_html_report(
        synthetic_result,
        synthetic_summary,
        synthetic_errors,
        home=tmp_path / "home",
        replayed=False,
    )

    # Raw script or img tags must NEVER appear in output
    assert "<script>123</script>" not in rendered
    assert "<img src=x>" not in rendered
    assert "<tag>USD</tag>" not in rendered
    assert "<evil>.csv" not in rendered

    # Escaped versions must appear
    assert "&lt;script&gt;123&lt;/script&gt;" in rendered
    assert "&lt;img src=x&gt;" in rendered
    assert "&lt;tag&gt;USD&lt;/tag&gt;" in rendered
    assert "&lt;evil&gt;.csv" in rendered
    assert "cat&amp;dog" in rendered


def test_html_escaping_comprehensive(tmp_path: Path):
    """Test render_html_report with row='<script>x</script>', error_counts value, and inputs as markup."""
    synthetic_result = {
        "task_id": "task<script>123</script>",
        "dataset_id": "data&name",
        "dataset_version": "v1.0<tag>",
        "plan_hash": "hash<foo>",
        "status": "SUCCEEDED",
        "verification": {"passed": True, "inputs": "<inputs_count>"},
        "artifacts": [{"name": "evil<img src=x>.json", "sha256": "1234567890abcdef", "bytes": "<bytes_val>", "artifact_id": "art<id>"}],
    }
    synthetic_summary = {
        "total_rows": "<total_rows_markup>",
        "valid_rows": "<valid_rows_markup>",
        "error_rows": "<error_rows_markup>",
        "error_counts": {"<code_key>": "<count_val_script>"},
        "groups": [
            {
                "currency": "<tag>USD</tag>",
                "category": "cat&dog",
                "rows": "<row_markup>",
                "quantity": "<qty_markup>",
                "amount": "<amt_markup>",
            }
        ],
    }
    synthetic_errors = [
        {"file": "<evil>.csv", "row": "<script>x</script>", "code": "ERR<1>"}
    ]

    rendered = render_html_report(
        synthetic_result,
        synthetic_summary,
        synthetic_errors,
        home=tmp_path / "home<dir>",
        replayed=False,
    )

    # Raw markup tags MUST NOT appear anywhere unescaped
    assert "<script>x</script>" not in rendered
    assert "<inputs_count>" not in rendered
    assert "<count_val_script>" not in rendered
    assert "<code_key>" not in rendered
    assert "<total_rows_markup>" not in rendered
    assert "<valid_rows_markup>" not in rendered
    assert "<error_rows_markup>" not in rendered
    assert "<bytes_val>" not in rendered

    # Escaped representations must be present
    assert "&lt;script&gt;x&lt;/script&gt;" in rendered
    assert "&lt;inputs_count&gt;" in rendered
    assert "&lt;count_val_script&gt;" in rendered
    assert "&lt;code_key&gt;" in rendered
    assert "&lt;total_rows_markup&gt;" in rendered
    assert "&lt;valid_rows_markup&gt;" in rendered
    assert "&lt;error_rows_markup&gt;" in rendered
    assert "&lt;bytes_val&gt;" in rendered


def test_conflict_refuses_overwrite_of_foreign_output(tmp_path: Path):
    """Existing output directories containing foreign user files must fail closed."""
    home = tmp_path / "home"
    output = tmp_path / "user_dir"
    output.mkdir(parents=True)
    user_file = output / "important_user_code.py"
    user_file.write_text("print('critical user work')", encoding="utf-8")

    with pytest.raises(RuntimeFault) as exc_info:
        run_demo(home, output, files=2, rows=5)

    assert exc_info.value.code == "OUTPUT_CONFLICT"
    # Ensure user file is completely untouched
    assert user_file.read_text(encoding="utf-8") == "print('critical user work')"


def test_conflict_foreign_index_html_without_meta(tmp_path: Path):
    """Output dir with only foreign index.html and no meta raises OUTPUT_CONFLICT, bytes unchanged."""
    home = tmp_path / "home"
    output = tmp_path / "out"
    output.mkdir(parents=True)
    foreign_html = output / REPORT_FILENAME
    foreign_content = "<html><body>Original User File</body></html>"
    foreign_html.write_text(foreign_content, encoding="utf-8")

    with pytest.raises(RuntimeFault) as exc_info:
        run_demo(home, output, files=2, rows=5)

    assert exc_info.value.code == "OUTPUT_CONFLICT"
    assert foreign_html.read_text(encoding="utf-8") == foreign_content
    assert not (output / META_FILENAME).exists()


def test_conflict_meta_home_mismatch(tmp_path: Path):
    """meta.dataset_id=demo but meta.home is another demo dir raises OUTPUT_CONFLICT, files unchanged."""
    home1 = tmp_path / "home1"
    home2 = tmp_path / "home2"
    out1 = tmp_path / "out1"

    # Run for home1
    run_demo(home1, out1, files=2, rows=5)
    meta_before = (out1 / META_FILENAME).read_text(encoding="utf-8")
    report_before = (out1 / REPORT_FILENAME).read_text(encoding="utf-8")

    # Now attempt to run with home2 pointing to out1
    with pytest.raises(RuntimeFault) as exc_info:
        run_demo(home2, out1, files=2, rows=5)

    assert exc_info.value.code == "OUTPUT_CONFLICT"
    assert (out1 / META_FILENAME).read_text(encoding="utf-8") == meta_before
    assert (out1 / REPORT_FILENAME).read_text(encoding="utf-8") == report_before


def test_conflict_refuses_mismatched_home(tmp_path: Path):
    """Existing directory that is not an initialized AgentOS demo home must fail closed."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(parents=True)
    (fake_home / "random.txt").write_text("not a demo", encoding="utf-8")
    output = tmp_path / "out"

    with pytest.raises(RuntimeFault) as exc_info:
        run_demo(fake_home, output, files=2, rows=5)

    assert exc_info.value.code == "MISMATCHED_HOME"


def test_conflict_overlapping_paths(tmp_path: Path):
    """Overlapping home and output paths must fail closed."""
    target = tmp_path / "shared"
    with pytest.raises(RuntimeFault) as exc_info:
        run_demo(target, target)
    assert exc_info.value.code == "OVERLAPPING_PATHS"

    parent = tmp_path / "parent"
    child = parent / "child"
    with pytest.raises(RuntimeFault) as exc_info:
        run_demo(parent, child)
    assert exc_info.value.code == "OVERLAPPING_PATHS"


def test_task_submit_failures_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Mock task_submit: FAILED; SUCCEEDED with passed=False; missing status/verification/artifacts."""
    artifact_reads: list[tuple] = []
    original_read = AgentGateway.artifact_read

    def spy_artifact_read(self, *args, **kwargs):
        artifact_reads.append(args)
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(AgentGateway, "artifact_read", spy_artifact_read)

    home = tmp_path / "home"
    initialize_demo(home, files=2, rows=5)

    # 1. Status is FAILED
    def mock_submit_failed(self, *args, **kwargs):
        return {"status": "FAILED", "task_id": "123", "verification": {"passed": False}, "artifacts": []}

    monkeypatch.setattr(AgentGateway, "task_submit", mock_submit_failed)
    out_fail = tmp_path / "out_fail"
    with pytest.raises(RuntimeFault) as exc_info:
        run_demo(home, out_fail)
    assert exc_info.value.code == "TASK_FAILED"
    assert not (out_fail / REPORT_FILENAME).exists()
    assert not (out_fail / META_FILENAME).exists()
    assert len(artifact_reads) == 0

    # 2. Status SUCCEEDED but verification.passed is False
    def mock_submit_passed_false(self, *args, **kwargs):
        return {"status": "SUCCEEDED", "task_id": "123", "verification": {"passed": False}, "artifacts": []}

    monkeypatch.setattr(AgentGateway, "task_submit", mock_submit_passed_false)
    out_not_passed = tmp_path / "out_not_passed"
    with pytest.raises(RuntimeFault) as exc_info:
        run_demo(home, out_not_passed)
    assert exc_info.value.code == "VERIFICATION_FAILED"
    assert not (out_not_passed / REPORT_FILENAME).exists()
    assert not (out_not_passed / META_FILENAME).exists()
    assert len(artifact_reads) == 0

    # 3. Missing status
    def mock_submit_missing_status(self, *args, **kwargs):
        return {"verification": {"passed": True}, "artifacts": []}

    monkeypatch.setattr(AgentGateway, "task_submit", mock_submit_missing_status)
    out_missing_status = tmp_path / "out_missing_status"
    with pytest.raises(RuntimeFault) as exc_info:
        run_demo(home, out_missing_status)
    assert exc_info.value.code == "TASK_FAILED"
    assert not (out_missing_status / REPORT_FILENAME).exists()
    assert not (out_missing_status / META_FILENAME).exists()
    assert len(artifact_reads) == 0

    # 4. Missing verification
    def mock_submit_missing_verif(self, *args, **kwargs):
        return {"status": "SUCCEEDED", "task_id": "123", "artifacts": []}

    monkeypatch.setattr(AgentGateway, "task_submit", mock_submit_missing_verif)
    out_missing_verif = tmp_path / "out_missing_verif"
    with pytest.raises(RuntimeFault) as exc_info:
        run_demo(home, out_missing_verif)
    assert exc_info.value.code == "VERIFICATION_FAILED"
    assert not (out_missing_verif / REPORT_FILENAME).exists()
    assert not (out_missing_verif / META_FILENAME).exists()
    assert len(artifact_reads) == 0

    # 5. Missing artifacts
    def mock_submit_missing_artifacts(self, *args, **kwargs):
        return {"status": "SUCCEEDED", "task_id": "123", "verification": {"passed": True}}

    monkeypatch.setattr(AgentGateway, "task_submit", mock_submit_missing_artifacts)
    out_missing_art = tmp_path / "out_missing_art"
    with pytest.raises(RuntimeFault) as exc_info:
        run_demo(home, out_missing_art)
    assert exc_info.value.code == "GATEWAY_FAULT"
    assert not (out_missing_art / REPORT_FILENAME).exists()
    assert not (out_missing_art / META_FILENAME).exists()
    assert len(artifact_reads) == 0


def test_no_unexpected_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Pure local execution must not attempt any socket or HTTP connection."""
    def forbidden_connect(*args, **kwargs):
        raise RuntimeError("Forbidden: offline demo attempted network connection!")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_connect)

    home = tmp_path / "home"
    output = tmp_path / "out"
    result = run_demo(home, output, files=2, rows=5)

    assert result["status"] == "SUCCEEDED"
    assert (output / REPORT_FILENAME).exists()


def test_cli_main_invocation(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Verify python -m agentos_runtime.demo_app CLI interface behavior."""
    home = tmp_path / "home"
    output = tmp_path / "out"

    # Normal success
    exit_code = main(["--home", str(home), "--output", str(output), "--files", "2", "--rows", "5"])
    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "SUCCEEDED"
    assert payload["verification_passed"] is True

    # Error case: foreign file in output
    foreign_dir = tmp_path / "foreign"
    foreign_dir.mkdir()
    (foreign_dir / "user.txt").write_text("data")
    err_exit_code = main(["--home", str(home), "--output", str(foreign_dir)])
    assert err_exit_code == 2
    err_captured = capsys.readouterr()
    assert "OUTPUT_CONFLICT" in err_captured.err


def test_open_browser_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--open calls webbrowser.open; default does not."""
    opened_urls: list[str] = []

    def mock_open(url: str):
        opened_urls.append(url)
        return True

    monkeypatch.setattr(webbrowser, "open", mock_open)

    home = tmp_path / "home"
    out1 = tmp_path / "out1"
    run_demo(home, out1, open_browser=False, files=2, rows=5)
    assert len(opened_urls) == 0

    out2 = tmp_path / "out2"
    run_demo(home, out2, open_browser=True, files=2, rows=5)
    assert len(opened_urls) == 1
    assert "file://" in opened_urls[0] or "index.html" in opened_urls[0]


def test_legacy_codepage_subprocess_chinese_output_path(tmp_path: Path):
    """Subprocess with PYTHONUTF8=0 and PYTHONIOENCODING=cp1252 must succeed with Chinese output path."""
    home = tmp_path / "home"
    output = tmp_path / "测试报告输出目录"

    env = dict(os.environ)
    env["PYTHONUTF8"] = "0"
    env["PYTHONIOENCODING"] = "cp1252"

    cmd = [
        sys.executable,
        "-m",
        "agentos_runtime.demo_app",
        "--home",
        str(home),
        "--output",
        str(output),
        "--files",
        "2",
        "--rows",
        "5",
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        env=env,
        timeout=30,
    )

    assert proc.returncode == 0, f"Process failed with code {proc.returncode}, stderr: {proc.stderr.decode('utf-8', errors='replace')}"

    # Require UTF-8 JSON, exit 0, SUCCEEDED
    stdout_text = proc.stdout.decode("utf-8")
    payload = json.loads(stdout_text)
    assert payload["status"] == "SUCCEEDED"
    assert payload["verification_passed"] is True
    assert (output / REPORT_FILENAME).exists()
    assert (output / META_FILENAME).exists()

