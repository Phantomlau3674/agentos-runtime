"""Allowlisted, content-free diagnostics for owner export.

Never exports source rows, oracle values, arbitrary event payloads, conversation
history, environment variables, browser state, hostnames or absolute paths.
"""
from __future__ import annotations

import platform
import sqlite3
from pathlib import Path

from . import __version__
from .gateway import AgentGateway
from .journal import Journal


def collect_diagnostics(home: Path, task_id: str) -> dict:
    gateway = AgentGateway(home)
    task = gateway._task(task_id)
    status = gateway.call('task_inspect', {'task_id': task_id})
    details = {'task_id': task_id, 'cancel_requested': bool(task['cancelled'])}
    allowed = {'status', 'run_id', 'plan_hash', 'attempt', 'completed_nodes', 'artifact_state',
               'error_code', 'execution_active', 'needs_recovery'}
    if status['ok']:
        details.update({key: val for key, val in status['data'].items() if key in allowed})
        details['artifact_count'] = len(status['data'].get('artifacts', []))
        # Export booleans, not extensible validator messages or raw data.
        verification = status['data'].get('verification') or {}
        details['verification_passed'] = verification.get('passed') is True
    else:
        details.update(status='INSPECTION_BLOCKED', error_code=status['error']['code'])
    counts = {}
    workspace = gateway._workspace(task_id)
    if (workspace / 'journal.sqlite3').exists():
        journal = None
        try:
            journal = Journal(workspace / 'journal.sqlite3', create=False)
            known = {'run_started', 'operation_intent', 'operation_completed', 'operation_reconciling',
                     'run_resumed', 'run_finished'}
            for row in journal.connection.execute('SELECT kind,COUNT(*) AS count FROM events GROUP BY kind'):
                label = row['kind'] if row['kind'] in known else 'other_event'
                counts[label] = counts.get(label, 0) + row['count']
        except Exception:
            counts = {'journal_unreadable': 1}
        finally:
            if journal is not None:
                journal.close()
    return {'schema_version': 'aor.diagnostics.v0.1',
            'software': {'agentos_runtime': __version__, 'python': platform.python_version(),
                         'os': platform.system(), 'sqlite': sqlite3.sqlite_version},
            'task': details, 'event_counts': counts,
            'live_model_measurement': 'not_run',
            'excluded': ['source_content', 'oracle', 'raw_event_payloads', 'host_paths',
                         'credentials', 'environment_variables', 'conversation_history'],
            'boundary': 'trusted-local synthetic fixture; not malicious-host tamper resistance'}
