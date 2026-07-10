# 对话画布SKILL 2.0

内部插件名为 `codex-canvas`。它为每个 Codex 任务维护一张独立的阶段检查点画布。

## 运行内容

- `skills/codex-canvas/SKILL.md`：节点判断、首次历史总结和静默记录规则。
- `scripts/checkpoint.py`：单个或批量写入 checkpoint。
- `scripts/canvas_server.py`：本机画布服务和 API。
- `scripts/canvas_store.py`：schema 2、迁移、文件锁和原子写入。
- `assets/canvas/`：预构建的 Vue Flow 画布。
- `frontend/`：Vue 3 前端源码。
- `data/schema.json`：数据结构说明。

## 打开画布

```powershell
python "<plugin-root>\scripts\canvas_server.py" --session "<session-id>" --open
```

默认地址为 `http://127.0.0.1:8765/?session=<session-id>`。同一服务可通过不同 session 参数打开多张独立画布。

## 写入 checkpoint

```powershell
python "<plugin-root>\scripts\checkpoint.py" --session "<session-id>" --auto-link --type verification --title "验证完成" --summary "核心流程已经通过。" --detail-markdown "## 验证`n- 交互通过" --context-text "当前阶段验证完成。" --origin live --confidence high
```

默认优先写 `detailMarkdown` 和 `contextText`。`rawText` 只保存短证据。

## 首次启用

已经进行一段时间的任务首次启用时，当前 Codex Agent 应直接根据现有上下文总结阶段节点，并通过 `--stdin-json` 一次批量写入。离线会话匹配只在当前上下文不足时兜底。

## 边界

- 不修改 Codex 记忆或内部上下文。
- 不向 Codex 客户端自动发送消息。
- 连线只影响画布关系和组装顺序。
- 节点不可删除，布局和连线可编辑。

## 验证

```powershell
npm --prefix .\frontend ci
npm --prefix .\frontend run build
npm --prefix .\frontend test

$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python .\scripts\canvas_regression.py
```

插件升级会保留旧 session，并在 schema 迁移前生成备份。

## 许可证

项目使用 [MIT License](LICENSE)。生产依赖的完整许可证清单与原文见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
