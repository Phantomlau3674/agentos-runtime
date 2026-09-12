"""Trusted-local file primitives; NOT protection against a hostile same-user process."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .errors import RuntimeFault

SAFE_CSV = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.csv$")
SAFE_BLOB = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.(dat|bin|txt)$")
SAFE_BRIEF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.(txt|md)$")
INPUT_NAME_RULES = {'tabular.aggregate': SAFE_CSV, 'files.dedup_manifest': SAFE_BLOB,
                    'drafts.mock_flow': SAFE_BRIEF}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def checked_path(path: Path) -> Path:
    # Do not resolve first: it would hide an existing link component.
    path = Path(os.path.abspath(path))
    for component in (path, *path.parents):
        if component.is_symlink() or (hasattr(component, "is_junction") and component.is_junction()):
            raise RuntimeFault("UNSUPPORTED_LINK", "不支持符号链接或重解析路径。")
    return path


def new_file(path: Path, data: bytes) -> None:
    """Never overwrite an existing path. Durability of parent directory is not promised."""
    checked_path(path)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def read_bounded(path: Path, maximum: int) -> bytes:
    checked_path(path)
    if maximum < 0:
        raise RuntimeFault("INPUT_BUDGET", "输入超过字节预算。")
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise RuntimeFault("UNSUPPORTED_FILE", "仅支持普通、非链接输入文件。")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        current = os.fstat(handle.fileno())
        if (st.st_ino, st.st_dev) != (current.st_ino, current.st_dev):
            raise RuntimeFault("INPUT_CHANGED", "输入在读取前发生变化。")
        data = handle.read(maximum + 1)
        if len(data) > maximum:
            raise RuntimeFault("INPUT_BUDGET", "输入超过字节预算。")
        final = os.fstat(handle.fileno())
        if (current.st_size, current.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
            raise RuntimeFault("INPUT_CHANGED", "输入在读取期间发生变化。")
        return data


def input_paths(root: Path, max_files: int, rule: re.Pattern = SAFE_CSV) -> list[Path]:
    root = checked_path(root)
    if not root.is_dir():
        raise RuntimeFault("INPUT_ROOT", "请选择已存在的合成输入目录。")
    paths: list[Path] = []
    # Flat directory only. Stop enumeration before collecting unbounded entries.
    for path in root.iterdir():
        if len(paths) >= max_files:
            raise RuntimeFault("FILE_BUDGET", "文件数量超过预算。")
        if not rule.fullmatch(path.name):
            raise RuntimeFault("INPUT_NAME", "目录只能包含本任务族允许的文件名，不能包含子目录。")
        paths.append(path)
    if not paths:
        raise RuntimeFault("EMPTY_INPUT", "输入目录没有可处理的文件。")
    return sorted(paths, key=lambda p: p.name)


def sync_directory(path: Path) -> None:
    """Flush directory metadata on POSIX; no power-loss guarantee on Windows."""
    checked_path(path)
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_json(path: Path, value: object) -> None:
    """Replace a derived metadata file, never an input or public artifact."""
    from uuid import uuid4
    checked_path(path)
    if path.exists():
        read_bounded(path, 2_097_152)  # reject hard links and non-regular targets
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        new_file(temporary, json_bytes(value))
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def ensure_file(path: Path, content: bytes, *, code: str = 'ARTIFACT_CHANGED') -> None:
    """Recover an uncommitted local copy only if its bytes are exactly expected.

    A partial or different file is evidence requiring review, not permission to
    silently replace it. Missing files may be newly created in this namespace.
    """
    checked_path(path)
    if path.exists():
        if read_bounded(path, len(content)) != content:
            raise RuntimeFault(code, '已有文件与预期不一致，保留现场并停止。')
    else:
        new_file(path, content)
        sync_directory(path.parent)


def database_path(path: Path, maximum: int, *, optional: bool = False) -> Path:
    """Type/size checks for a MUTABLE SQLite file, not immutable-file hashing.

    SQLite provides transaction consistency. Requiring stable mtime while reading
    its raw bytes incorrectly rejects concurrent writers. Same-user path races
    remain outside this trusted-local boundary.
    """
    path = checked_path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if optional:
            return path
        raise
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeFault('UNSUPPORTED_FILE', '数据库路径不是受支持的普通文件。')
    if info.st_size > maximum:
        raise RuntimeFault('DATABASE_BUDGET', '数据库超过当前工作区预算。')
    return path
