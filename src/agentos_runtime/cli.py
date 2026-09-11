from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import sqlite3
from time import perf_counter

from .contracts import PlanSpec, default_plan
from .errors import RuntimeFault
from .fixtures import generate
from .runtime import Runtime
from .storage import checked_path, json_bytes, new_file, read_bounded
from .tabular import aggregate, summary_csv
from .verification import verify


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentOS Runtime 离线合成任务验证；不调用模型或互联网。")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="在新目录生成合成数据并完成核验")
    demo.add_argument("--workspace", type=Path, required=True)
    demo.add_argument("--files", type=int, default=100)
    demo.add_argument("--rows", type=int, default=10)
    demo.add_argument("--seed", type=int, default=7)
    run = sub.add_parser("run", help="仅运行已生成的合成 fixture")
    run.add_argument("--fixture", type=Path, required=True)
    run.add_argument("--workspace", type=Path, required=True)
    run.add_argument("--plan", type=Path)
    baseline = sub.add_parser("baseline", help="相同批处理适配器的离线参考执行；不是 Agent 性能实验")
    baseline.add_argument("--fixture", type=Path, required=True)
    baseline.add_argument("--output", type=Path, required=True)
    sub.add_parser("schema", help="输出目前已实现的合成任务契约")
    resume = sub.add_parser("resume", help="明确请求核对并继续中断的合成任务")
    resume.add_argument("--fixture", type=Path, required=True)
    resume.add_argument("--workspace", type=Path, required=True)
    init = sub.add_parser("init-demo", help="所有者初始化合成任务空间；不是 Agent 工具")
    init.add_argument("--home", type=Path, required=True)
    init.add_argument("--files", type=int, default=100)
    init.add_argument("--rows", type=int, default=10)
    tools = sub.add_parser("tools", help="列出已实现的 Agent 工具及 JSON Schema")
    tools.add_argument("--home", type=Path, required=True)
    tool = sub.add_parser("tool", help="从标准输入读取一个工具请求并返回 JSON；不是 MCP 传输")
    tool.add_argument("--home", type=Path, required=True)
    diagnose = sub.add_parser("diagnose", help="所有者导出不含原文、路径或凭据的诊断")
    diagnose.add_argument("--home", type=Path, required=True)
    diagnose.add_argument("--task", required=True)
    diagnose.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "diagnose":
            from .diagnostics import collect_diagnostics
            result = collect_diagnostics(args.home, args.task)
            output = checked_path(args.output)
            home = checked_path(args.home)
            if output == home or home in output.parents:
                raise RuntimeFault("DIAGNOSTIC_DESTINATION", "诊断必须导出到任务空间之外。")
            new_file(output, json_bytes(result))
            print(json.dumps({"status": "EXPORTED", "schema_version": result["schema_version"]}, ensure_ascii=False))
            return 0
        if args.command in {"init-demo", "tools", "tool"}:
            from .gateway import AgentGateway, initialize_demo
            if args.command == "init-demo":
                result = initialize_demo(args.home, files=args.files, rows=args.rows)
            else:
                gateway = AgentGateway(args.home)
                if args.command == "tools":
                    result = {"tools": gateway.tools()}
                else:
                    raw = sys.stdin.buffer.read(65_537)
                    if len(raw) > 65_536:
                        raise RuntimeFault("REQUEST_BUDGET", "工具请求超过字节预算。")
                    request = json.loads(raw)
                    if not isinstance(request, dict) or set(request) != {"tool", "arguments"}:
                        raise RuntimeFault("INVALID_ARGUMENT", "请求必须只包含 tool 和 arguments。")
                    result = gateway.call(request["tool"], request["arguments"])
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result.get("ok") is False else 0
        if args.command == "resume":
            oracle = json.loads(read_bounded(args.fixture / "oracle.json", 16_777_216))
            record = Runtime().resume(args.workspace, args.fixture / "inputs", oracle)
            print(json.dumps(record, ensure_ascii=False, indent=2))
            return 0 if record["status"] == "SUCCEEDED" else 1
        if args.command == "schema":
            print(json.dumps(PlanSpec.model_json_schema(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "demo":
            root = checked_path(args.workspace)
            root.mkdir(parents=True, exist_ok=False)
            oracle = generate(root / "fixture", args.files, args.rows, args.seed)
            record = Runtime().run(default_plan(), root / "fixture" / "inputs", root / "run", oracle)
        elif args.command == "run":
            oracle = json.loads(read_bounded(args.fixture / "oracle.json", 16_777_216))
            plan = PlanSpec.model_validate_json(read_bounded(args.plan, 65536)) if args.plan else default_plan()
            record = Runtime().run(plan, args.fixture / "inputs", args.workspace, oracle)
        else:
            # This intentionally omits journaling/recovery. Strong agent baseline B is still pending.
            from .storage import digest, input_paths
            start = perf_counter()
            plan = default_plan()
            root = checked_path(args.output)
            if root == args.fixture or args.fixture.absolute() in root.parents or root in args.fixture.absolute().parents:
                raise RuntimeFault("WORKSPACE_OVERLAP", "输出必须与 fixture 目录分离。")
            remaining = plan.limits.max_input_bytes
            blobs = {}
            for path in input_paths(args.fixture / "inputs", plan.limits.max_files):
                blob = read_bounded(path, remaining)
                remaining -= len(blob)
                blobs[path.name] = blob
            hashes = {n: digest(b) for n, b in blobs.items()}
            oracle = json.loads(read_bounded(args.fixture / "oracle.json", 16_777_216))
            if hashes != oracle.get("input_hashes"):
                raise RuntimeFault("ORACLE_MISMATCH", "输入与测试预期不匹配。")
            result = aggregate(blobs, plan.limits.max_rows)
            root.mkdir(parents=True, exist_ok=False)
            data = {"summary.json": json_bytes({k: v for k, v in result.items() if k != "errors"}),
                    "errors.json": json_bytes(result["errors"]), "summary.csv": summary_csv(result["groups"])}
            for n, b in data.items():
                new_file(root / n, b)
            final_hashes = {p.name: digest(read_bounded(p, plan.limits.max_input_bytes))
                            for p in input_paths(args.fixture / "inputs", plan.limits.max_files)}
            persisted = {n: read_bounded(root / n, plan.limits.max_artifact_bytes) for n in data}
            report = verify(persisted["summary.json"], persisted["errors.json"], persisted["summary.csv"],
                            oracle, hashes, final_hashes)
            record = {"status": "SUCCEEDED" if report["passed"] else "FAILED", "verification": report,
                      "elapsed_seconds": perf_counter()-start, "kind": "offline_batch_reference_not_agent_baseline"}
            new_file(root / "baseline.json", json_bytes(record))
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0 if record["status"] == "SUCCEEDED" else 1
    except (RuntimeFault, OSError, ValueError, TypeError, RecursionError, sqlite3.Error) as exc:
        code = exc.code if isinstance(exc, RuntimeFault) else "CONFIG_OR_IO_ERROR"
        print(json.dumps({"status": "REJECTED", "error_code": code,
                          "message": "未执行成功。请使用新的工作目录和项目生成的合成 fixture；详情见交接文档。"},
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
