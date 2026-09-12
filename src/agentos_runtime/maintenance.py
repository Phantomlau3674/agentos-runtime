"""DAT-006: storage quota and dry-run garbage collection for task workspaces.

Owner-side only; never an agent tool. Deletion requires an explicit apply step;
the plan view is always dry-run first. Running workspaces are never collected.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import time

from .errors import RuntimeFault
from .storage import checked_path, database_path

TERMINAL = {'SUCCEEDED', 'FAILED', 'CANCELLED'}


def _tree_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob('*'):
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total


def home_usage(home: Path) -> dict:
    """Inventory task workspaces with size, age and journal status."""
    home = checked_path(home)
    tasks = home / 'tasks'
    entries = []
    now = time.time()
    if tasks.is_dir():
        for task_dir in sorted(tasks.iterdir()):
            workspace = task_dir / 'run'
            journal = workspace / 'journal.sqlite3'
            status = 'no_journal'
            if journal.exists():
                import sqlite3
                conn = sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True)
                try:
                    row = conn.execute('SELECT status FROM runs LIMIT 1').fetchone()
                    status = row[0] if row else 'no_runs'
                except sqlite3.Error:
                    status = 'journal_unreadable'
                finally:
                    conn.close()
            size = _tree_bytes(task_dir)
            entries.append({'task_id': task_dir.name, 'bytes': size,
                            'age_seconds': round(now - task_dir.stat().st_mtime, 1),
                            'status': status})
    return {'tasks': entries, 'total_bytes': sum(e['bytes'] for e in entries),
            'count': len(entries)}


def gc_plan(home: Path, *, older_than_seconds: float = 86400 * 7,
            max_total_bytes: int | None = None) -> dict:
    """Dry-run only: which terminal workspaces are eligible for collection.

    Active journals (RUNNING/INTERRUPTED) are never eligible regardless of age.
    """
    usage = home_usage(home)
    eligible = [e for e in usage['tasks'] if e['status'] in TERMINAL
                and e['age_seconds'] >= older_than_seconds]
    if max_total_bytes is not None:
        keep_bytes = usage['total_bytes'] - max_total_bytes
        for entry in eligible:
            if keep_bytes <= 0:
                entry['eligible'] = False
                continue
            entry['eligible'] = True
            keep_bytes -= entry['bytes']
    else:
        for entry in eligible:
            entry['eligible'] = True
    return {'dry_run': True, 'eligible': eligible,
            'protected': [e['task_id'] for e in usage['tasks']
                          if e['status'] not in TERMINAL]}


def gc_apply(home: Path, plan: dict) -> dict:
    """Apply a gc_plan. Destructive; owner CLI only, never an agent tool."""
    if not plan.get('dry_run') or not isinstance(plan.get('eligible'), list):
        raise RuntimeFault('GC_PLAN_INVALID', '只接受 gc_plan() 生成的 dry-run 计划。')
    removed = []
    for entry in plan['eligible']:
        if not entry.get('eligible'):
            continue
        target = checked_path(home) / 'tasks' / entry['task_id']
        if not target.is_dir():
            continue
        shutil.rmtree(target)
        removed.append(entry['task_id'])
    return {'removed': removed, 'count': len(removed)}


def enforce_task_quota(home: Path, *, max_tasks: int, max_total_bytes: int) -> None:
    """Called before a new task workspace is created."""
    usage = home_usage(home)
    if usage['count'] >= max_tasks:
        raise RuntimeFault('TASK_BUDGET', '任务数量达到所有者上限，先归档或清理。')
    if usage['total_bytes'] >= max_total_bytes:
        raise RuntimeFault('TASK_BUDGET', '任务存储达到所有者配额，先归档或清理。')
