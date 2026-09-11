"""Record the reproduction environment for local measurements (REV-001).

Captures the git commit, interpreter, platform, pinned dependencies, and
per-file digests of the trusted source under test. Emits one JSON document.
It measures nothing and makes no performance claim.
"""
from __future__ import annotations

import hashlib
import json
from importlib import metadata
from pathlib import Path
import platform
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "src" / "agentos_runtime"
LOCK_FILE = REPO_ROOT / "requirements.lock.txt"


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture() -> dict:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from agentos_runtime.runtime import engine_fingerprint

    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", "src", "tests"],
        capture_output=True, text=True, check=True).stdout.strip()
    dependencies = {}
    for name in ("pydantic", "pydantic-core", "pytest", "mcp"):
        try:
            dependencies[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            dependencies[name] = None
    return {
        "schema_version": "aor.repro-env.v1",
        "recorded_at_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "git": {"commit": _git("rev-parse", "HEAD"), "branch": _git("branch", "--show-current"),
                "src_tests_dirty": bool(tracked)},
        "python": sys.version,
        "platform": {"system": platform.system(), "release": platform.release(),
                     "machine": platform.machine(), "processor": platform.processor()},
        "dependencies": dependencies,
        "requirements_lock_sha256": _sha256(LOCK_FILE),
        "engine_fingerprint": engine_fingerprint(),
        "source_sha256": {p.name: _sha256(p) for p in sorted(SOURCE_DIR.glob("*.py"))},
        "evidence_manifest": "docs/reviews/2026-09-11/evidence/manifest.json",
        "scope": "environment record only; not a performance or regression result",
    }


def main() -> None:
    print(json.dumps(capture(), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
