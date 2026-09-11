"""Cooperative process exclusion, not a sandbox against hostile local code."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat

from .errors import RuntimeFault
from .storage import checked_path


@contextmanager
def workspace_lock(workspace: Path):
    """A persistent lock file whose kernel lock disappears after process death.

    Never unlink a lock file: doing so could allow two live processes to lock
    different inodes under the same name. Windows branch needs native CI.
    """
    path = checked_path(workspace / '.run.lock')
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags, 0o600)
    acquired = False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeFault('UNSUPPORTED_FILE', '工作区锁不是受支持的普通文件。')
        if os.name == 'nt':
            import msvcrt
            if info.st_size == 0:
                os.write(fd, b'0')
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeFault('WORKSPACE_BUSY', '任务仍由另一个进程执行，不能同时恢复。') from exc
        elif os.name == 'posix':
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeFault('WORKSPACE_BUSY', '任务仍由另一个进程执行，不能同时恢复。') from exc
        else:
            raise RuntimeFault('LOCK_UNSUPPORTED', '该平台尚无经支持的进程锁。')
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
