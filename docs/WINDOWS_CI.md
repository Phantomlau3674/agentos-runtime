# Windows GitHub CI

PR #1 GitHub `windows-latest` 3.11 / 3.13 jobs failed on `tests/test_gateway.py::test_actual_cli_agent_round_trip_and_restart`. Ubuntu jobs and the native Windows 3.12.14 controller run (161 passed, 5 skipped) did not show this failure. Crash / `taskkill` tests passed on GitHub; they are not the CI cause.

## Cause

`python -m agentos_runtime tools` prints tool JSON with Chinese descriptions using `ensure_ascii=False`. GitHub Windows runners use the English locale (`cp1252`) and do not set `PYTHONUTF8`. `sys.stdout` is strict, so `print` raises `UnicodeEncodeError`. That exception subclasses `ValueError`, so the CLI reported `CONFIG_OR_IO_ERROR` on stderr and left stdout empty. The test then did `json.loads('')`.

`sys.stderr` uses `backslashreplace`, so rejection JSON and malformed-request tests still returned 2. The developer machine hid this because the environment has `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`.

`init-demo` succeeded: its JSON is ASCII.

## Fix

The CLI forces UTF-8 stdio before argparse. Subprocess tests decode UTF-8 and assert the `tools` return code. A regression test runs `tools` with `PYTHONUTF8=0` and `PYTHONIOENCODING=cp1252` and requires UTF-8 JSON.

Do not set `PYTHONUTF8` in GitHub Actions to paper over locale-sensitive CLI output.

## Remaining

Five existing Windows link / privilege cases stay skipped. Local notes of intermittent `taskkill` timeout and gateway `INTERNAL_ERROR` are preserved; GitHub crash tests passed, so those are not treated as this job's failure.
