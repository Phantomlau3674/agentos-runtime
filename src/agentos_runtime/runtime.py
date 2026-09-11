"""Bounded synthetic-fixture runtime with explicit, owner-requested recovery.

Only deterministic local copies are recoverable. No arbitrary external effects,
implicit retries of failures, whole-computer sandbox or distributed transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Callable
from uuid import uuid4

from .actions import action_contract
from .compiler import CompiledPlan, compile_canonical, compile_plan
from .contracts import OPERATIONS, PlanSpec
from .errors import RuntimeFault
from .journal import Journal, MAX_ATTEMPTS
from .locking import workspace_lock
from .storage import (atomic_json, checked_path, digest, ensure_file, input_paths,
                      json_bytes, new_file, read_bounded, sync_directory)
from .tabular import aggregate, summary_csv
from .verification import verify

ARTIFACTS = frozenset({'summary.json', 'errors.json', 'summary.csv'})
PUBLIC_ARTIFACTS = ARTIFACTS | {'verification.json'}
PhaseHook = Callable[[str, Path], None]


def engine_fingerprint() -> str:
    """Prevent reusing receipts across a changed implementation or verifier."""
    root = Path(__file__).parent
    names = ('runtime.py', 'contracts.py', 'compiler.py', 'actions.py', 'storage.py',
             'journal.py', 'locking.py', 'tabular.py', 'verification.py')
    return digest(b''.join(name.encode() + (root / name).read_bytes() for name in names))


@dataclass
class Policy:
    # This object comes from the local owner, never from an agent-supplied plan.
    allowed_operations: frozenset[str] = frozenset(OPERATIONS)
    cancelled: bool = False

    def check(self, operation: str) -> None:
        if self.cancelled:
            raise RuntimeFault('CANCELLED', '任务已取消，后续动作未执行。')
        if operation not in self.allowed_operations:
            raise RuntimeFault('POLICY_DENIED', '该动作未获得本地所有者授权。')


def _preflight(plan: PlanSpec | bytes, input_root: Path, workspace: Path,
               policy: Policy) -> tuple[CompiledPlan, Path, Path]:
    compiled = compile_canonical(plan) if isinstance(plan, bytes) else compile_plan(plan)
    scope = compiled.contract.allowed_operations if compiled.contract else None
    for node in compiled.nodes:
        if scope is not None and node.operation not in scope:
            raise RuntimeFault('CONTRACT_DENIED', '该动作超出本计划目标合同的授权范围。')
        policy.check(node.operation)
        action_contract(node.operation)
    input_root, workspace = checked_path(input_root), checked_path(workspace)
    if workspace == input_root or input_root in workspace.parents or workspace in input_root.parents:
        raise RuntimeFault('WORKSPACE_OVERLAP', '输入目录和工作区必须分离。')
    return compiled, input_root, workspace


def _directory_names(root: Path, allowed: set | frozenset) -> set[str]:
    checked_path(root)
    if not root.is_dir():
        raise RuntimeFault('CHECKPOINT_MISSING', '需要核对的目录不存在。')
    names = set()
    for path in root.iterdir():
        if path.name not in allowed:
            raise RuntimeFault('UNEXPECTED_FILE', '受控目录出现未知文件，保留现场并停止。')
        names.add(path.name)
    return names


def _validate_artifacts(root: Path, manifest: dict, maximum: int, *, full: bool = False) -> dict[str, bytes]:
    expected = PUBLIC_ARTIFACTS if full else ARTIFACTS
    if set(manifest) != expected:
        raise RuntimeFault('CHECKPOINT_INVALID', '产物回执结构不符合当前契约。')
    names = _directory_names(root, PUBLIC_ARTIFACTS)
    if not expected <= names or (full and names != expected):
        raise RuntimeFault('ARTIFACT_MISSING', '产物缺失，不能复用已完成结果。')
    remaining, data = maximum, {}
    for name, info in manifest.items():
        blob = read_bounded(root / name, remaining)
        remaining -= len(blob)
        if digest(blob) != info.get('sha256') or len(blob) != info.get('bytes'):
            raise RuntimeFault('ARTIFACT_CHANGED', '产物已变化，不能复用或标记成功。')
        data[name] = blob
    return data


class Runtime:
    def run(self, plan: PlanSpec, input_root: Path, workspace: Path, oracle: dict, *,
            policy: Policy | None = None, after_node: PhaseHook | None = None,
            phase_hook: PhaseHook | None = None) -> dict:
        policy = policy or Policy()
        plan, input_root, workspace = _preflight(plan, input_root, workspace, policy)
        oracle = json.loads(json_bytes(oracle))
        workspace.mkdir(parents=True, exist_ok=False)
        with workspace_lock(workspace):
            journal = Journal(workspace / 'journal.sqlite3')
            try:
                run_id = str(uuid4())
                new_file(workspace / 'plan.json', plan.canonical_bytes)
                sync_directory(workspace)
                journal.create(run_id, plan.plan_hash, engine=engine_fingerprint(),
                               oracle_hash=digest(json_bytes(oracle)), input_binding=digest(str(input_root).encode()))
                return self._execute(plan, input_root, workspace, oracle, policy, journal,
                                     resumed=False, after_node=after_node, phase_hook=phase_hook)
            finally:
                journal.close()

    def resume(self, workspace: Path, input_root: Path, oracle: dict, *,
               policy: Policy | None = None, expected_plan_hash: str | None = None,
               phase_hook: PhaseHook | None = None) -> dict:
        """Explicit reconcile-and-resume; failures/cancellations are not retried.

        Kernel lock excludes a still-live worker. All original bindings and
        current permissions must match. Old v0.0.1 workspaces fail closed.
        """
        workspace = checked_path(workspace)
        if not workspace.is_dir():
            raise RuntimeFault('WORKSPACE_MISSING', '工作区不存在。')
        with workspace_lock(workspace):
            # plan.json is validated exactly once: canonical bytes -> CompiledPlan.
            plan_data = read_bounded(workspace / 'plan.json', 65_536)
            policy = policy or Policy()
            plan, input_root, workspace = _preflight(plan_data, input_root, workspace, policy)
            oracle = json.loads(json_bytes(oracle))
            journal = Journal(workspace / 'journal.sqlite3', create=False)
            try:
                state = journal.load()
                if plan.plan_hash != state['plan_hash'] or (expected_plan_hash is not None and plan.plan_hash != expected_plan_hash):
                    journal.event(state['id'], 'audit.plan_changed',
                                  {'stored': state['plan_hash'], 'presented': plan.plan_hash})
                    raise RuntimeFault('PLAN_CHANGED', '计划版本已变化，不能继续旧任务。')
                if state['engine'] != engine_fingerprint():
                    raise RuntimeFault('ENGINE_CHANGED', '执行器或核验器版本变化，不能沿用旧回执。')
                if state['oracle_hash'] != digest(json_bytes(oracle)):
                    raise RuntimeFault('ORACLE_CHANGED', '所有者的核验预期已变化，不能自动恢复。')
                if state['input_binding'] != digest(str(input_root).encode()):
                    raise RuntimeFault('INPUT_BINDING_CHANGED', '输入目录与原任务绑定不同。')
                if state['status'] not in {'RUNNING', 'INTERRUPTED', 'SUCCEEDED'}:
                    raise RuntimeFault('TERMINAL_RUN', '失败或取消的任务不自动重试，请检查原因并新建任务。')
                hashes = self._current_hashes(input_root, plan)
                if hashes != oracle.get('input_hashes'):
                    raise RuntimeFault('INPUT_CHANGED', '输入版本变化，不能继续旧任务。')
                if state['status'] == 'SUCCEEDED':
                    record = json.loads(state['record'])
                    data = _validate_artifacts(workspace / 'outputs', record['artifacts'],
                                               plan.limits.max_artifact_bytes, full=True)
                    report = verify(data['summary.json'], data['errors.json'], data['summary.csv'], oracle, hashes, hashes)
                    if not report['passed'] or json.loads(data['verification.json']) != report:
                        raise RuntimeFault('VERIFICATION_FAILED', '历史产物未通过重新核验。')
                    # run.json is a derived cache, repaired from the committed DB record.
                    atomic_json(workspace / 'run.json', record)
                    return record
                journal.begin_resume(state['id'])
                return self._execute(plan, input_root, workspace, oracle, policy, journal,
                                     resumed=True, after_node=None, phase_hook=phase_hook)
            finally:
                journal.close()

    @staticmethod
    def _read_sources(root: Path, plan: CompiledPlan, check: Callable[[], None] = lambda: None) -> dict[str, bytes]:
        remaining, source = plan.limits.max_input_bytes, {}
        for path in input_paths(root, plan.limits.max_files):
            check()
            blob = read_bounded(path, remaining)
            remaining -= len(blob)
            source[path.name] = blob
        return source

    @classmethod
    def _current_hashes(cls, root: Path, plan: CompiledPlan) -> dict[str, str]:
        return {n: digest(b) for n, b in cls._read_sources(root, plan).items()}

    def _execute(self, plan: CompiledPlan, input_root: Path, workspace: Path, oracle: dict,
                 policy: Policy, journal: Journal, *, resumed: bool,
                 after_node: PhaseHook | None, phase_hook: PhaseHook | None) -> dict:
        started = perf_counter()
        state = journal.load()
        run_id = state['id']
        receipts = journal.receipts(run_id)
        prepared = json.loads(state['prepared']) if state['prepared'] else None
        blobs, hashes, artifact_manifest = {}, {}, {}
        result = report = None
        status, error_code = 'RUNNING', None
        executed, reused, reconciled = [], [], []
        staging, output = workspace / 'staging', workspace / 'outputs'

        def hook(phase: str) -> None:
            if phase_hook:
                phase_hook(phase, workspace)  # Test-only: never accepted in a plan or tool call.

        def check_budget() -> None:
            if perf_counter() - started > plan.limits.max_seconds:
                raise RuntimeFault('TIME_BUDGET', '本次执行超过时间预算，后续动作已停止。')

        def check_sources() -> None:
            if hashes and {n: digest(b) for n, b in self._read_sources(input_root, plan, check_budget).items()} != hashes:
                raise RuntimeFault('INPUT_CHANGED', '原始输入已经变化，停止沿用旧计划。')

        def local_root() -> Path:
            if output.exists():
                if staging.exists():
                    raise RuntimeFault('PUBLICATION_CONFLICT', '暂存和交付目录同时存在，不能猜测哪份有效。')
                if prepared is None:
                    raise RuntimeFault('UNKNOWN_EFFECT', '交付目录存在但没有提交意图，不自动收编或覆盖。')
                return output
            return staging

        def validate_snapshot(receipt: dict) -> None:
            nonlocal blobs, hashes
            hashes = receipt['hashes']
            if hashes != oracle.get('input_hashes'):
                raise RuntimeFault('CHECKPOINT_INVALID', '快照回执与原始输入版本不一致。')
            snap = workspace / 'snapshots'
            if _directory_names(snap, set(hashes)) != set(hashes):
                raise RuntimeFault('CHECKPOINT_MISSING', '已完成的输入快照缺失。')
            blobs = self._read_sources(snap, plan, check_budget)
            if {n: digest(b) for n, b in blobs.items()} != hashes:
                raise RuntimeFault('SNAPSHOT_CHANGED', '输入快照被修改，停止恢复。')
            if json.loads(read_bounded(workspace / 'input_manifest.json', 262_144)) != hashes:
                raise RuntimeFault('CHECKPOINT_INVALID', '输入清单不一致。')
            check_sources()

        try:
            completed_ids = set(receipts)
            prefix = [n.id for n in plan.nodes[:len(completed_ids)]]
            if completed_ids != set(prefix):
                raise RuntimeFault('CHECKPOINT_ORDER', '已完成阶段不是合法前缀，停止恢复。')
            for node in plan.nodes:
                policy.check(node.operation)
                check_budget()
                check_sources()
                operation_id = digest(f'{run_id}:{plan.plan_hash}:{node.id}'.encode())
                if node.id in receipts:
                    receipt = receipts[node.id]
                    if node.operation == 'inputs.snapshot':
                        validate_snapshot(receipt)
                    elif node.operation == 'tabular.aggregate':
                        blob = read_bounded(workspace / 'checkpoints' / 'aggregate.json', plan.limits.max_artifact_bytes)
                        if digest(blob) != receipt['sha256']:
                            raise RuntimeFault('CHECKPOINT_CHANGED', '汇总检查点已变化，停止恢复。')
                        result = json.loads(blob)
                    elif node.operation == 'artifacts.export':
                        artifact_manifest = receipt['artifacts']
                        _validate_artifacts(local_root(), artifact_manifest, plan.limits.max_artifact_bytes)
                    else:
                        if prepared is None or prepared != receipt:
                            raise RuntimeFault('CHECKPOINT_INVALID', '交付回执与准备记录不一致。')
                        artifact_manifest = receipt['artifacts']
                        data = _validate_artifacts(output, artifact_manifest, plan.limits.max_artifact_bytes, full=True)
                        report = verify(data['summary.json'], data['errors.json'], data['summary.csv'], oracle, hashes, hashes)
                        if plan.contract is not None and report['validator'] != plan.contract.acceptance:
                            raise RuntimeFault('ACCEPTANCE_MISMATCH',
                                               '验收标准与实际核验器不一致，不能按合同交付。')
                        if not report['passed'] or json.loads(data['verification.json']) != report:
                            raise RuntimeFault('VERIFICATION_FAILED', '恢复时独立核验失败。')
                    reused.append(node.id)
                    continue

                if journal.intent_exists(run_id, operation_id):
                    reconciled.append(node.id)
                    journal.event(run_id, 'operation_reconciling', {'node': node.id, 'operation_id': operation_id})
                else:
                    journal.event(run_id, 'operation_intent', {'node': node.id, 'operation': node.operation,
                                                              'operation_id': operation_id,
                                                              'effect': action_contract(node.operation).effect})
                hook(f'intent:{node.id}')
                if node.operation == 'inputs.snapshot':
                    blobs = self._read_sources(input_root, plan, check_budget)
                    hashes = {n: digest(b) for n, b in blobs.items()}
                    if hashes != oracle.get('input_hashes'):
                        raise RuntimeFault('ORACLE_MISMATCH', '输入版本与所有者预期不匹配。')
                    snap = checked_path(workspace / 'snapshots')
                    snap.mkdir(exist_ok=True)
                    _directory_names(snap, set(hashes))
                    for name, blob in blobs.items():
                        policy.check(node.operation)
                        check_budget()
                        ensure_file(snap / name, blob, code='SNAPSHOT_CHANGED')
                        hook(f'snapshot_file:{name}')
                    ensure_file(workspace / 'input_manifest.json', json_bytes(hashes), code='SNAPSHOT_CHANGED')
                    receipt = {'hashes': hashes}
                elif node.operation == 'tabular.aggregate':
                    result = aggregate(blobs, plan.limits.max_rows)
                    checkpoint = json_bytes(result)
                    if len(checkpoint) > plan.limits.max_artifact_bytes:
                        raise RuntimeFault('ARTIFACT_BUDGET', '汇总检查点超过产物预算。')
                    folder = checked_path(workspace / 'checkpoints')
                    folder.mkdir(exist_ok=True)
                    _directory_names(folder, {'aggregate.json'})
                    ensure_file(folder / 'aggregate.json', checkpoint, code='CHECKPOINT_CHANGED')
                    receipt = {'sha256': digest(checkpoint), 'bytes': len(checkpoint)}
                    hook('aggregate_saved')
                elif node.operation == 'artifacts.export':
                    if result is None:
                        raise RuntimeFault('CHECKPOINT_INVALID', '缺少可用汇总结果。')
                    artifacts = {'summary.json': json_bytes({k: v for k, v in result.items() if k != 'errors'}),
                                 'errors.json': json_bytes(result['errors']), 'summary.csv': summary_csv(result['groups'])}
                    if sum(map(len, artifacts.values())) > plan.limits.max_artifact_bytes:
                        raise RuntimeFault('ARTIFACT_BUDGET', '产物超过预算。')
                    if output.exists():
                        raise RuntimeFault('UNKNOWN_EFFECT', '导出尚未记账但交付目录存在，停止核对。')
                    checked_path(staging).mkdir(exist_ok=True)
                    _directory_names(staging, ARTIFACTS)
                    for name, data in artifacts.items():
                        policy.check(node.operation)
                        check_budget()
                        ensure_file(staging / name, data)
                        artifact_manifest[name] = {'sha256': digest(data), 'bytes': len(data)}
                        hook(f'export_file:{name}')
                    receipt = {'artifacts': artifact_manifest.copy()}
                else:
                    current_root = local_root()
                    persisted = _validate_artifacts(current_root, artifact_manifest, plan.limits.max_artifact_bytes)
                    final_hashes = {n: digest(b) for n, b in self._read_sources(input_root, plan, check_budget).items()}
                    report = verify(persisted['summary.json'], persisted['errors.json'], persisted['summary.csv'],
                                    oracle, hashes, final_hashes)
                    if plan.contract is not None and report['validator'] != plan.contract.acceptance:
                        raise RuntimeFault('ACCEPTANCE_MISMATCH',
                                           '验收标准与实际核验器不一致，不能按合同交付。')
                    report_blob = json_bytes(report)
                    if sum(v['bytes'] for v in artifact_manifest.values()) + len(report_blob) > plan.limits.max_artifact_bytes:
                        raise RuntimeFault('ARTIFACT_BUDGET', '核验报告加产物超过预算。')
                    ensure_file(current_root / 'verification.json', report_blob)
                    artifact_manifest['verification.json'] = {'sha256': digest(report_blob), 'bytes': len(report_blob)}
                    if not report['passed']:
                        raise RuntimeFault('VERIFICATION_FAILED', '产物未通过独立核验，未交付为成功结果。')
                    receipt = {'artifacts': artifact_manifest.copy(), 'verification': report}
                    if prepared is not None and prepared != receipt:
                        raise RuntimeFault('PUBLICATION_CHANGED', '待交付结果与原提交意图不同。')
                    journal.prepare(run_id, receipt)
                    prepared = receipt
                    hook('publication_prepared')
                    policy.check(node.operation)
                    check_budget()
                    check_sources()
                    if not output.exists():
                        sync_directory(staging)
                        os.rename(staging, output)
                        sync_directory(workspace)
                        hook('publication_renamed')
                journal.complete(run_id, node.id, operation_id, receipt)
                executed.append(node.id)
                hook(f'node_committed:{node.id}')
                if after_node:
                    after_node(node.id, workspace)
            check_sources()
            policy.check(plan.nodes[-1].operation)
            check_budget()
            status = 'SUCCEEDED'
        except KeyboardInterrupt:
            error_code, status = 'INTERRUPTED', 'INTERRUPTED'
        except RuntimeFault as exc:
            error_code = exc.code
            status = 'CANCELLED' if exc.code == 'CANCELLED' else 'FAILED'
        except Exception:
            error_code, status = 'INTERNAL_ERROR', 'FAILED'

        record = {'schema_version': 'aor.run-record.v0.2', 'run_id': run_id, 'plan_hash': plan.plan_hash,
                  'status': status, 'error_code': error_code, 'elapsed_seconds': perf_counter() - started,
                  'elapsed_scope': 'current_attempt_only; crash time is not reconstructed',
                  'input_files': len(hashes), 'attempt': state['attempts'],
                  'metrics': {'live_model_calls': 0, 'input_tokens': None, 'output_tokens': None,
                              'model_cost': None, 'model_measurement': 'not_run',
                              'executed_nodes': executed, 'reused_nodes': reused, 'reconciled_nodes': reconciled},
                  'artifacts': artifact_manifest,
                  'acceptance': (None if plan.contract is None else {
                      'contract_sha256': digest(plan.contract.model_dump_json().encode()),
                      'verifier_engine': engine_fingerprint(),
                      'validator': report['validator'] if report else None,
                      'input_version': digest(json_bytes(hashes)),
                      'unresolved': list(plan.contract.unresolved),
                      'human_judgment': list(plan.contract.human_judgment),
                  }),
                  'artifact_state': ('verified_outputs' if status == 'SUCCEEDED' else
                                     'published_unconfirmed' if output.exists() else 'not_delivered'),
                  'verification': report,
                  'recovery': {'supported': 'explicit_local_fixture_only', 'resumed': resumed,
                               'max_attempts': MAX_ATTEMPTS, 'attempt_seconds_limit': plan.limits.max_seconds}}
        journal.finish(run_id, status, error_code, record=record)
        hook('run_committed')
        atomic_json(workspace / 'run.json', record)
        hook('record_written')
        return record
