"""SQLite v2 journal with atomic state/event transitions and stage receipts."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .errors import RuntimeFault
from .storage import checked_path, database_path

SCHEMA_VERSION = 2
APPLICATION_ID = 0x414F5232
MAX_ATTEMPTS = 4  # Initial attempt plus at most three owner-requested resumes.


class Journal:
    def __init__(self, path: Path, *, create: bool = True):
        path = checked_path(path)
        for suffix in ('-journal', '-wal', '-shm'):
            database_path(Path(str(path) + suffix), 67_108_864, optional=True)
        if not create:
            if not path.exists():
                raise RuntimeFault('JOURNAL_MISSING', '没有可核对的执行日志，不自动恢复。')
            database_path(path, 67_108_864)
        elif path.exists():
            raise FileExistsError(path)
        self.connection = sqlite3.connect(path.as_uri() + ('?mode=rwc' if create else '?mode=rw'),
                                          uri=True, timeout=2)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute('PRAGMA synchronous=FULL')
            self.connection.execute('PRAGMA trusted_schema=OFF')
            if create:
                self.connection.executescript(f'''
                    BEGIN IMMEDIATE;
                    PRAGMA application_id={APPLICATION_ID};
                    PRAGMA user_version={SCHEMA_VERSION};
                    CREATE TABLE runs (id TEXT PRIMARY KEY, plan_hash TEXT NOT NULL, status TEXT NOT NULL);
                    CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                                         at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
                    CREATE TABLE metadata (run_id TEXT PRIMARY KEY, engine TEXT NOT NULL,
                        oracle_hash TEXT NOT NULL, input_binding TEXT NOT NULL,
                        attempts INTEGER NOT NULL, prepared TEXT, record TEXT);
                    CREATE TABLE checkpoints (run_id TEXT NOT NULL, node TEXT NOT NULL,
                        operation_id TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(run_id, node));
                    COMMIT;
                ''')
                self.connection.commit()
            else:
                if (self.connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION
                        or self.connection.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID):
                    raise RuntimeFault('JOURNAL_VERSION', '旧版或不受支持的日志不能自动恢复。')
                if self.connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeFault('JOURNAL_CORRUPT', '日志完整性检查失败，停止恢复。')
        except BaseException:
            self.connection.close()
            raise

    def _event(self, run_id: str, kind: str, payload: dict) -> None:
        self.connection.execute('INSERT INTO events(run_id,at,kind,payload) VALUES (?,?,?,?)',
            (run_id, datetime.now(timezone.utc).isoformat(), kind,
             json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)))

    def create(self, run_id: str, plan_hash: str, *, engine: str, oracle_hash: str, input_binding: str) -> None:
        with self.connection:
            self.connection.execute("INSERT INTO runs VALUES (?,?,'RUNNING')", (run_id, plan_hash))
            self.connection.execute('INSERT INTO metadata VALUES (?,?,?,?,1,NULL,NULL)',
                                    (run_id, engine, oracle_hash, input_binding))
            self._event(run_id, 'run_started', {'plan_hash': plan_hash})

    def load(self) -> dict:
        rows = self.connection.execute('SELECT * FROM runs JOIN metadata ON runs.id=metadata.run_id').fetchall()
        if len(rows) != 1:
            raise RuntimeFault('JOURNAL_INCOMPLETE', '执行日志未完成初始化，不能自动恢复。')
        return dict(rows[0])

    def event(self, run_id: str, kind: str, payload: dict) -> None:
        with self.connection:
            self._event(run_id, kind, payload)

    def receipts(self, run_id: str) -> dict[str, dict]:
        return {row['node']: json.loads(row['receipt']) for row in self.connection.execute(
            'SELECT node,receipt FROM checkpoints WHERE run_id=?', (run_id,))}

    def intent_exists(self, run_id: str, operation_id: str) -> bool:
        for row in self.connection.execute("SELECT payload FROM events WHERE run_id=? AND kind='operation_intent'", (run_id,)):
            if json.loads(row[0]).get('operation_id') == operation_id:
                return True
        return False

    def complete(self, run_id: str, node: str, operation_id: str, receipt: dict) -> None:
        with self.connection:
            self.connection.execute('INSERT INTO checkpoints VALUES (?,?,?,?)',
                (run_id, node, operation_id, json.dumps(receipt, sort_keys=True)))
            self._event(run_id, 'operation_completed', {'node': node, 'operation_id': operation_id})

    def prepare(self, run_id: str, receipt: dict) -> None:
        with self.connection:
            self.connection.execute('UPDATE metadata SET prepared=? WHERE run_id=?',
                                    (json.dumps(receipt, sort_keys=True), run_id))

    def begin_resume(self, run_id: str) -> None:
        with self.connection:
            row = self.connection.execute('SELECT attempts FROM metadata WHERE run_id=?', (run_id,)).fetchone()
            if row is None or row[0] >= MAX_ATTEMPTS:
                raise RuntimeFault('RECOVERY_BUDGET', '恢复次数已达上限，保留结果并等待人工检查。')
            self.connection.execute('UPDATE metadata SET attempts=attempts+1 WHERE run_id=?', (run_id,))
            self.connection.execute("UPDATE runs SET status='RUNNING' WHERE id=?", (run_id,))
            self._event(run_id, 'run_resumed', {'attempt': row[0] + 1})

    def finish(self, run_id: str, status: str, error: str | None = None, *, record: dict) -> None:
        with self.connection:
            self.connection.execute('UPDATE runs SET status=? WHERE id=?', (status, run_id))
            self.connection.execute('UPDATE metadata SET record=? WHERE run_id=?',
                                    (json.dumps(record, ensure_ascii=False, sort_keys=True), run_id))
            self._event(run_id, 'run_finished', {'status': status, 'error_code': error})

    def close(self) -> None:
        self.connection.close()
