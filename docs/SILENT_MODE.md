# 静默模式

Codex 插件安装过程不会自动修改用户的全局 `AGENTS.md`。需要每个新任务从第一轮开始记录画布时，在 `~/.codex/AGENTS.md` 添加一条轻量规则。

先把下面的 `<checkpoint.py 绝对路径>` 和 `<canvas_server.py 绝对路径>` 改成当前插件源码目录中的真实路径：

```text
对话画布默认静默启用。每个新 Codex 任务从首个明确需求开始，为当前任务确定一个固定 session-id，并直接运行 python "<checkpoint.py 绝对路径>" 记录一个 live 起点 checkpoint。后续只在阶段完成、决策确认、实现完成、验证完成或出现阻塞时追加一个 checkpoint；不要每句话都记录。优先写 detailMarkdown 和 contextText，rawText 只保存必要短证据。成功记录时保持静默；失败或我要求看画布时再说明。当前任务已经从开始记录时，不要重新回溯历史。我要打开画布时，运行 python "<canvas_server.py 绝对路径>" --session "<本任务固定 session-id>" --open，并返回实际 URL。画布不修改 Codex 记忆或内部上下文。
```

## 这样设置的原因

- 新任务只调用轻量 `checkpoint.py`，无需预先加载完整画布 Skill。
- 同一个任务始终复用一个 session-id，不会每轮重建。
- 想看画布时才启动 Web 服务。
- 插件目录移动后，需要同步更新两个绝对路径。

显式使用 `$codex-canvas` 仍可随时打开画布、首次总结旧任务或读取完整规则。
