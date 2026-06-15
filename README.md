# 对话画布SKILL

对话画布SKILL 是一个 Codex 本地插件原型。它把当前 Codex 对话沉淀成一张类似 n8n 的阶段检查点画布：节点代表小话题、小阶段、关键决策、实现结果或验证结果，连线代表这些检查点在“组装下一次输入”时的关系。

内部插件 slug 保持为 `codex-canvas`，这是为了满足 Codex 插件的稳定命名和兼容要求；对外展示名为“对话画布SKILL”。

## 能做什么

- 每个 Codex 对话对应一张独立画布。
- 自动或手动记录阶段 checkpoint 节点。
- 在画布上查看节点摘要、结构化详情、标签、相关文件和证据来源。
- 拖动节点、框选节点、调整连线、删除连线、重连连线。
- “还原画布”可撤销，撤销栈保留最近 40 步。
- 选中节点后组装成一段可复制的上下文，粘贴回 Codex 输入框。

## 不做什么

- 不修改 Codex 记忆。
- 不修改 Codex 原生上下文。
- 不直接控制 Codex 客户端输入框。
- 连线不会改变 Codex 内部推理，只影响插件里的输入框组装顺序。
- 不把每一句对话都变成节点，只记录阶段级检查点。

## 项目结构

```text
.agents/plugins/marketplace.json
plugins/codex-canvas/
  .codex-plugin/plugin.json
  assets/canvas/
  commands/
  data/schema.json
  scripts/
  skills/codex-canvas/
```

## 本地启动

```powershell
python .\plugins\codex-canvas\scripts\canvas_server.py --session demo --open
```

打开地址：

```text
http://127.0.0.1:8765/?session=demo
```

## 手动写入 checkpoint

```powershell
$detail = @"
## 决策
- 节点代表阶段检查点
- 连线只用于组装可复制上下文
"@

$context = "当前阶段：已经确认节点、连线和输入框组装的产品边界。"

python .\plugins\codex-canvas\scripts\checkpoint.py --session demo --auto-link --type decision --title "确定边界" --summary "节点代表阶段检查点，连线只用于组装输入。" --detail-markdown $detail --context-text $context --origin live --confidence high
```

## 安装到 Codex

这个仓库自带本地 marketplace：

```text
.agents/plugins/marketplace.json
```

在 Codex 里安装时，把该 marketplace 指向仓库根目录即可。插件内部名称是：

```text
codex-canvas
```

在仓库根目录执行：

```powershell
codex plugin marketplace add .
```

## 验证命令

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'

python C:\Users\1\.codex\skills\.system\skill-creator\scripts\quick_validate.py .\plugins\codex-canvas\skills\codex-canvas
python C:\Users\1\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py .\plugins\codex-canvas
python .\plugins\codex-canvas\scripts\canvas_regression.py
```

## 当前版本

以 `plugins/codex-canvas/.codex-plugin/plugin.json` 里的 `version` 为准。

## 数据兼容原则

- 画布 session 是用户资产。
- 插件升级不能默认破坏节点、连线、布局和输入框组装顺序。
- 数据结构版本使用 `schemaVersion`，和插件版本分开。
- 旧 session 迁移前会生成备份。
- 旧数据无法判断创建插件版本时，`createdByPluginVersion` 写 `unknown`。

## 许可证

当前未指定开源许可证。发布到 GitHub 后，如果要允许别人复制、修改或再发布，需要单独补充 LICENSE。
