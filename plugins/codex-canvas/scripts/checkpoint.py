from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from typing import Any

sys.dont_write_bytecode = True

from canvas_store import (
    record_checkpoint,
    record_checkpoints,
    safe_session_id,
    session_path,
)


def configure_utf8_stdio() -> None:
    for stream in [sys.stdin, sys.stdout, sys.stderr]:
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record one or more Codex Canvas checkpoints.")
    parser.add_argument("--session", default=None, help="Canvas session id.")
    parser.add_argument("--type", default="note", help="Checkpoint type.")
    parser.add_argument("--title", default=None, help="Checkpoint title.")
    parser.add_argument("--summary", default=None, help="Checkpoint summary.")
    parser.add_argument("--raw-text", default="", help="Short original conversation evidence.")
    parser.add_argument("--stdin-raw-text", action="store_true", help="Read rawText from stdin.")
    parser.add_argument("--detail-markdown", default="", help="Human-readable structured detail.")
    parser.add_argument("--stdin-detail-markdown", action="store_true", help="Read detailMarkdown from stdin.")
    parser.add_argument("--context-text", default="", help="Compressed context for prompt assembly.")
    parser.add_argument("--stdin-context-text", action="store_true", help="Read contextText from stdin.")
    parser.add_argument("--source", default="assistant", choices=["user", "assistant", "mixed"])
    parser.add_argument("--origin", default="live", choices=["live", "reconstructed", "imported"])
    parser.add_argument("--confidence", default="high", choices=["high", "medium", "low"])
    parser.add_argument("--status", default="active", choices=["active", "resolved", "archived"])
    parser.add_argument("--id", default=None, help="Optional stable checkpoint node id.")
    parser.add_argument("--auto-link", action="store_true", help="Connect new checkpoints from the previous node.")
    parser.add_argument("--tag", action="append", default=[], help="Repeatable tag.")
    parser.add_argument("--related-file", action="append", default=[], help="Repeatable file path.")
    parser.add_argument("--evidence-ref", action="append", default=[], help="Repeatable source reference.")
    parser.add_argument("--payload-json", default=None, help="JSON object containing one checkpoint or a checkpoints list.")
    parser.add_argument("--stdin-json", action="store_true", help="Read a JSON payload from stdin.")
    return parser.parse_args()


def checkpoint_from_args(args: argparse.Namespace) -> dict[str, Any]:
    raw_text = sys.stdin.read() if args.stdin_raw_text else args.raw_text
    detail_markdown = sys.stdin.read() if args.stdin_detail_markdown else args.detail_markdown
    context_text = sys.stdin.read() if args.stdin_context_text else args.context_text
    return {
        "id": args.id,
        "type": args.type,
        "title": args.title,
        "summary": args.summary,
        "rawText": raw_text,
        "detailMarkdown": detail_markdown,
        "contextText": context_text,
        "source": args.source,
        "origin": args.origin,
        "confidence": args.confidence,
        "status": args.status,
        "tags": args.tag,
        "relatedFiles": args.related_file,
        "evidenceRefs": args.evidence_ref,
    }


def parse_json_payload(args: argparse.Namespace) -> dict[str, Any] | None:
    if not args.payload_json and not args.stdin_json:
        return None
    raw = sys.stdin.read() if args.stdin_json else args.payload_json
    try:
        payload = json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 格式错误：{exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON 顶层必须是对象")
    return payload


def normalize_checkpoint_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("每个 checkpoint 必须是 JSON 对象")
    title = str(value.get("title") or "").strip()
    summary = str(value.get("summary") or "").strip()
    if not title or not summary:
        raise ValueError("每个 checkpoint 都必须包含 title 和 summary")
    aliases = {
        "detail": "detailMarkdown",
        "context": "contextText",
        "raw": "rawText",
        "related_files": "relatedFiles",
        "evidence_refs": "evidenceRefs",
    }
    payload = dict(value)
    for source, target in aliases.items():
        if source in payload and target not in payload:
            payload[target] = payload[source]
    return payload


def record_from_json(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    session = args.session or payload.get("session") or payload.get("sessionId")
    auto_link = bool(payload.get("autoLink", args.auto_link))
    values = payload.get("checkpoints")
    if values is None and isinstance(payload.get("nodes"), list):
        values = payload["nodes"]
    if values is None:
        value = payload.get("checkpoint", payload)
        saved = record_checkpoint(session, normalize_checkpoint_payload(value), auto_link=auto_link)
        return {
            "session": session,
            "node": saved["node"],
            "edge": saved["edge"],
            "nodes": [saved["node"]],
            "edges": [saved["edge"]] if saved["edge"] else [],
        }
    if not isinstance(values, list) or not values:
        raise ValueError("checkpoints 必须是非空数组")
    saved = record_checkpoints(
        session,
        [normalize_checkpoint_payload(value) for value in values],
        auto_link=auto_link,
    )
    return {
        "session": session,
        "node": saved["nodes"][-1],
        "edge": saved["edges"][-1] if saved["edges"] else None,
        "nodes": saved["nodes"],
        "edges": saved["edges"],
    }


def main() -> int:
    configure_utf8_stdio()
    args = parse_args()
    stdin_flags = [args.stdin_raw_text, args.stdin_detail_markdown, args.stdin_context_text, args.stdin_json]
    if sum(1 for enabled in stdin_flags if enabled) > 1:
        print("stdin 输入模式一次只能使用一个。", file=sys.stderr)
        return 2
    if args.payload_json and args.stdin_json:
        print("--payload-json 和 --stdin-json 不能同时使用。", file=sys.stderr)
        return 2

    try:
        payload = parse_json_payload(args)
        if payload is not None:
            saved = record_from_json(args, payload)
            session_value = saved["session"]
        else:
            if not str(args.title or "").strip() or not str(args.summary or "").strip():
                raise ValueError("普通参数模式必须提供 --title 和 --summary")
            checkpoint = checkpoint_from_args(args)
            result = record_checkpoint(args.session, checkpoint, auto_link=args.auto_link)
            saved = {
                "node": result["node"],
                "edge": result["edge"],
                "nodes": [result["node"]],
                "edges": [result["edge"]] if result["edge"] else [],
            }
            session_value = args.session
    except (ValueError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    session = safe_session_id(session_value)
    encoded_session = urllib.parse.quote(session, safe="")
    result = {
        "ok": True,
        "sessionId": session,
        "node": saved["node"],
        "edge": saved["edge"],
        "nodes": saved["nodes"],
        "edges": saved["edges"],
        "path": str(session_path(session)),
        "url": f"http://127.0.0.1:8765/?session={encoded_session}",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
