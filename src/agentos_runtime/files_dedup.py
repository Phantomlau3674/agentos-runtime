"""Second task family (ADP-006): content-hash manifest and duplicate grouping.

Deterministic over snapshot bytes; no external reads. The oracle is produced by
fixtures.generate_dedup and verified independently -- the verifier never calls
this implementation.
"""
from __future__ import annotations

import csv
import io

from .errors import RuntimeFault
from .storage import digest


def dedup_manifest(blobs: dict[str, bytes], max_files: int) -> dict:
    """Group identical files by content hash. Input order never affects output."""
    if len(blobs) > max_files:
        raise RuntimeFault('INPUT_BUDGET', '文件数超出计划限额。')
    groups: dict[str, list[str]] = {}
    for name in sorted(blobs):
        groups.setdefault(digest(blobs[name]), []).append(name)
    duplicates = {h: names for h, names in groups.items() if len(names) > 1}
    return {'total_files': len(blobs), 'unique_contents': len(groups),
            'duplicate_files': sum(len(v) for v in duplicates.values()),
            'duplicate_groups': [{'sha256': h, 'files': names}
                                 for h, names in sorted(duplicates.items())],
            'unique_files': sorted(n for h, names in groups.items()
                                   if len(names) == 1 for n in names)}


def duplicates_csv(result: dict) -> bytes:
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(['sha256', 'file'])
    for group in result['duplicate_groups']:
        for name in group['files']:
            writer.writerow([group['sha256'], name])
    return buffer.getvalue().encode('utf-8')
