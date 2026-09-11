"""Shared helpers for tests that manage real child processes."""
from __future__ import annotations

import os
import subprocess


def kill_process_tree(process: subprocess.Popen) -> None:
    """Terminate exactly the spawned test worker and any children it launched.

    On Windows the venv ``python.exe`` is a launcher stub: the real interpreter
    runs as its child, so ``Popen.kill()`` orphans a live worker that keeps the
    workspace byte-range lock (observed as WORKSPACE_BUSY after kill+wait).
    Kill the tree while the owned launcher is still alive. Never sweep by a
    dead parent's numeric PID: a reused PID could refer to unrelated work.
    Crash-test workers stay paused until this helper terminates them.
    """
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)],
                       capture_output=True, timeout=15, check=True)
    else:
        process.kill()
    process.wait(timeout=10)
