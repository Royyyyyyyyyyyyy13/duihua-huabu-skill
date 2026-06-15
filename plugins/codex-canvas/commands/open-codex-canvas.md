# /open-codex-canvas

打开当前 Codex 对话对应的 Codex Canvas。

## 参数

- `session`：可选画布会话 id。没传时，优先使用当前对话已经确定的 session；如果还没有，就按日期和主题创建一个可读 id。

## 工作流程

1. 确认当前对话的画布 session id。
2. 运行 `python .\plugins\codex-canvas\scripts\canvas_server.py --session "<session>" --open`。
3. 把本地 URL 告诉用户。
4. 后续继续按 `codex-canvas` 的 checkpoint 规则记录这个对话。
