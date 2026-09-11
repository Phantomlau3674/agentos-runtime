# Windows takeover validation

Scope: GOV-003 (native environment), REC-001/REC-002 (crash-test execution), existing gateway input validation. No production interfaces, runtime locking/recovery semantics, dependency pins, or default time limits changed.

The v0.0.2 handoff archive hash matches `7e27ced3c6e57c9aa2bcca17c5375713087fd39343c3fcc821d9778ee93ead5b`. All 18 source/test files matched the imported snapshot after normalizing Git line endings. Historical `reports/` referenced by the cloud handoff are not included in that snapshot; they are not claimed recovered.

Native Windows/Python 3.12.14 baseline: 153 passed, 7 failed, 5 skipped, 2 setup/teardown errors. Setup/teardown errors were the same oversized parametrized test; the suite contains 166 cases.

Fixes:

- Short explicit pytest parameter IDs keep the actual 65,537-byte oversized payload, avoiding Windows' environment-variable length limit.
- UTF-8 is explicit when modifying the UTF-8 plan fixture on a GBK-default machine.
- `bad name.csv` is creatable on Windows but invalid under the same runtime filename policy, so the test reaches the intended rejection.
- Windows venv Python uses a launcher process. A real PID probe confirmed that killing just the launcher left the interpreter alive and holding the lock. Crash tests now terminate the live owned tree with `taskkill /F /T`, check its result, and wait. They do not delete lock files or sweep dead parent PIDs. Live-worker exclusion and post-death recovery assertions remain.
- The 1000-file correctness fixture declares the schema-supported 300-second budget. The runtime default remains 60 seconds; timeout enforcement tests remain unchanged. This is not a performance claim.

Validation command (choose a fresh basetemp on each run):

```powershell
.\.venv\Scripts\python.exe -m pytest -q -W error::ResourceWarning -o cache_dir=.local/native-cache --basetemp=.local/native-final-2 --junitxml=.local/windows-final.xml
```

Final controller run on 2026-09-11: **161 passed, 5 skipped, 0 failures, 0 errors, no warnings in 127.58 seconds**. Separately, the native CLI completed a 100-file / 1000-row synthetic task, verified its outputs independently, deduplicated the repeated request, and read the JSON artifact through pagination. No model was called by that runtime demo.

Windows crash tests require a process environment that permits terminating its own test worker tree. Codex's restricted process sandbox rejected `taskkill`; the native account run used project-local temp/cache directories to avoid cross-account pytest cache ownership conflicts. No system ACLs or security settings were changed.

Remaining limitations: five existing Windows link/FIFO/privilege cases are skipped. Intermediate native runs observed one taskkill timeout and one gateway INTERNAL_ERROR; both passed isolated rechecks, so retain the failed evidence and do not infer the machine is free of intermittent failures. MCP and real-agent runtime integration remain outside this change.

Devin SWE-2 Max produced the initial test edits; Codex corrected process-cleanup scope and performs integration verification; AGY Gemini 3.8 Flash independently reviewed the bounded patch. Provider self-reports are not runtime acceptance.
