from __future__ import annotations

import argparse
import json
import sys

from canvas_store import add_edge, add_node, load_session, safe_session_id, session_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record a Codex Canvas checkpoint.")
    parser.add_argument("--session", default=None, help="Canvas session id.")
    parser.add_argument("--type", default="note", help="Checkpoint type.")
    parser.add_argument("--title", required=True, help="Checkpoint title.")
    parser.add_argument("--summary", required=True, help="Checkpoint summary.")
    parser.add_argument("--raw-text", default="", help="Original conversation text.")
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
    parser.add_argument("--auto-link", action="store_true", help="Connect the new checkpoint from the previous node.")
    parser.add_argument("--tag", action="append", default=[], help="Repeatable tag.")
    parser.add_argument("--related-file", action="append", default=[], help="Repeatable file path.")
    parser.add_argument("--evidence-ref", action="append", default=[], help="Repeatable source reference.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stdin_flags = [args.stdin_raw_text, args.stdin_detail_markdown, args.stdin_context_text]
    if sum(1 for enabled in stdin_flags if enabled) > 1:
        print(
            "只能同时使用一个 stdin 输入参数：--stdin-raw-text、--stdin-detail-markdown、--stdin-context-text 三选一。",
            file=sys.stderr,
        )
        return 2
    raw_text = sys.stdin.read() if args.stdin_raw_text else args.raw_text
    detail_markdown = sys.stdin.read() if args.stdin_detail_markdown else args.detail_markdown
    context_text = sys.stdin.read() if args.stdin_context_text else args.context_text
    before = load_session(args.session)
    previous_node = before.get("nodes", [])[-1] if before.get("nodes") else None
    node = add_node(
        args.session,
        {
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
        },
    )
    edge = None
    if args.auto_link and previous_node and previous_node.get("id") != node.get("id"):
        edge = add_edge(
            args.session,
            {
                "from": previous_node.get("id"),
                "to": node.get("id"),
                "label": "",
            },
        )
    session = safe_session_id(args.session)
    result = {
        "ok": True,
        "sessionId": session,
        "node": node,
        "edge": edge,
        "path": str(session_path(session)),
        "url": f"http://127.0.0.1:8765/?session={session}",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
