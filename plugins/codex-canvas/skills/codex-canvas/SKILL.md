---
name: codex-canvas
description: Record phase-level checkpoints for the current Codex conversation in a n8n-style canvas. Use when the user asks for Codex Canvas, conversation maps, checkpoint nodes, automatic phase summaries, or prompt assembly from selected checkpoints.
---

# Codex Canvas

Use this skill to keep a per-thread checkpoint canvas for the current Codex conversation.

## Core Rule

Automatically create a checkpoint when a meaningful phase is complete. Do not create one for every message.

This is mandatory behavior for this skill. Do not wait for the user to ask "record this" after a phase has clearly finished. If the canvas session is known and the work produced a decision, implementation, verification, blocker, or resolved subtopic, record the checkpoint before the final reply for that turn.

A checkpoint is appropriate when one of these happens:

- The user establishes or changes the product goal.
- A small topic or stage has been resolved.
- A key decision has been made.
- A plan has been accepted or replaced.
- A file or artifact has been created or materially changed.
- A verification step has completed.
- A blocker or open question has been identified.

When the canvas is empty but the current Codex conversation is already underway, reconstruct only the useful amount of history before normal live checkpointing begins.

Do not force a minimum number such as 3 reconstructed nodes. Choose the count from the actual amount of meaningful prior conversation:

- If there is no reliable prior context, create no reconstructed node and let the next real checkpoint start the canvas.
- If there is only one small topic, create one `anchor` or one reconstructed checkpoint.
- If there are a few clear phases, create one node per phase.
- If there is a long conversation, create enough nodes to preserve the major product decisions, implementation stages, verification results, and unresolved questions, capped at 8 by default.

Reconstructed nodes must be honest summaries, not fake originals. Leave `rawText` empty unless there is a short exact excerpt worth preserving. Use `detailMarkdown` for structured history and `contextText` for compact prompt assembly.

## What A Checkpoint Contains

Each checkpoint must have:

- `type`: one of `anchor`, `requirement`, `decision`, `plan`, `implementation`, `verification`, `blocker`, `artifact`, `note`.
- `title`: short title, ideally 4 to 12 Chinese characters or a concise phrase.
- `summary`: 1 to 3 sentences explaining the stage.
- `detailMarkdown`: human-readable structured detail. Prefer sections such as `已确认`, `正在讨论`, `决策`, `风险`, `下一步`.
- `contextText`: compressed context used when assembling content back into Codex. Keep this much shorter than raw dialogue.
- `source`: `user`, `assistant`, or `mixed`.
- `origin`: `live`, `reconstructed`, or `imported`. Use `live` for normal checkpoints after the canvas is enabled. Use `reconstructed` for old-conversation catch-up nodes.
- `confidence`: `high`, `medium`, or `low`, based on how much reliable context supports the node.
- `relatedFiles`: files touched or discussed, if any.
- `evidenceRefs`: optional source references, local files, or message ranges that can be used for review.
- `tags`: short labels.

`rawText` is optional evidence. Do not use it as the primary node content unless the user explicitly asks to preserve original excerpts.

## Session Rule

For each Codex conversation, maintain one canvas session id. If the user does not provide one, create a readable id using the date and topic, for example:

```text
20260611-codex-canvas-mvp
```

Use the same session id for all later checkpoints in this conversation.

## Recording Checkpoints

When a checkpoint should be recorded, run:

```powershell
python .\plugins\codex-canvas\scripts\checkpoint.py --session "<session-id>" --auto-link --type "<type>" --title "<title>" --summary "<summary>" --detail-markdown "<structured detail>" --context-text "<compressed context>" --origin live --confidence high
```

Add repeated `--tag` and `--related-file` values when useful.

Use `--auto-link` by default so the new checkpoint is connected from the previous checkpoint. Only omit it when the user explicitly asks for an unconnected node or when the node is intentionally standalone.

Only add `--raw-text` when preserving a short original excerpt is explicitly useful as evidence. Raw text is not the default storage path.

## Auto Checkpoint Discipline

At the end of each substantial turn:

1. Decide whether the turn completed a meaningful phase.
2. If yes, record exactly one checkpoint summarizing that phase.
3. Include `detailMarkdown` for the right panel and `contextText` for prompt assembly. Keep `contextText` concise.
4. Use `source=mixed` when both user feedback and assistant implementation shaped the phase.
5. Use `origin=live` for normal new checkpoints.
6. Mention briefly in the final response that a checkpoint was recorded.

Do not create a checkpoint for quick clarifications, pure status replies, or tiny wording-only answers.

## Opening The Canvas

To open the canvas for a session, run:

```powershell
python .\plugins\codex-canvas\scripts\canvas_server.py --session "<session-id>" --open
```

If a server is already running, use the printed URL:

```text
http://127.0.0.1:8765/?session=<session-id>
```

## Important Boundaries

- Do not change Codex memory.
- Do not claim that edges modify Codex internal context.
- Edges only express which checkpoints should be assembled into the next user prompt.
- The canvas summarizes the current conversation; it is not a global history browser.
- Keep user-facing explanations in Chinese unless the user asks otherwise.
