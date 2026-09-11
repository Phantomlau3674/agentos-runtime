"""Local synthetic demo application and HTML report generator for AgentOS.

Enables nontechnical Windows owners to launch, inspect, and verify the offline
synthetic CSV processing pipeline without network access or live model calls.
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any
import webbrowser

from .cli import _force_utf8_stdio
from .errors import RuntimeFault
from .gateway import AgentGateway, initialize_demo
from .storage import checked_path, json_bytes, read_bounded

STABLE_REQUEST_ID = "demo-local-owner-request"
META_FILENAME = ".demo_meta.json"
REPORT_FILENAME = "index.html"


def read_artifact_text(gateway: AgentGateway, task_id: str, artifact_id: str) -> str:
    """Read an entire text artifact via paginated gateway tool calls."""
    offset = 0
    chunks: list[str] = []
    while True:
        res = gateway.artifact_read(task_id, artifact_id, offset=offset, max_chars=8000)
        chunks.append(res["content"])
        offset = res["next_offset"]
        if offset is None:
            break
    return "".join(chunks)


def validate_and_prepare_paths(
    home_arg: Path,
    output_arg: Path,
    request_id: str = STABLE_REQUEST_ID,
    dataset_id: str = "demo",
) -> tuple[Path, Path, Path]:
    """Validate home and output paths, failing closed on mismatch or foreign files.

    Returns:
        tuple of (home_dir, output_dir, report_file)
    """
    home = checked_path(home_arg)
    output = checked_path(output_arg)

    if home == output or home in output.parents or output in home.parents:
        raise RuntimeFault("OVERLAPPING_PATHS", "home 目录与 output 路径不能相同或相互包含。")

    if output.suffix.lower() in {".html", ".htm"}:
        output_dir = output.parent
        report_file = output
    else:
        output_dir = output
        report_file = output / REPORT_FILENAME

    # Home validation
    if home.exists():
        if not home.is_dir():
            raise RuntimeFault("MISMATCHED_HOME", "指定的 home 是普通文件而非目录。")
        required_items = [
            home / "owner_policy.json",
            home / "datasets.json",
            home / "registry.sqlite3",
            home / "fixtures" / "demo" / "oracle.json",
        ]
        if any(not item.exists() for item in required_items):
            raise RuntimeFault(
                "MISMATCHED_HOME",
                "指定的 home 目录不是已初始化的匹配 AgentOS Demo 环境，拒绝覆盖或混用现有文件。",
            )

    # Output directory validation (fail closed against overwriting user files)
    if output.exists() and output.is_file() and output != report_file:
        raise RuntimeFault("OUTPUT_CONFLICT", "目标输出路径已作为非 HTML 文件存在，拒绝覆盖。")

    if output_dir.exists():
        if not output_dir.is_dir():
            raise RuntimeFault("OUTPUT_CONFLICT", "目标输出路径不是目录，拒绝覆盖。")
        existing_paths = list(output_dir.iterdir())
        if existing_paths:
            meta_file = output_dir / META_FILENAME
            if not meta_file.exists():
                raise RuntimeFault(
                    "OUTPUT_CONFLICT",
                    "目标输出目录已存在未由本工具元数据管理的文件，拒绝覆盖用户文件。",
                )
            allowed_names = {report_file.name, META_FILENAME}
            existing_names = {p.name for p in existing_paths}
            foreign_files = existing_names - allowed_names
            if foreign_files:
                sample = ", ".join(sorted(foreign_files)[:3])
                raise RuntimeFault(
                    "OUTPUT_CONFLICT",
                    f"目标输出目录中存在非 Demo 产物 ({sample})，已拒绝覆盖用户文件。",
                )
            try:
                meta = json.loads(read_bounded(meta_file, 65536))
            except Exception as exc:
                if isinstance(exc, RuntimeFault):
                    raise
                raise RuntimeFault("OUTPUT_CONFLICT", "无法读取输出目录元数据，拒绝覆盖。") from exc

            if not isinstance(meta, dict):
                raise RuntimeFault("OUTPUT_CONFLICT", "输出目录元数据格式无效，拒绝覆盖。")

            # Ownership binding checks: canonical home, request_id, dataset_id, report_file
            meta_home = meta.get("home")
            try:
                same_home = meta_home is not None and Path(meta_home).resolve() == home.resolve()
            except Exception:
                same_home = False

            if not same_home:
                raise RuntimeFault(
                    "OUTPUT_CONFLICT",
                    "目标输出目录归属于另一个 home 目录，拒绝采用或覆盖。",
                )
            if meta.get("request_id") != request_id:
                raise RuntimeFault(
                    "OUTPUT_CONFLICT",
                    "目标输出目录元数据 request_id 不匹配，拒绝采用或覆盖。",
                )
            if meta.get("dataset_id") != dataset_id:
                raise RuntimeFault(
                    "OUTPUT_CONFLICT",
                    "目标输出目录元数据 dataset_id 不匹配，拒绝采用或覆盖。",
                )
            if meta.get("report_file") != report_file.name:
                raise RuntimeFault(
                    "OUTPUT_CONFLICT",
                    "目标输出目录元数据 report_file 不匹配，拒绝采用或覆盖。",
                )

    return home, output_dir, report_file


def render_html_report(
    task_result: dict[str, Any],
    summary_data: dict[str, Any],
    errors_data: list[dict[str, Any]],
    home: Path,
    replayed: bool,
) -> str:
    """Generate self-contained Chinese HTML report without external asset fetches.

    Escapes all untrusted interpolated values to prevent HTML injection.
    """
    task_id = html.escape(str(task_result.get("task_id", "")))
    dataset_id = html.escape(str(task_result.get("dataset_id", "")))
    dataset_version = html.escape(str(task_result.get("dataset_version", "")))
    plan_hash = html.escape(str(task_result.get("plan_hash", "")))
    status = html.escape(str(task_result.get("status", "")))
    status_label = "执行成功 (SUCCEEDED)" if status == "SUCCEEDED" else status

    verification = task_result.get("verification", {})
    v_passed = verification.get("passed") is True
    v_oracle = verification.get("oracle_matches") is True
    v_input_hashes = verification.get("input_hashes_verified") is True
    v_final_hashes = verification.get("final_hashes_verified") is True
    v_artifacts = verification.get("artifacts_verified") is True
    input_file_count = html.escape(str(verification.get("inputs", 0)))

    total_rows = html.escape(str(summary_data.get("total_rows", 0)))
    valid_rows = html.escape(str(summary_data.get("valid_rows", 0)))
    error_rows = html.escape(str(summary_data.get("error_rows", 0)))
    error_counts = summary_data.get("error_counts", {})
    groups = summary_data.get("groups", [])
    artifacts = task_result.get("artifacts", [])

    replay_badge = '<span class="badge badge-info">复用已有执行结果</span>' if replayed else '<span class="badge badge-success">首次执行完成</span>'
    pass_badge = '<span class="badge badge-success">全部核验通过</span>' if v_passed else '<span class="badge badge-danger">核验未通过</span>'

    # Build group rows
    group_rows_html = []
    for g in groups:
        curr = html.escape(str(g.get("currency", "")))
        cat = html.escape(str(g.get("category", "")))
        r_count = html.escape(str(g.get("rows", 0)))
        qty = html.escape(str(g.get("quantity", 0)))
        amt = html.escape(str(g.get("amount", "0.00")))
        group_rows_html.append(
            f"<tr><td><strong>{curr}</strong></td><td>{cat}</td><td>{r_count}</td>"
            f"<td>{qty}</td><td class=\"text-right\">{amt}</td></tr>"
        )
    group_table_body = "".join(group_rows_html) if group_rows_html else "<tr><td colspan=\"5\">无分组数据</td></tr>"

    # Build error rows (limit preview to 50 items)
    error_rows_html = []
    for err in errors_data[:50]:
        f_name = html.escape(str(err.get("file", "")))
        row_num = html.escape(str(err.get("row", "")))
        code = html.escape(str(err.get("code", "")))
        error_rows_html.append(
            f"<tr><td>{f_name}</td><td>第 {row_num} 行</td><td><code>{code}</code></td></tr>"
        )
    error_table_body = "".join(error_rows_html) if error_rows_html else "<tr><td colspan=\"3\">无校验异常记录</td></tr>"
    total_err_count = html.escape(str(len(errors_data)))
    truncated_notice = f"<p class=\"hint\">仅展示前 50 条异常明细，共 {total_err_count} 条。</p>" if len(errors_data) > 50 else ""

    # Error code badges
    error_badges_html = []
    for c_code, count in error_counts.items():
        c_code_esc = html.escape(str(c_code))
        count_esc = html.escape(str(count))
        error_badges_html.append(f'<span class="badge badge-warning">{c_code_esc}: {count_esc}</span> ')
    error_summary_html = "".join(error_badges_html) if error_badges_html else '<span class="text-muted">无错误分类</span>'

    # Build artifact rows
    artifact_rows_html = []
    for art in artifacts:
        name = html.escape(str(art.get("name", "")))
        sha = html.escape(str(art.get("sha256", "")))
        size = html.escape(str(art.get("bytes", 0)))
        art_id = html.escape(str(art.get("artifact_id", "")))
        artifact_rows_html.append(
            f"<tr><td><strong>{name}</strong></td><td>{size} 字节</td>"
            f"<td><code class=\"mono\">{sha[:16]}...{sha[-8:]}</code></td>"
            f"<td><code class=\"mono\">{art_id[:16]}...</code></td></tr>"
        )
    artifact_table_body = "".join(artifact_rows_html) if artifact_rows_html else "<tr><td colspan=\"4\">无产物记录</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AgentOS 离线合成数据处理报告</title>
  <style>
    :root {{
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --text: #0f172a;
      --text-muted: #64748b;
      --border: #e2e8f0;
      --primary: #2563eb;
      --success: #16a34a;
      --warning: #d97706;
      --danger: #dc2626;
      --info: #0284c7;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", "PingFang SC", sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 24px;
    }}
    .container {{
      max-width: 1080px;
      margin: 0 auto;
    }}
    .header {{
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 2px solid var(--border);
    }}
    .header h1 {{
      font-size: 26px;
      font-weight: 700;
      color: #0f172a;
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .header .subtitle {{
      color: var(--text-muted);
      font-size: 14px;
      margin-top: 4px;
    }}
    .disclaimer-box {{
      background-color: #eff6ff;
      border: 1px solid #bfdbfe;
      border-left: 5px solid var(--primary);
      border-radius: 8px;
      padding: 14px 18px;
      margin-bottom: 24px;
      font-size: 14px;
      color: #1e3a8a;
    }}
    .disclaimer-box strong {{
      color: #1d4ed8;
    }}
    .grid-4 {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }}
    .card .label {{
      font-size: 13px;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .card .value {{
      font-size: 24px;
      font-weight: 700;
      margin-top: 6px;
      color: var(--text);
    }}
    .card .subvalue {{
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 4px;
    }}
    .badge {{
      display: inline-block;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 600;
      border-radius: 4px;
    }}
    .badge-success {{ background-color: #dcfce7; color: #15803d; }}
    .badge-info {{ background-color: #e0f2fe; color: #0369a1; }}
    .badge-warning {{ background-color: #fef3c7; color: #b45309; }}
    .badge-danger {{ background-color: #fee2e2; color: #b91c1c; }}
    section {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }}
    section h2 {{
      font-size: 18px;
      font-weight: 600;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 8px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
      margin-top: 8px;
    }}
    th, td {{
      padding: 10px 14px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    th {{
      background-color: #f1f5f9;
      color: var(--text-muted);
      font-weight: 600;
    }}
    tr:last-child td {{
      border-bottom: none;
    }}
    tr:hover td {{
      background-color: #f8fafc;
    }}
    .text-right {{ text-align: right; }}
    .mono {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      font-size: 12px;
    }}
    code {{
      background-color: #f1f5f9;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 12px;
      color: #334155;
    }}
    .meta-list {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 12px;
      font-size: 13px;
    }}
    .meta-item {{
      padding: 8px 12px;
      background: #f8fafc;
      border-radius: 6px;
      border: 1px solid #edf2f7;
    }}
    .meta-label {{
      color: var(--text-muted);
      margin-bottom: 2px;
    }}
    .meta-value {{
      font-weight: 600;
      word-break: break-all;
    }}
    .hint {{
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 10px;
    }}
    .footer {{
      text-align: center;
      font-size: 13px;
      color: var(--text-muted);
      margin-top: 32px;
      padding-top: 16px;
      border-top: 1px solid var(--border);
    }}
  </style>
</head>
<body>
  <div class="container">
    <header class="header">
      <h1>AgentOS 离线合成数据处理报告 {replay_badge}</h1>
      <div class="subtitle">Windows 本地确定性批处理与检查结果展示</div>
    </header>

    <div class="disclaimer-box">
      <strong>【纯本地离线运行声明】</strong>
      本报告由 AgentOS 确定性批处理运行时生成。本任务运行于受控本地空间，使用算法生成的合成测试数据。
      <strong>全程未调用任何在线大语言模型 (No Live LLM)、未发起任何网络请求、不依赖外部服务、不包含任何真实个人隐私或企业业务数据。</strong>
    </div>

    <div class="grid-4">
      <div class="card">
        <div class="label">任务状态</div>
        <div class="value">{status_label}</div>
        <div class="subvalue">{pass_badge}</div>
      </div>
      <div class="card">
        <div class="label">输入记录</div>
        <div class="value">{total_rows} <span style="font-size: 14px; font-weight: normal;">行</span></div>
        <div class="subvalue">分布于 {input_file_count} 个合成 CSV 文件</div>
      </div>
      <div class="card">
        <div class="label">有效记录</div>
        <div class="value" style="color: var(--success);">{valid_rows} <span style="font-size: 14px; font-weight: normal;">行</span></div>
        <div class="subvalue">符合格式规范并通过业务聚合</div>
      </div>
      <div class="card">
        <div class="label">校验异常</div>
        <div class="value" style="color: var(--warning);">{error_rows} <span style="font-size: 14px; font-weight: normal;">行</span></div>
        <div class="subvalue">{error_summary_html}</div>
      </div>
    </div>

    <section>
      <h2>源数据哈希与检查结果</h2>
      <div class="meta-list">
        <div class="meta-item">
          <div class="meta-label">标准答案对比 (Oracle Match)</div>
          <div class="meta-value">{"一致 (MATCHED)" if v_oracle else "不符 (MISMATCH)"}</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">输入源文件哈希校验</div>
          <div class="meta-value">{"全部校验通过 (VERIFIED)" if v_input_hashes else "校验失败"}</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">执行后输入一致性核验</div>
          <div class="meta-value">{"未被篡改 (UNTOUCHED)" if v_final_hashes else "已被篡改"}</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">生成产物完整性校验</div>
          <div class="meta-value">{"校验通过 (VALIDATED)" if v_artifacts else "校验失败"}</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">任务 ID (Task ID)</div>
          <div class="meta-value mono">{task_id}</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">数据集 ID 及版本哈希</div>
          <div class="meta-value mono">{dataset_id} ({dataset_version[:16]}...)</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">计划哈希 (Plan Hash)</div>
          <div class="meta-value mono">{plan_hash[:24]}...</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">本地数据根目录 (Home)</div>
          <div class="meta-value mono">{html.escape(str(home))}</div>
        </div>
      </div>
    </section>

    <section>
      <h2>汇总结果 (Grouped Totals)</h2>
      <table>
        <thead>
          <tr>
            <th>币种 (Currency)</th>
            <th>品类 (Category)</th>
            <th>记录行数 (Rows)</th>
            <th>数量汇总 (Quantity)</th>
            <th class="text-right">金额汇总 (Amount)</th>
          </tr>
        </thead>
        <tbody>
          {group_table_body}
        </tbody>
      </table>
    </section>

    <section>
      <h2>校验异常明细 (Validation Errors)</h2>
      <p style="margin-bottom: 8px; font-size: 13px; color: var(--text-muted);">
        在确定性数据处理中被安全过滤的异常记录：
      </p>
      <table>
        <thead>
          <tr>
            <th>来源文件 (File)</th>
            <th>位置 (Location)</th>
            <th>异常原因码 (Error Code)</th>
          </tr>
        </thead>
        <tbody>
          {error_table_body}
        </tbody>
      </table>
      {truncated_notice}
    </section>

    <section>
      <h2>任务交付物清单 (Artifacts)</h2>
      <table>
        <thead>
          <tr>
            <th>产物文件名</th>
            <th>文件大小</th>
            <th>SHA-256 哈希值</th>
            <th>不透明引用编号 (Artifact ID)</th>
          </tr>
        </thead>
        <tbody>
          {artifact_table_body}
        </tbody>
      </table>
    </section>

    <footer class="footer">
      <p>AgentOS 离线确定性运行时 · 纯本地 HTML 报告 · 无外部网络依赖</p>
    </footer>
  </div>
</body>
</html>
"""


def run_demo(
    home_path: Path,
    output_path: Path,
    open_browser: bool = False,
    files: int = 100,
    rows: int = 10,
    seed: int = 7,
) -> dict[str, Any]:
    """Execute or replay the local synthetic demo, generating a verified HTML report.

    Args:
        home_path: Path to runtime home directory. Initialized if absent.
        output_path: Path to output directory or HTML file.
        open_browser: Whether to open the generated report in default browser.
        files: Number of synthetic files for new demo.
        rows: Rows per synthetic file for new demo.
        seed: Random seed for deterministic generation.

    Returns:
        Structured result dict with status, task_id, and report file path.
    """
    home, output_dir, report_file = validate_and_prepare_paths(
        home_path, output_path, request_id=STABLE_REQUEST_ID, dataset_id="demo"
    )

    # 1. Initialize home if absent
    if not home.exists():
        initialize_demo(home, files=files, rows=rows, seed=seed)

    # 2. Connect gateway and submit task
    gateway = AgentGateway(home)
    submit_result = gateway.task_submit(dataset_id="demo", request_id=STABLE_REQUEST_ID)

    # 3. Strict verification of task result before reading artifacts or writing output
    if not isinstance(submit_result, dict):
        raise RuntimeFault("GATEWAY_FAULT", "任务提交结果格式无效。")

    status = submit_result.get("status")
    if status != "SUCCEEDED":
        raise RuntimeFault("TASK_FAILED", f"任务未成功执行 (状态: {status})。")

    verification = submit_result.get("verification")
    if not isinstance(verification, dict) or verification.get("passed") is not True:
        raise RuntimeFault("VERIFICATION_FAILED", "任务契约与不可变哈希核验未通过。")

    artifacts = submit_result.get("artifacts")
    if not isinstance(artifacts, list):
        raise RuntimeFault("GATEWAY_FAULT", "任务产物列表缺失或无效。")

    task_id = submit_result.get("task_id")
    if not task_id or not isinstance(task_id, str):
        raise RuntimeFault("GATEWAY_FAULT", "任务编号缺失或无效。")

    replayed = submit_result.get("replayed_request", False)

    # 4. Read artifacts (only after verification confirmed passed)
    summary_artifact = next(
        (a for a in artifacts if a.get("name") == "summary.json"), None
    )
    errors_artifact = next(
        (a for a in artifacts if a.get("name") == "errors.json"), None
    )

    if not summary_artifact:
        raise RuntimeFault("ARTIFACT_UNAVAILABLE", "必需的汇总产物 summary.json 缺失。")

    summary_raw = read_artifact_text(gateway, task_id, summary_artifact["artifact_id"])
    summary_data = json.loads(summary_raw)

    if errors_artifact:
        errors_raw = read_artifact_text(gateway, task_id, errors_artifact["artifact_id"])
        errors_data = json.loads(errors_raw)
    else:
        errors_data = []

    # 5. Generate HTML content
    html_content = render_html_report(submit_result, summary_data, errors_data, home, replayed)

    # 6. Write report and metadata atomically to output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file_bytes = html_content.encode("utf-8")

    meta_path = output_dir / META_FILENAME
    meta_payload = {
        "schema_version": "aor.demo-meta.v0.1",
        "request_id": STABLE_REQUEST_ID,
        "task_id": task_id,
        "dataset_id": "demo",
        "home": str(home.resolve()),
        "report_file": report_file.name,
    }

    temp_report = report_file.with_name(f".{report_file.name}.tmp")
    try:
        temp_report.write_bytes(report_file_bytes)
        temp_report.replace(report_file)
    except Exception:
        report_file.write_bytes(report_file_bytes)

    temp_meta = meta_path.with_name(f".{meta_path.name}.tmp")
    try:
        temp_meta.write_bytes(json_bytes(meta_payload))
        temp_meta.replace(meta_path)
    except Exception:
        meta_path.write_bytes(json_bytes(meta_payload))

    # 7. Optional browser open
    if open_browser:
        webbrowser.open(report_file.as_uri())

    return {
        "status": status,
        "task_id": task_id,
        "replayed_request": replayed,
        "report": str(report_file),
        "verification_passed": True,
        "total_rows": summary_data.get("total_rows", 0),
        "valid_rows": summary_data.get("valid_rows", 0),
        "error_rows": summary_data.get("error_rows", 0),
        "live_model_calls": 0,
    }


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="AgentOS 离线合成数据演示与自包含报告生成器（纯本地运行，不调用模型或网络）。"
    )
    parser.add_argument("--home", type=Path, required=True, help="AgentOS 运行时 home 目录")
    parser.add_argument("--output", type=Path, required=True, help="输出报告目录或 HTML 文件路径")
    parser.add_argument(
        "--open",
        action="store_true",
        default=False,
        help="完成后在默认浏览器中打开生成的 HTML 报告",
    )
    parser.add_argument("--files", type=int, default=100, help="新环境初始化合成 CSV 文件数（默认 100）")
    parser.add_argument("--rows", type=int, default=10, help="每个 CSV 文件行数（默认 10）")
    parser.add_argument("--seed", type=int, default=7, help="合成数据随机种子（默认 7）")

    args = parser.parse_args(argv)

    try:
        result = run_demo(
            home_path=args.home,
            output_path=args.output,
            open_browser=args.open,
            files=args.files,
            rows=args.rows,
            seed=args.seed,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if (result.get("status") == "SUCCEEDED" and result.get("verification_passed") is True) else 1
    except (RuntimeFault, OSError, ValueError, TypeError, sqlite3.Error) as exc:
        code = exc.code if isinstance(exc, RuntimeFault) else "CONFIG_OR_IO_ERROR"
        error_payload = {
            "status": "REJECTED",
            "error_code": code,
            "message": str(exc),
        }
        print(json.dumps(error_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
