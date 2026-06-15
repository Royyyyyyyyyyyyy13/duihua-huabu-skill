from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from canvas_store import load_session, save_session


MAX_FILES = 40
MAX_FILE_BYTES = 35 * 1024 * 1024
MAX_NODE_TEXT = 4200
WEAK_RAW_TEXT_CHARS = 160


@dataclass
class Turn:
    timestamp: str
    role: str
    text: str


@dataclass
class Transcript:
    path: Path
    score: int
    turns: list[Turn]


def codex_home() -> Path:
    root = os.environ.get("CODEX_HOME")
    if root:
        return Path(root).expanduser()
    return Path.home() / ".codex"


def recover_session_raw_text(session_id: str | None, workspace_hint: str | None = None) -> dict[str, Any]:
    data = load_session(session_id)
    nodes = data.get("nodes", [])
    weak_nodes = [node for node in nodes if needs_recovery(node)]
    if not weak_nodes:
        return {"ok": True, "updated": 0, "sources": [], "message": "没有需要回填的短原文节点。"}

    transcripts = load_candidate_transcripts(nodes, workspace_hint)
    if not transcripts:
        return {"ok": False, "updated": 0, "sources": [], "message": "没有找到可读的 Codex 会话记录。"}

    updated = 0
    used_sources: set[str] = set()
    for index, node in enumerate(nodes):
        if not needs_recovery(node):
            continue
        recovered, source = recover_node_text(node, transcripts, index, len(nodes))
        if not recovered:
            continue
        node["rawText"] = recovered
        if source:
            used_sources.add(str(source))
        updated += 1

    if updated:
        save_session(session_id, data)

    return {
        "ok": True,
        "updated": updated,
        "sources": sorted(used_sources),
        "message": f"已回填 {updated} 个短原文节点。",
    }


def needs_recovery(node: dict[str, Any]) -> bool:
    raw_text = str(node.get("rawText") or "").strip()
    summary = str(node.get("summary") or "").strip()
    if not raw_text:
        return True
    if len(raw_text) <= WEAK_RAW_TEXT_CHARS:
        return True
    return raw_text == summary


def load_candidate_transcripts(nodes: list[dict[str, Any]], workspace_hint: str | None) -> list[Transcript]:
    root = codex_home() / "sessions"
    if not root.exists():
        return []

    keywords = session_keywords(nodes)
    files = sorted(root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    transcripts: list[Transcript] = []
    for path in files[:MAX_FILES * 4]:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        turns, meta_score = parse_transcript(path, keywords, workspace_hint)
        if not turns:
            continue
        content_score = score_transcript(turns, keywords)
        score = meta_score + content_score
        if score <= 0:
            continue
        transcripts.append(Transcript(path=path, score=score, turns=turns))
        if len(transcripts) >= MAX_FILES:
            break

    transcripts.sort(key=lambda item: item.score, reverse=True)
    transcripts.extend(load_memory_transcripts(keywords))
    transcripts.sort(key=lambda item: item.score, reverse=True)
    return transcripts


def load_memory_transcripts(keywords: set[str]) -> list[Transcript]:
    path = codex_home() / "memories" / "raw_memories.md"
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", raw) if chunk.strip()]
    turns = [
        Turn(timestamp=memory_timestamp(path), role="assistant", text=chunk)
        for chunk in chunks
        if any(keyword in chunk.lower() for keyword in keywords)
    ]
    score = score_transcript(turns, keywords)
    if not turns or score <= 0:
        return []
    return [Transcript(path=path, score=score, turns=turns)]


def parse_transcript(path: Path, keywords: set[str], workspace_hint: str | None) -> tuple[list[Turn], int]:
    turns: list[Turn] = []
    meta_score = 0
    seen: set[tuple[str, str, str]] = set()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as file:
            for line in file:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("type") == "session_meta":
                    payload = item.get("payload") or {}
                    cwd = str(payload.get("cwd") or "")
                    if workspace_hint and normalize_path(cwd) == normalize_path(workspace_hint):
                        meta_score += 30
                    continue
                turn = turn_from_item(item)
                if not turn:
                    continue
                key = (turn.timestamp, turn.role, compact_text(turn.text)[:180])
                if key in seen:
                    continue
                seen.add(key)
                turns.append(turn)
    except OSError:
        return [], 0
    if any(keyword and keyword in path.name for keyword in keywords):
        meta_score += 5
    return turns, meta_score


def turn_from_item(item: dict[str, Any]) -> Turn | None:
    timestamp = str(item.get("timestamp") or "")
    payload = item.get("payload") or {}
    item_type = item.get("type")
    if item_type == "response_item" and payload.get("type") == "message":
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            return None
        text = text_from_content(payload.get("content"))
        if not text:
            return None
        return Turn(timestamp=timestamp, role=role, text=text)
    if item_type == "event_msg" and payload.get("type") == "user_message":
        text = str(payload.get("message") or "").strip()
        if text:
            return Turn(timestamp=timestamp, role="user", text=text)
    if item_type == "event_msg" and payload.get("type") == "agent_message":
        text = str(payload.get("message") or "").strip()
        if text:
            return Turn(timestamp=timestamp, role="assistant", text=text)
    return None


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return "\n\n".join(chunks).strip()


def session_keywords(nodes: list[dict[str, Any]]) -> set[str]:
    keywords: set[str] = set()
    for node in nodes:
        source = " ".join(
            [
                str(node.get("title") or ""),
                str(node.get("summary") or ""),
                " ".join(str(tag) for tag in node.get("tags") or []),
            ]
        )
        keywords.update(extract_keywords(source))
    return {keyword for keyword in keywords if len(keyword) >= 2}


def extract_keywords(text: str) -> set[str]:
    words = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()))
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    for chunk in chinese:
        if len(chunk) <= 6:
            words.add(chunk)
        else:
            for size in (2, 3, 4):
                for index in range(0, len(chunk) - size + 1):
                    words.add(chunk[index : index + size])
    stop_words = {
        "这个",
        "现在",
        "已经",
        "节点",
        "画布",
        "当前",
        "一个",
        "可以",
        "进行",
        "用户",
        "实现",
        "测试",
    }
    return {word for word in words if word not in stop_words}


def score_transcript(turns: list[Turn], keywords: set[str]) -> int:
    if not keywords:
        return 0
    score = 0
    sample_text = "\n".join(turn.text for turn in turns)
    lowered = sample_text.lower()
    for keyword in keywords:
        if keyword in lowered:
            score += min(lowered.count(keyword), 8)
    return score


def recover_node_text(
    node: dict[str, Any],
    transcripts: list[Transcript],
    index: int,
    total_nodes: int,
) -> tuple[str, Path | None]:
    node_keywords = extract_keywords(
        " ".join(
            [
                str(node.get("title") or ""),
                str(node.get("summary") or ""),
                " ".join(str(tag) for tag in node.get("tags") or []),
            ]
        )
    )
    for transcript in transcripts[:8]:
        windows = ranked_windows(transcript.turns, node_keywords)
        if windows:
            return format_recovered_text(node, transcript.path, windows[:2]), transcript.path

    best = transcripts[0]
    fallback = proportional_window(best.turns, index, total_nodes)
    if fallback:
        return format_recovered_text(node, best.path, [fallback]), best.path
    return "", None


def ranked_windows(turns: list[Turn], keywords: set[str]) -> list[list[Turn]]:
    if not turns:
        return []
    scored: list[tuple[int, int, list[Turn]]] = []
    for start in range(len(turns)):
        window = turns[start : start + 4]
        text = "\n".join(turn.text for turn in window).lower()
        score = 0
        for keyword in keywords:
            score += text.count(keyword.lower())
        if score:
            scored.append((score, start, window))
    scored.sort(key=lambda item: (-item[0], item[1]))
    picked: list[list[Turn]] = []
    used_ranges: list[range] = []
    for score, start, window in scored:
        current = range(start, start + len(window))
        if any(overlaps(current, used) for used in used_ranges):
            continue
        picked.append(window)
        used_ranges.append(current)
        if len(picked) >= 2:
            break
    return picked


def proportional_window(turns: list[Turn], index: int, total_nodes: int) -> list[Turn]:
    if not turns:
        return []
    total = max(total_nodes, 1)
    center = int((len(turns) - 1) * (index + 0.5) / total)
    start = max(0, center - 2)
    return turns[start : start + 5]


def format_recovered_text(node: dict[str, Any], source_path: Path, windows: list[list[Turn]]) -> str:
    parts = [
        "【自动回填说明】",
        "以下内容来自本机 Codex 可读会话记录。它不是旧节点当时保存的逐字原文，而是按节点标题、摘要、标签和当前工作目录匹配到的相关聊天片段。",
        f"来源文件：{source_path}",
        "",
    ]
    for index, window in enumerate(windows, start=1):
        parts.append(f"【相关片段 {index}】")
        for turn in window:
            label = "用户" if turn.role == "user" else "助手"
            text = compact_text(turn.text)
            parts.append(f"{label}（{turn.timestamp or '未知时间'}）：{text}")
        parts.append("")
    result = "\n".join(parts).strip()
    if len(result) <= MAX_NODE_TEXT:
        return result
    return result[: MAX_NODE_TEXT - 40].rstrip() + "\n\n【已截断】"


def compact_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", str(text or "").strip())


def overlaps(left: range, right: range) -> bool:
    return left.start < right.stop and right.start < left.stop


def normalize_path(value: str) -> str:
    return str(Path(value).expanduser()).replace("/", "\\").rstrip("\\").lower()


def memory_timestamp(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return "memory"
