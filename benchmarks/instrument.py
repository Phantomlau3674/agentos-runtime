"""Logical-read instrumentation for the trusted local file primitives (REV-002).

Counts calls into ``read_bounded`` and ``Runtime._read_sources`` per import
site. These are LOGICAL reads through the runtime's checked reader: one call
may or may not hit disk (OS cache), and no physical I/O is measured here.
"""
from __future__ import annotations

import importlib
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

_PATCH_SITES = ("agentos_runtime.runtime", "agentos_runtime.gateway", "agentos_runtime.storage")


class ReadLog:
    """Context manager counting logical reads by call site label.

    ``sources`` records each full pass over the input directory performed by
    ``Runtime._read_sources``; ``reads`` records every ``read_bounded`` call,
    labelled by the module whose namespace was patched.
    """

    def __init__(self) -> None:
        self.reads: list[dict] = []
        self.sources: list[dict] = []
        self._restores: list[tuple[object, str, object]] = []

    def _wrap_read(self, module: object, label: str) -> None:
        original = getattr(module, "read_bounded")

        def counted(path, maximum, _original=original, _label=label):
            data = _original(path, maximum)
            self.reads.append({"site": _label, "file": Path(path).name, "bytes": len(data)})
            return data

        setattr(module, "read_bounded", counted)
        self._restores.append((module, "read_bounded", original))

    def __enter__(self) -> "ReadLog":
        runtime = importlib.import_module("agentos_runtime.runtime")
        original_sources = runtime.Runtime._read_sources

        def counted_sources(root, plan, check=lambda: None, _original=original_sources):
            blobs = _original(root, plan, check)
            self.sources.append({"files": len(blobs), "bytes": sum(len(b) for b in blobs.values()),
                                 "root": Path(root).name})
            return blobs

        runtime.Runtime._read_sources = staticmethod(counted_sources)
        self._restores.append((runtime.Runtime, "_read_sources", staticmethod(original_sources)))
        for name in _PATCH_SITES:
            module = importlib.import_module(name)
            if hasattr(module, "read_bounded"):
                self._wrap_read(module, name.rsplit(".", 1)[-1])
        return self

    def __exit__(self, *exc) -> None:
        for obj, attr, original in self._restores:
            setattr(obj, attr, original)
        self._restores.clear()

    def report(self) -> dict:
        by_site: dict[str, dict] = {}
        for entry in self.reads:
            slot = by_site.setdefault(entry["site"], {"calls": 0, "bytes": 0, "files": set()})
            slot["calls"] += 1
            slot["bytes"] += entry["bytes"]
            slot["files"].add(entry["file"])
        return {
            "read_bounded_by_site": {k: {"calls": v["calls"], "bytes": v["bytes"],
                                         "distinct_files": len(v["files"])}
                                   for k, v in sorted(by_site.items())},
            "read_bounded_total": {"calls": len(self.reads), "bytes": sum(e["bytes"] for e in self.reads)},
            "source_passes": {"calls": len(self.sources),
                              "files": sum(e["files"] for e in self.sources),
                              "bytes": sum(e["bytes"] for e in self.sources),
                              "detail": self.sources},
            "measurement_kind": "logical_calls_to_checked_reader; not physical disk I/O",
        }
