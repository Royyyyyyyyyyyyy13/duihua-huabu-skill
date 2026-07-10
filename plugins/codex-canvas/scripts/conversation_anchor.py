from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from canvas_store import (
    GRID_COLUMN_GAP,
    GRID_COLUMNS,
    GRID_LEFT,
    GRID_ROW_GAP,
    GRID_TOP,
    insert_reconstructed_nodes,
    load_session,
)
from transcript_recovery import Turn, codex_home, compact_text, parse_transcript


MAX_RECENT_FILES = 80
MAX_DETAIL_CHARS = 2600
MAX_CONTEXT_CHARS = 900


@dataclass
class AnchorSource:
    path: Path
    score: int
    turns: list[Turn]


def bootstrap_anchor_node(session_id: str | None, workspace_hint: str | None = None) -> dict[str, Any]:
    data = load_session(session_id)
    starter_nodes = starter_anchor_nodes(data)
    if data.get("nodes") and not starter_nodes:
        return {
            "ok": True,
            "created": False,
            "message": "画布已有节点，不需要生成启示节点。",
            "session": data,
        }

    source_hint = infer_workspace_hint(data) if starter_nodes else None
    source = find_anchor_source(source_hint or workspace_hint, session_id=session_id)
    if not source:
        return {
            "ok": False,
            "created": False,
            "message": "没有找到可用于生成启示节点的最近 Codex 记录。",
            "session": data,
        }

    inserted = insert_reconstructed_nodes(
        session_id,
        build_reconstructed_nodes(source),
        [node.get("id") for node in starter_nodes],
    )
    nodes = inserted["nodes"]
    session = inserted["session"]
    return {
        "ok": True,
        "created": True,
        "message": f"已根据最近对话生成 {len(nodes)} 个回溯节点。",
        "node": nodes[0] if len(nodes) == 1 else None,
        "nodes": nodes,
        "session": session,
    }


def starter_anchor_nodes(data: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = list(data.get("nodes") or [])
    if not nodes:
        return []
    if any(node.get("origin") == "reconstructed" for node in nodes):
        return []
    if not any(is_starter_anchor(node) for node in nodes[:3]):
        return []
    return nodes


def is_starter_anchor(node: dict[str, Any]) -> bool:
    if node.get("type") != "anchor" or node.get("origin") != "live":
        return False
    text = "\n".join(
        [
            str(node.get("title") or ""),
            str(node.get("summary") or ""),
            str(node.get("detailMarkdown") or ""),
            " ".join(str(tag) for tag in node.get("tags") or []),
        ]
    )
    if "画布启用" in text or "从当前对话开始启用" in text or ("canvas" in text.lower() and "checkpoint" in text.lower()):
        return True
    return False


def infer_workspace_hint(data: dict[str, Any]) -> str | None:
    text_parts: list[str] = []
    path_values: list[str] = []
    for node in list(data.get("nodes") or []):
        text_parts.extend(
            [
                str(node.get("title") or ""),
                str(node.get("summary") or ""),
                str(node.get("detailMarkdown") or ""),
                str(node.get("contextText") or ""),
            ]
        )
        path_values.extend(str(value) for value in list(node.get("relatedFiles") or []))
        path_values.extend(str(value) for value in list(node.get("evidenceRefs") or []))

    text = "\n".join(text_parts)
    project_match = re.search(r"项目目录[:：]\s*([A-Za-z]:\\[^\n\r。；;]+)", text)
    if project_match:
        return project_match.group(1).strip().rstrip(" .")

    absolute_paths = [value.strip().rstrip(" .") for value in path_values if re.match(r"^[A-Za-z]:\\", value.strip())]
    if not absolute_paths:
        return None
    try:
        return os.path.commonpath(absolute_paths)
    except ValueError:
        return str(Path(absolute_paths[0]).parent)


def find_anchor_source(workspace_hint: str | None, session_id: str | None = None) -> AnchorSource | None:
    sessions_root = codex_home() / "sessions"
    candidates: list[AnchorSource] = []
    session_terms = session_search_terms(session_id)
    if sessions_root.exists():
        files = sorted(sessions_root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in files[:MAX_RECENT_FILES]:
            try:
                if path.stat().st_size > 35 * 1024 * 1024:
                    continue
            except OSError:
                continue
            turns, meta_score = parse_transcript(path, set(), workspace_hint)
            visible_turns = [turn for turn in turns if turn.text.strip()]
            if len(visible_turns) < 2:
                continue
            content = content_score(visible_turns)
            session_match = session_term_score(visible_turns, session_terms)
            if not workspace_hint and session_terms and session_match <= 0:
                continue
            if not workspace_hint and not session_terms:
                continue
            if workspace_hint and meta_score <= 0 and session_match <= 0:
                continue
            candidates.append(
                AnchorSource(
                    path=path,
                    score=meta_score + content + session_match,
                    turns=visible_turns,
                )
            )
    memory_source = memory_anchor_source(workspace_hint, session_terms)
    if memory_source:
        candidates.append(memory_source)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[0]


def session_search_terms(session_id: str | None) -> set[str]:
    text = str(session_id or "").lower()
    terms = set(re.findall(r"[a-z][a-z0-9_-]{3,}", text))
    terms.update(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    stop_terms = {
        "live",
        "demo",
        "test",
        "smoke",
        "canvas",
        "codex",
        "session",
        "default",
    }
    return {term for term in terms if term not in stop_terms and not term.isdigit() and not re.fullmatch(r"20\d{6,}", term)}


def session_term_score(turns: list[Turn], terms: set[str]) -> int:
    if not terms:
        return 0
    text = "\n".join(turn.text for turn in turns).lower()
    score = 0
    for term in terms:
        if term in text:
            score += min(text.count(term), 10) * 8
    return score


def content_score(turns: list[Turn]) -> int:
    text = "\n".join(turn.text for turn in turns[-12:]).lower()
    score = 0
    for keyword in ["画布", "节点", "checkpoint", "codex", "插件", "skill", "方案", "实现", "验证"]:
        if keyword.lower() in text:
            score += 3
    return score


def memory_anchor_source(workspace_hint: str | None, session_terms: set[str]) -> AnchorSource | None:
    path = codex_home() / "memories" / "raw_memories.md"
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not raw:
        return None
    normalized_raw = normalize_text_path(raw)
    if workspace_hint and normalize_text_path(workspace_hint) not in normalized_raw:
        return None
    chunks = [chunk.strip() for chunk in raw.split("\n\n") if chunk.strip()]
    turns = [Turn(timestamp="memory", role="assistant", text=chunk) for chunk in chunks[-8:]]
    session_score = session_term_score(turns, session_terms)
    if session_terms and session_score <= 0:
        return None
    if not workspace_hint and not session_terms:
        return None
    return AnchorSource(path=path, score=10 + content_score(turns) + session_score, turns=turns)


def normalize_text_path(value: str) -> str:
    return str(value or "").replace("/", "\\").rstrip("\\").lower()


def build_reconstructed_nodes(source: AnchorSource) -> list[dict[str, Any]]:
    usable_turns = [turn for turn in source.turns if not is_progress_turn(turn)]
    meaningful = [turn for turn in usable_turns if not is_low_signal_line(summarize_line(turn.text))]
    turns = meaningful or usable_turns or source.turns
    recent = turns[-32:]
    count = estimate_reconstruction_count(recent)
    if count <= 1:
        return [build_anchor_node(source)]
    chunks = split_evenly(recent, count)
    nodes: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        node = build_phase_node(source, chunk, index, len(chunks))
        nodes.append(node)
    return nodes


def estimate_reconstruction_count(turns: list[Turn]) -> int:
    useful = [clean_message_text(turn.text) for turn in turns]
    useful = [text for text in useful if text and not is_low_signal_line(summarize_line(text))]
    total_chars = sum(len(text) for text in useful)
    if len(useful) < 3 or total_chars < 600:
        return 1
    if len(useful) < 6 or total_chars < 1600:
        return 2
    if len(useful) < 12 or total_chars < 3600:
        return 3
    return min(8, max(4, round(len(useful) / 4)))


def split_evenly(values: list[Turn], count: int) -> list[list[Turn]]:
    count = max(1, min(count, len(values)))
    chunks: list[list[Turn]] = []
    for index in range(count):
        start = round(index * len(values) / count)
        end = round((index + 1) * len(values) / count)
        chunk = values[start:end]
        if chunk:
            chunks.append(chunk)
    return chunks


def build_phase_node(source: AnchorSource, turns: list[Turn], index: int, total: int) -> dict[str, Any]:
    user_turns = [turn for turn in turns if turn.role == "user"]
    assistant_turns = [turn for turn in turns if turn.role == "assistant"]
    user_points = compact_bullets([turn.text for turn in user_turns], limit=3)
    assistant_points = compact_bullets([turn.text for turn in assistant_turns], limit=3)
    title = derive_phase_title(turns, index)
    summary = derive_phase_summary(turns)
    detail = "\n".join(
        [
            "## 回溯阶段",
            f"- {summary}",
            "",
            "## 用户重点",
            user_points or "- 没有足够明确的用户原文，只能保留阶段级摘要。",
            "",
            "## 助手要点",
            assistant_points or "- 没有足够明确的助手回应，只能保留阶段级摘要。",
            "",
            "## 可信度",
            f"- {phase_confidence(turns)}：由当前可读 Codex 记录回顾生成，不代表逐字原文。",
            "",
            "## 来源",
            f"- {source.path}",
        ]
    ).strip()
    if len(detail) > MAX_DETAIL_CHARS:
        detail = detail[: MAX_DETAIL_CHARS - 20].rstrip() + "\n\n..."
    context = f"历史回溯阶段 {index + 1}/{total}：{summary}"
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[: MAX_CONTEXT_CHARS - 20].rstrip() + "..."
    return {
        "id": f"reconstructed_{index + 1:02d}",
        "type": infer_phase_type(turns),
        "title": title,
        "summary": summary,
        "detailMarkdown": detail,
        "contextText": context,
        "rawText": "",
        "source": "mixed",
        "origin": "reconstructed",
        "confidence": phase_confidence(turns),
        "relatedFiles": [],
        "evidenceRefs": [str(source.path)],
        "tags": ["回溯节点", "历史摘要", f"{index + 1}/{total}"],
        "status": "active",
        "x": GRID_LEFT + (index % GRID_COLUMNS) * GRID_COLUMN_GAP,
        "y": GRID_TOP + (index // GRID_COLUMNS) * GRID_ROW_GAP,
    }


def build_anchor_node(source: AnchorSource) -> dict[str, Any]:
    usable_turns = [turn for turn in source.turns if not is_progress_turn(turn)]
    recent = (usable_turns or source.turns)[-20:]
    user_turns = [turn for turn in recent if turn.role == "user"]
    assistant_turns = [turn for turn in recent if turn.role == "assistant"]
    latest_user = pick_meaningful_text(user_turns) or compact_text(recent[-1].text)
    latest_assistant = compact_text(assistant_turns[-1].text if assistant_turns else "")
    discussion_points = compact_bullets([turn.text for turn in reversed(user_turns[-6:])], limit=4)
    confirmations = compact_bullets([turn.text for turn in reversed(assistant_turns[-6:])], limit=4)

    summary = derive_anchor_summary(latest_user)
    detail = "\n".join(
        [
            "## 当前目标",
            f"- {summary}",
            "",
            "## 已确认",
            confirmations or "- 已从最近一次可读 Codex 记录建立当前状态起点，后续节点从这里继续生长。",
            "",
            "## 正在讨论",
            discussion_points or f"- {summary}",
            "",
            "## 下一步",
            "- 后续每完成一个小阶段，直接追加新的轻量 checkpoint 节点。",
            "- 默认使用结构化详情和压缩上下文，不把大段原文作为核心数据。",
            "",
            "## 来源",
            f"- {source.path}",
        ]
    ).strip()
    if len(detail) > MAX_DETAIL_CHARS:
        detail = detail[: MAX_DETAIL_CHARS - 20].rstrip() + "\n\n..."

    context = "\n".join(
        [
            "当前对话起点：",
            summary,
            "",
            "后续处理原则：从这个启示节点之后继续记录新 checkpoint，不复盘完整历史；复制上下文时优先使用压缩后的 contextText。",
        ]
    ).strip()
    if latest_assistant:
        context = f"{context}\n\n最近助手回应要点：{summarize_line(latest_assistant)}"
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[: MAX_CONTEXT_CHARS - 20].rstrip() + "..."

    return {
        "id": "anchor_current_state",
        "type": "anchor",
        "title": "当前对话起点",
        "summary": summary,
        "detailMarkdown": detail,
        "contextText": context,
        "rawText": "",
        "source": "mixed",
        "origin": "reconstructed",
        "confidence": "medium",
        "relatedFiles": [],
        "evidenceRefs": [str(source.path)],
        "tags": ["启示节点", "当前状态", "起点"],
        "status": "active",
        "x": GRID_LEFT,
        "y": GRID_TOP,
    }


def derive_phase_title(turns: list[Turn], index: int) -> str:
    text = derive_phase_summary(turns)
    for prefix in ["需求", "方案", "实现", "验证", "修复", "固化", "讨论"]:
        if prefix in text:
            return f"{prefix}回溯"
    return f"回溯阶段{index + 1}"


def derive_phase_summary(turns: list[Turn]) -> str:
    for turn in turns:
        if turn.role == "user":
            line = summarize_line(turn.text)
            if line and not is_low_signal_line(line):
                return line
    for turn in turns:
        line = summarize_line(turn.text)
        if line and not is_low_signal_line(line):
            return line
    return "当前阶段只有少量可读上下文，保留为历史回溯摘要。"


def infer_phase_type(turns: list[Turn]) -> str:
    text = "\n".join(clean_message_text(turn.text) for turn in turns)
    if any(keyword in text for keyword in ["验证", "检查", "回归", "测试", "通过"]):
        return "verification"
    if any(keyword in text for keyword in ["实现", "改造", "修复", "代码", "补齐"]):
        return "implementation"
    if any(keyword in text for keyword in ["决定", "确定", "不做", "边界", "方案"]):
        return "decision"
    if any(keyword in text for keyword in ["计划", "规划", "MVP"]):
        return "plan"
    if any(keyword in text for keyword in ["问题", "失败", "阻塞", "bug", "BUG"]):
        return "blocker"
    return "note"


def phase_confidence(turns: list[Turn]) -> str:
    useful = [clean_message_text(turn.text) for turn in turns if clean_message_text(turn.text)]
    total_chars = sum(len(text) for text in useful)
    if len(useful) >= 4 and total_chars >= 1000:
        return "high"
    if len(useful) >= 2 and total_chars >= 400:
        return "medium"
    return "low"


def compact_bullets(values: list[str], limit: int) -> str:
    bullets: list[str] = []
    seen: set[str] = set()
    for value in values:
        line = summarize_line(value)
        if not line or line in seen or is_low_signal_line(line):
            continue
        seen.add(line)
        bullets.append(f"- {line}")
        if len(bullets) >= limit:
            break
    return "\n".join(bullets)


def derive_anchor_summary(value: str) -> str:
    text = summarize_line(value)
    if "启示节点" in text and "新节点" in text:
        return "中途启用画布时，不复盘完整历史，只用最近上下文生成一个启示节点，后续从这里追加新节点。"
    if "不顾及历史" in text or "不估计历史" in text:
        return "中途启用画布时，以当前状态为起点，不把历史完整重建为画布。"
    return text


def is_low_signal_line(line: str) -> bool:
    normalized = line.lower().strip("。！？!?. ")
    low_signal = {
        "ok",
        "好",
        "嗯",
        "嗯 改造吧",
        "可以",
        "继续",
        "开搞",
        "好i开搞",
        "改造吧",
        "再次跳出检查下",
    }
    return normalized in low_signal


def is_progress_turn(turn: Turn) -> bool:
    text = " ".join(compact_text(turn.text).split())
    if turn.role != "assistant":
        return False
    if text.startswith(("我先", "接下来")) and ("计划" in text or "落地" in text):
        return True
    if len(text) > 260:
        return False
    progress_terms = [
        "我先",
        "接下来",
        "现在",
        "已经",
        "准备",
        "定位",
        "补丁",
        "静态检查",
        "语法检查",
        "重启",
        "服务",
        "接口",
        "浏览器",
        "样式",
        "HTML",
        "CSS",
        "数据结构",
        "跑编译",
        "验证",
    ]
    return any(term in text for term in progress_terms)


def pick_meaningful_text(turns: list[Turn]) -> str:
    short_ack = {
        "ok",
        "好",
        "嗯",
        "嗯 改造吧",
        "可以",
        "继续",
        "开搞",
        "好i开搞",
        "改造吧",
        "再次跳出检查下",
    }
    for turn in reversed(turns):
        text = " ".join(clean_message_text(turn.text).split())
        normalized = text.lower().strip("。！？!?. ")
        if len(text) >= 40 and normalized not in short_ack:
            return text
    for turn in reversed(turns):
        text = " ".join(clean_message_text(turn.text).split())
        normalized = text.lower().strip("。！？!?. ")
        if normalized and normalized not in short_ack:
            return text
    return ""


def summarize_line(value: str) -> str:
    text = clean_message_text(value)
    text = " ".join(text.split())
    if not text:
        return "当前对话已经进行到可继续记录新节点的状态。"
    if len(text) <= 180:
        return text
    return text[:177].rstrip() + "..."


def clean_message_text(value: str) -> str:
    text = compact_text(value)
    marker = "## My request for Codex:"
    if marker in text:
        text = text.split(marker, 1)[1].strip()
    lines = []
    skip_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# In app browser:") or stripped.startswith("# Files mentioned by the user:"):
            skip_block = True
            continue
        if skip_block and stripped.startswith("## "):
            skip_block = False
        if skip_block:
            continue
        lines.append(line)
    return compact_text("\n".join(lines))
