"""Probe: logical read counts for run, resume and paged artifact_read (REV-002).

Rebuilds the historical observation that one run re-reads the full input set
several times and that a one-character ``artifact_read`` still walks every
artifact. Counts LOGICAL calls into the checked reader only -- wall time and
physical disk I/O are out of scope and are not claimed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from instrument import ReadLog  # noqa: E402

from agentos_runtime.contracts import default_plan  # noqa: E402
from agentos_runtime.fixtures import generate  # noqa: E402
from agentos_runtime.gateway import AgentGateway, initialize_demo  # noqa: E402
from agentos_runtime.runtime import Runtime  # noqa: E402


def measure(files: int = 100, rows: int = 10, seed: int = 7) -> dict:
    phases: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="aor-probe-") as tmp:
        base = Path(tmp)

        fixture_root = base / "fixture"
        oracle = generate(fixture_root, files=files, rows_per_file=rows, seed=seed)
        inputs = fixture_root / "inputs"

        with ReadLog() as log:
            record = Runtime().run(default_plan(), inputs, base / "ws-run", oracle)
        phases["run"] = {**log.report(), "status": record["status"]}

        with ReadLog() as log:
            record = Runtime().resume(base / "ws-run", inputs, oracle)
        phases["resume_succeeded"] = {**log.report(), "status": record["status"]}

        home = base / "home"
        initialize_demo(home, files=files, rows=rows, seed=seed)
        gateway = AgentGateway(home)
        with ReadLog() as log:
            submitted = gateway.task_submit("demo", "probe-request-1")
        phases["gateway_task_submit"] = {**log.report(), "status": submitted["status"]}

        target = next(a for a in submitted["artifacts"] if a["name"] == "errors.json")
        with ReadLog() as log:
            page = gateway.artifact_read(submitted["task_id"], target["artifact_id"],
                                         offset=0, max_chars=1)
        phases["artifact_read_one_char"] = {
            **log.report(), "returned_chars": len(page["content"]),
            "artifact_bytes": target["bytes"],
        }
        with ReadLog() as log:
            opened = gateway.artifact_open(submitted["task_id"], target["artifact_id"])
        phases["artifact_open"] = {**log.report(), "artifact_bytes": target["bytes"]}
        with ReadLog() as log:
            for _ in range(3):
                gateway.artifact_session_read(opened["session_id"], offset=0, max_chars=1)
            gateway.artifact_session_close(opened["session_id"])
        phases["session_read_three_pages_and_close"] = log.report()
        with ReadLog() as log:
            gateway.task_inspect(submitted["task_id"])
        phases["task_inspect"] = log.report()

    return {"schema_version": "aor.probe-logical-reads.v1",
            "fixture": {"files": files, "rows_per_file": rows, "seed": seed},
            "phases": phases}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    result = measure()
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
