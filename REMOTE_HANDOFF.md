# Remote handoff verification

This public repository was populated from the verified v0.0.2 source snapshot on 2026-09-11.

- Source archive SHA-256: `7e27ced3c6e57c9aa2bcca17c5375713087fd39343c3fcc821d9778ee93ead5b`
- Imported source commit: `993d8e8a8f8d731715cdcc12f54a05bbc011a3d2`
- Local pre-handoff verification: 166 tests passed on Linux / Python 3.13.5.
- Remote CI is the authoritative check for clean GitHub-hosted Ubuntu/Windows environments after this commit.

Scope note: v0.0.2 contains the bounded runtime, crash reconciliation/recovery, request de-duplication, JSON CLI Agent gateway, cancellation, artifact reads, event pagination and diagnostics. Standard MCP transport, real Codex/Claude capability regression, Windows product packaging, Office/Blender adapters and production browser-account automation remain unverified and are not claimed complete.
