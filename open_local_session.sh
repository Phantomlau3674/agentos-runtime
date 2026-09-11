#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v codex >/dev/null 2>&1; then
  printf '%s\n' 'Codex CLI not found. No installation or settings changes were made.' 'Open this folder in your coding agent and ask it to read LOCAL_SESSION_START.md.' >&2
  exit 1
fi
exec codex 'Read AGENTS.md and LOCAL_SESSION_START.md. Continue this project as a new development session. Inspect code and test evidence first. Do not publish remotely, access private accounts, or run paid model benchmarks without explicit configuration and authorization. Explain progress in Chinese.'
