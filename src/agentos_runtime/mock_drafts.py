"""Third task family (ADP-005): local mock draft site.

No accounts, no network, no paid models. The "site" is a directory inside the
task workspace; drafts are keyed by digest(title + body_sha256) so re-runs are
idempotent and reconcile-safe. Draft fields bind the input hash directly.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .errors import RuntimeFault
from .storage import digest, ensure_file, json_bytes


def draft_key(title: str, body_sha256: str) -> str:
    return digest(f'{title}:{body_sha256}'.encode('utf-8'))


def mock_flow(blobs: dict[str, bytes], site_root: Path, max_files: int) -> dict:
    """Create-or-reuse drafts in the workspace-local mock site, then read back."""
    if len(blobs) > max_files:
        raise RuntimeFault('INPUT_BUDGET', '草稿文件数超出计划限额。')
    drafts_dir = site_root / 'drafts'
    drafts_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for name in sorted(blobs):
        body = blobs[name]
        key = draft_key(name, digest(body))
        target = drafts_dir / f'{key}.json'
        draft = json_bytes({'draft_key': key, 'title': name,
                            'body_sha256': digest(body), 'bytes': len(body),
                            'status': 'draft'})
        # Idempotent: identical bytes are reused, different bytes fail closed.
        # Run-varying flags stay out of the result so the checkpoint is
        # deterministic across a crash-and-resume boundary.
        ensure_file(target, draft, code='DRAFT_CHANGED')
        readback = json.loads(target.read_bytes())
        if readback['body_sha256'] != digest(body) or readback['draft_key'] != key:
            raise RuntimeFault('DRAFT_READBACK', '草稿回读与写入不一致。')
        records.append({'draft_key': key, 'title': name, 'body_sha256': digest(body),
                        'bytes': len(body)})
    return {'total_briefs': len(records), 'drafts': records}


def drafts_csv(result: dict) -> bytes:
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(['draft_key', 'title', 'bytes'])
    for record in result['drafts']:
        writer.writerow([record['draft_key'], record['title'], record['bytes']])
    return buffer.getvalue().encode('utf-8')
