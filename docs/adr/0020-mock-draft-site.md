# ADR 0020：本地模拟草稿站（第三任务族）

状态：已实施（ADP-005）。对应路线图"本地模拟草稿流程：mock 草稿站与填写/读回/导出动作"。

## 决定

新增 `drafts.mock_flow`：对快照内每个 brief 文件按 `draft_key = sha256(title + ':' + body_sha256)` 在任务工作区的 `mock_site/drafts/` 幂等建稿并回读核验。

- mock 站点是工作区内目录，不是外部系统：无账号、无外网、无付费模型——满足"v0 只允许项目内副本与本地 mock 草稿"的安全边界。
- 幂等语义：key 绑定内容哈希；同 key 同内容 → 复用，同 key 异内容 → `DRAFT_CHANGED` 失败关闭。checkpoint 结果不含 run 依赖字段，保证 reconcile 重跑确定性。
- 产物：`draft_manifest.json` + `drafts.csv`；核验器 `fixture_drafts_mock.v1` 从 oracle 字段独立重建期望键与 CSV。
- 输入规则族化 `SAFE_BRIEF`（.txt/.md）；oracle schema `aor.fixture-oracle-drafts.v0.1`。

## 边界

真实草稿系统（有状态服务、权限、版本并发）未实现；这是"幂等+回读+独立核验"语义的可测替身，不是浏览器或 CMS 集成。
