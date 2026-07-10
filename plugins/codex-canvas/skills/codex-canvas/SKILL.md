---
name: codex-canvas
description: Maintain a phase-level checkpoint canvas for the current Codex conversation. Use for conversation maps, checkpoint summaries, canvas review, selected-context assembly, or when the user asks to open or update the conversation canvas.
---

# 对话画布

把当前 Codex 对话沉淀成一张独立画布。一个节点代表一个小话题或阶段，不代表单条消息。

## 不可改变的边界

- 画布不修改 Codex 记忆、系统提示或内部上下文。
- 连线只表达检查点关系，并决定底部组装区的默认顺序。
- 画布不自动向 Codex 客户端发送消息。
- checkpoint 节点属于对话记录，界面不允许删除；位置、连线和组装顺序可以调整。
- `rawText` 只保存必要的短证据，主要内容使用 `detailMarkdown` 和 `contextText`。

## 先确定运行模式

### 1. 已从对话开始静默记录

继续复用当前对话固定的 session-id。阶段完成时直接调用 `checkpoint.py`，不要重建历史，也不要为了记录一个节点加载或扫描完整对话。

### 2. 已经聊了一段时间，首次启用画布

优先使用当前 Agent 已经拥有的对话上下文，一次性总结历史节点：

1. 判断实际存在多少个有意义阶段，不设固定数量。
2. 短对话可以只有 1 个节点；长对话默认最多 8 个。
3. 每个阶段写一个 `origin=reconstructed` 节点。
4. 使用一次批量 JSON 写入，避免逐节点重复调用和重复总结。
5. 历史节点写完后，再进入正常 `live` checkpoint。

不要先创建空洞的“画布启用”占位节点。不要把当前 Agent 能直接总结的内容再次交给离线脚本总结。

### 3. 当前上下文确实不足

仅在需要回看历史、且当前 Agent 无法可靠总结时，才运行 `conversation_anchor.py` 或 `transcript_recovery.py`。离线来源必须能通过当前 session、项目目录或相关文件可靠匹配；匹配不可靠时宁可不补。

## 什么时候提交节点

满足任一条件时提交一个 checkpoint：

- 产品目标或需求已经确认或改变。
- 一个小话题得出结论。
- 方案、计划或取舍已经确定。
- 实现或重要文件修改已经完成。
- 验证完成并有明确结果。
- 出现需要保留的阻塞、风险或未决问题。

快速澄清、纯状态回复、细小文案调整不生成节点。同一阶段的连续实现和修复应合并成一个完整节点。

## 节点内容

每个节点至少包含：

- `type`：`anchor`、`requirement`、`decision`、`plan`、`implementation`、`verification`、`blocker`、`artifact`、`note`。
- `title`：简短可扫描的阶段名。
- `summary`：1 到 3 句阶段结论。
- `detailMarkdown`：结构化详情，可包含标题、列表、风险、验证和下一步。
- `contextText`：给底部组装区使用的压缩上下文，明显短于完整对话。
- `source`：`user`、`assistant` 或 `mixed`。
- `origin`：正常记录用 `live`，首次回看用 `reconstructed`。
- `confidence`：`high`、`medium` 或 `low`。
- `relatedFiles`、`evidenceRefs`、`tags`：有内容时再写。

## 脚本路径

从当前 `SKILL.md` 所在目录向上两级确定插件根目录。脚本位于 `<plugin-root>/scripts/`。不要把当前工作目录误当作插件目录。

## 写一个实时节点

```powershell
python "<plugin-root>\scripts\checkpoint.py" --session "<固定-session-id>" --auto-link --type "verification" --title "验证完成" --summary "核心交互已经通过回归。" --detail-markdown "## 验证`n- 结果一`n- 结果二" --context-text "当前阶段已完成验证，可继续下一步。" --origin live --confidence high
```

默认使用 `--auto-link`。只有节点明确独立时才省略。

## 首次批量写入历史节点

`checkpoint.py --stdin-json` 同时接受 `session/checkpoints` 和 `sessionId/nodes`：

```powershell
$payload = @{
  sessionId = "<固定-session-id>"
  autoLink = $true
  nodes = @(
    @{
      type = "requirement"
      title = "确认目标"
      summary = "用户确认了本次工作的核心目标。"
      detailMarkdown = "## 已确认`n- 目标`n- 边界"
      contextText = "核心目标和边界的压缩说明。"
      source = "mixed"
      origin = "reconstructed"
      confidence = "high"
    }
  )
} | ConvertTo-Json -Depth 8 -Compress

$payload | python "<plugin-root>\scripts\checkpoint.py" --stdin-json
```

## 打开画布

```powershell
python "<plugin-root>\scripts\canvas_server.py" --session "<固定-session-id>" --open
```

返回脚本实际输出的 URL。默认端口为 `8765`；端口被占用时服务会选择其他可用端口。每个对话通过 `?session=<session-id>` 隔离，不会互相覆盖。

## 回复纪律

- 静默模式下，成功记录后不要提示“已写入画布”。
- 记录失败、来源不可靠、session-id 无法确定，或用户主动询问画布状态时才说明。
- 用户要求“打开画布 / 看画布 / 给我链接”时，启动服务并返回精确 URL。
- 默认用中文解释。
