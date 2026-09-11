# Coding-agent instructions

Read PROJECT_PLAN.zh-CN.md, docs/FIRST_CODING_SPRINT.md, docs/SECURITY.md and the relevant task in planning/backlog.json before implementation. Chinese user-facing explanations; identifiers and public API names in English.

## Work contract

- Read STATUS.md and reports/ before making claims. A narrow offline fixture spike now exists; the full platform and integrations are still planned. Never claim CI, benchmarks, remote pushes, approvals or support that have not occurred.
- Implement one vertical slice per change. Resolve task dependencies. Update status only with test evidence; a generated file is not a completed feature.
- Recheck upstream docs and pin selected versions. Do not copy code from unclear-license sources. Preserve required license notices for any copied code.
- Do not change public API or recovery semantics silently. Add or update an ADR and the affected tests.
- Use synthetic fixtures only. Do not publish private conversation text, personal accounts, credentials, browser profiles or real business records.

## Safety invariants

- No untrusted generated code, eval, unrestricted shell, remote script installers or arbitrary plugins in the v0 host process.
- Every managed action passes the broker. Resolve inputs, validate types, check resource scope/version/quota and current policy immediately before each action.
- Default deny destructive/external effects. v0 allows only project-scoped copies and local mock-site drafts.
- Do not expose an agent-callable approve tool. Human approvals bind principal, plan hash, resolved effects, object versions and expiry. Changed scope invalidates the approval.
- A task checkpoint does not roll back external effects. Ambiguous completion becomes unknown_effect; reconcile before retry.
- Never label trusted-local adapters as a secure sandbox against malicious host code. External shell access remains outside this runtime's boundary.
- Do not disable confirmations, security tests, gates or network restrictions to make a demo succeed.

## Quality and measurement

- Test schemas, invalid inputs, task transitions, crash windows, version conflicts, retries, resource exhaustion and cancellations—not just happy paths.
- Independently validate outputs. Use decimal arithmetic rules for decimal data; record exact input hashes.
- Keep A/B/C baselines fair. Same model configuration, adapters, tasks and permissions where possible. Publish unsuccessful runs and retry costs.
- No claims such as 10x faster, production-ready, zero-risk, universal rollback, exactly-once external writes without the corresponding bounded evidence.
- Offline tests first; live providers require explicit configuration and budget. Tests cannot unexpectedly spend money.

## Handoff

Each implementation change must state task IDs, modified interfaces, tests actually run, tests not run and why, residual risk, and the next runnable step. Do not instruct a nontechnical user to edit source code as the normal path.

## Cloud-first continuation

Default to cloud implementation and automated tests in the current tool environment. The optional local-session launchers are not required of the nontechnical owner. Read LOCAL_SESSION_START.md for v0.0.2 handoff. Preserve failed-test evidence, but distinguish it from the final passing suite. A transport-neutral JSON CLI is not MCP; scripted process tests are not a live-model integration test. Do not disable Chromium sandboxing to turn an environmental blocker into a passing browser test.
