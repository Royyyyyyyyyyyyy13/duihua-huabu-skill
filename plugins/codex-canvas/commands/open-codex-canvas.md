# /open-codex-canvas

打开当前 Codex 任务对应的对话画布。

## 参数

- `session`：可选。优先复用当前任务已经确定的固定 session-id；没有时按日期和主题创建可读 id。

## 执行

1. 从当前 Skill 文件位置确定插件根目录，不使用当前工作目录猜路径。
2. 已经从任务开始记录时直接复用现有 session，不重新总结历史。
3. 首次在旧任务中启用时，先按 Skill 规则基于当前上下文批量生成必要节点。
4. 运行：

```powershell
python "<plugin-root>\scripts\canvas_server.py" --session "<session-id>" --open
```

5. 返回脚本实际输出的本地 URL。端口可能不是 8765。
