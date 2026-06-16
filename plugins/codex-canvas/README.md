# 对话画布SKILL

对话画布SKILL 是一个本地 Codex 插件原型，内部插件 slug 为 `codex-canvas`：每个 Codex 对话可以对应一张独立画布，画布里不是每句话一个节点，而是把“小话题 / 小阶段 / 关键决策 / 实现结果 / 验证结果”记录成 checkpoint 节点。

它不修改 Codex 记忆，不修改 Codex 原生上下文，也不接管 Codex 的推理机制。连线和选择节点只用于把相关内容组装成下一次要粘贴给 Codex 的输入文本。

## 包含内容

- `skills/codex-canvas/SKILL.md`：让 Codex 判断什么时候该提交 checkpoint。
- `scripts/checkpoint.py`：把 checkpoint 写入当前画布会话的数据文件。
- `scripts/canvas_server.py`：启动本地画布服务。
- `assets/canvas/`：n8n 风格的本地画布页面。
- `commands/open-codex-canvas.md`：打开画布的 Codex 命令说明。
- `data/schema.json`：节点和连线数据结构。

## 使用方式

启动画布：

```powershell
python .\plugins\codex-canvas\scripts\canvas_server.py --session demo --open
```

手动写入一个 checkpoint：

```powershell
$detail = @"
## 决策
- 不做历史来源
- 不修改 Codex 记忆或内部上下文
- 连线只用于组装输入框
"@

$context = "当前决策：每个对话窗口一张独立画布；节点代表阶段检查点；连线只用于组装可粘贴回 Codex 的输入内容，不修改 Codex 记忆。"

python .\plugins\codex-canvas\scripts\checkpoint.py --session demo --auto-link --type decision --title "确定 MVP 范围" --summary "每个对话窗口一张画布，节点代表阶段检查点，连线只用于组装输入框。" --detail-markdown $detail --context-text $context
```

默认优先写 `detailMarkdown` 和 `contextText`。`rawText` 只作为短原文证据使用，不作为主要节点内容。

首次在已经进行中的对话里启用画布时，如果画布为空，或者只存在“画布启用”锚点及少量后续 live 节点，插件会先尝试从本机可读 Codex 会话记录里生成回溯节点。没有可靠来源时不会乱补节点；已经存在 `reconstructed` 节点后不会重复回溯。

如果用户在全局 `AGENTS.md` 或当前对话里要求“静默启用画布”，Skill 会继续记录 checkpoint，但不会在每次成功写入后提示用户。只有记录失败、出现阻塞，或用户主动询问画布状态时，才说明画布状态。

然后打开：

```text
http://127.0.0.1:8765/?session=demo
```

## 安装和更新提示

本地开发时，插件清单在 `.codex-plugin/plugin.json`，Skill 在 `skills/codex-canvas/SKILL.md`。修改插件后需要更新 cachebuster 并重新安装插件；Codex 通常要在新线程里才会稳定拾取新的 Skill 描述和插件元数据。

这个仓库里的 `.agents/plugins/marketplace.json` 是项目内本地 marketplace 示例。如果要放到个人 Codex 环境里，使用个人 marketplace 时不要手改 Codex 配置，优先走插件更新脚本和重新安装流程。

## 已固化状态

当前 MVP 已按 Codex Skill/插件规则完成固化检查。固化版本以 `.codex-plugin/plugin.json` 当前 `version` 为准。

固化验收范围：

- Skill frontmatter、`agents/openai.yaml`、插件 manifest、marketplace 指向。
- 画布服务、节点/连线数据、输入框组装、节点详情、基础 UI 交互回归。
- 无 Python 运行缓存、无乱码残留、无旧英文示例残留。

复验命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
python C:\Users\1\.codex\skills\.system\skill-creator\scripts\quick_validate.py .\plugins\codex-canvas\skills\codex-canvas
python C:\Users\1\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py .\plugins\codex-canvas
python .\plugins\codex-canvas\scripts\canvas_regression.py
```

## 版本兼容原则

画布 session 是用户资产，插件升级不能默认破坏节点、连线、布局和输入框组装顺序。

当前数据层会写入：

- `schemaVersion`：画布数据结构版本，和插件版本分开。
- `createdByPluginVersion`：首次创建该 session 的插件版本；旧数据无法判断时写 `unknown`，不伪装成当前版本。
- `lastOpenedByPluginVersion`：最近一次打开/迁移该 session 的插件版本。
- `origin`：节点来源，支持 `live`、`reconstructed`、`imported`。
- `confidence`：节点可信度，支持 `high`、`medium`、`low`。

旧 session 被新版本打开时，会先生成一份 `schema-*-backup-*` 备份，再补齐兼容字段。后续大版本升级必须继续遵守：优先增字段，不随意改旧字段含义；迁移前备份；迁移后跑回归。

## 当前边界

Codex 插件目前可以打包 Skill、脚本、资产、App 连接器等能力。这个插件把画布作为本地 Web App 放进插件资产里，通过本地服务打开。它不会直接修改 Codex App 的原生聊天窗口 UI；底部“组装输入框”会生成可复制文本，用于粘贴回 Codex 输入框。
