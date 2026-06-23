from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
SCRIPTS = ROOT / "scripts"
SESSION = "codex-canvas-smoke"
SERVER = "http://127.0.0.1:8765"
VERSION = "20260623-no-discussion-edge"


def main() -> int:
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.path.insert(0, str(SCRIPTS))
    checks = [
        check_static_files,
        check_store_invariants,
        check_anchor_no_source,
        check_anchor_no_false_match,
        check_recover_no_false_match,
        check_anchor_starter_backfill,
        check_anchor_starter_with_live_nodes_backfill,
        check_checkpoint_stdin_guard,
        check_live_server,
        check_browser_ui,
        check_browser_interactions,
    ]
    failures: list[str] = []
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except Exception as exc:
            failures.append(f"{check.__name__}: {exc}")
            print(f"FAIL {check.__name__}: {exc}", file=sys.stderr)
    if failures:
        print("\nFAILED CHECKS:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("\nALL REGRESSION CHECKS PASSED")
    return 0


def check_static_files() -> None:
    run(["node", "--check", str(ROOT / "assets" / "canvas" / "app.js")])
    for script_name in [
        "canvas_server.py",
        "canvas_store.py",
        "checkpoint.py",
        "conversation_anchor.py",
        "transcript_recovery.py",
    ]:
        script_path = SCRIPTS / script_name
        compile(script_path.read_text(encoding="utf-8"), str(script_path), "exec")
    json.loads((ROOT / "data" / "schema.json").read_text(encoding="utf-8"))
    html = (ROOT / "assets" / "canvas" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "assets" / "canvas" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "assets" / "canvas" / "styles.css").read_text(encoding="utf-8")
    server = (SCRIPTS / "canvas_server.py").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "codex-canvas" / "SKILL.md").read_text(encoding="utf-8")
    assert_true(VERSION in html, "index.html did not reference the current asset version")
    assert_true("anchorBootstrapBlocked" in app, "app.js missing anchor bootstrap block guard")
    assert_true("state.nodes.slice(0, 3).some(isStarterAnchorNode)" in app, "app.js should bootstrap starter plus early live nodes")
    assert_true('workspace_hint=body.get("workspaceHint")' in server, "server should not use its cwd as the conversation workspace")
    assert_true("starter anchor plus a few early `live` checkpoints" in skill, "skill should require backfill after starter anchors")
    assert_true("estimate_reconstruction_count" in (SCRIPTS / "conversation_anchor.py").read_text(encoding="utf-8"), "adaptive reconstruction count missing")
    assert_true("布局保存失败，已先保留在本地" in app, "app.js missing layout save failure handling")
    assert_true('document.removeEventListener("pointerup", onEnd)' in app, "resize pointerup cleanup missing")
    assert_true(".tag-list .tag" in css and "min-width: 0" in css, "chip overflow fix missing")


def check_store_invariants() -> None:
    with temp_env(CODEX_CANVAS_HOME=tempfile.mkdtemp(prefix="canvas-regression-")):
        from canvas_store import add_edge, add_node, load_session, reset_canvas, session_path

        add_node(
            "store",
            {
                "id": "n1",
                "type": "requirement",
                "title": "初始",
                "summary": "摘要",
                "contextText": "短上下文",
                "tags": ["a"],
            },
        )
        updated = add_node("store", {"id": "n1", "title": "更新标题"})
        data = load_session("store")
        assert_equal(data["schemaVersion"], 1, "session schema version missing")
        assert_true("+codex." in data["createdByPluginVersion"], "new session createdByPluginVersion missing")
        assert_true("+codex." in data["lastOpenedByPluginVersion"], "new session lastOpenedByPluginVersion missing")
        assert_equal(len(data["nodes"]), 1, "duplicate node id appended a second node")
        assert_equal(updated["summary"], "摘要", "partial duplicate node update cleared summary")
        assert_equal(updated["contextText"], "短上下文", "partial duplicate node update cleared contextText")
        assert_equal(updated["type"], "requirement", "partial duplicate node update changed type")
        assert_equal(updated["origin"], "live", "default node origin should be live")
        assert_equal(updated["confidence"], "high", "default node confidence should be high")

        n2 = add_node(
            "store",
            {
                "id": "n2",
                "type": "verification",
                "title": "二",
                "summary": "二",
                "origin": "reconstructed",
                "confidence": "medium",
            },
        )
        assert_equal(n2["origin"], "reconstructed", "explicit reconstructed origin not stored")
        assert_equal(n2["confidence"], "medium", "explicit confidence not stored")
        edge1 = add_edge("store", {"from": "n1", "to": "n2", "id": "edge-a"})
        edge2 = add_edge("store", {"from": "n1", "to": "n2", "id": "edge-b"})
        data = load_session("store")
        assert_equal(len(data["edges"]), 1, "duplicate edge appended a second edge")
        assert_equal(edge2["id"], edge1["id"], "duplicate edge returned an unsaved new id")

        reset = reset_canvas("store")
        assert_equal(len(reset["nodes"]), 2, "reset changed node count")
        assert_equal(len(reset["edges"]), 1, "reset did not rebuild one mainline edge")
        assert_equal(reset["nodes"][0]["x"], 80, "reset did not restore first node x")
        assert_equal(reset["nodes"][1]["x"], 430, "reset did not restore second node x")

        legacy_path = session_path("legacy")
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(
            json.dumps(
                {
                    "sessionId": "legacy",
                    "updatedAt": "2026-06-01T00:00:00+08:00",
                    "nodes": [{"id": "old", "type": "note", "title": "旧", "summary": "旧摘要"}],
                    "edges": [],
                    "composerOrder": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        legacy = load_session("legacy")
        assert_equal(legacy["schemaVersion"], 1, "legacy session was not migrated to schema version 1")
        assert_equal(legacy["createdByPluginVersion"], "unknown", "legacy createdByPluginVersion should not pretend to be current")
        assert_true(
            "+codex." in legacy["lastOpenedByPluginVersion"],
            "legacy lastOpenedByPluginVersion should track the migrating plugin",
        )
        assert_equal(legacy["nodes"][0]["origin"], "live", "legacy node origin default missing")
        assert_equal(legacy["nodes"][0]["confidence"], "high", "legacy node confidence default missing")
        backups = list(legacy_path.parent.glob("legacy.schema-none-backup-*.json"))
        assert_true(bool(backups), "legacy migration backup was not created")


def check_anchor_no_source() -> None:
    with temp_env(
        CODEX_HOME=tempfile.mkdtemp(prefix="codex-empty-"),
        CODEX_CANVAS_HOME=tempfile.mkdtemp(prefix="canvas-empty-"),
    ):
        from conversation_anchor import bootstrap_anchor_node
        from transcript_recovery import Turn

        result = bootstrap_anchor_node("empty")
        assert_equal(result["ok"], False, "empty Codex source should not report ok")
        assert_equal(result["created"], False, "empty Codex source should not create an anchor")
        assert_equal(len(result["session"]["nodes"]), 0, "empty Codex source should not fake nodes")
        from conversation_anchor import estimate_reconstruction_count

        assert_equal(estimate_reconstruction_count([]), 1, "empty reconstruction count should fall back to one start node")
        assert_equal(
            estimate_reconstruction_count([Turn(timestamp="", role="user", text="很短")]),
            1,
            "short old conversation should not force three nodes",
        )


def check_anchor_no_false_match() -> None:
    with temp_env(
        CODEX_HOME=tempfile.mkdtemp(prefix="codex-false-match-"),
        CODEX_CANVAS_HOME=tempfile.mkdtemp(prefix="canvas-false-match-"),
    ):
        codex_root = Path(os.environ["CODEX_HOME"])
        memory = codex_root / "memories" / "raw_memories.md"
        memory.parent.mkdir(parents=True, exist_ok=True)
        memory.write_text("codex canvas checkpoint 插件开发记录，和 unrelated 会话无关。" * 8, encoding="utf-8")
        transcript = codex_root / "sessions" / "2026" / "06" / "15" / "rollout-canvas-dev.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        turns = [
            {"type": "session_meta", "payload": {"cwd": r"E:\画布SKILL"}},
            {
                "type": "event_msg",
                "timestamp": "2026-06-15T11:00:00+08:00",
                "payload": {
                    "type": "user_message",
                    "message": "继续检查 codex canvas checkpoint 插件，修复画布节点和连线交互。" * 5,
                },
            },
            {
                "type": "event_msg",
                "timestamp": "2026-06-15T11:00:30+08:00",
                "payload": {
                    "type": "agent_message",
                    "message": "已修复 canvas bootstrap 和 checkpoint 回归测试。" * 5,
                },
            },
        ]
        transcript.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in turns), encoding="utf-8")

        from conversation_anchor import bootstrap_anchor_node

        result = bootstrap_anchor_node("20260615-unrelated-live")
        assert_equal(result["created"], False, "bootstrap should not use generic canvas terms to backfill unrelated sessions")
        assert_equal(len(result["session"]["nodes"]), 0, "generic false match should not create nodes")


def check_recover_no_false_match() -> None:
    with temp_env(
        CODEX_HOME=tempfile.mkdtemp(prefix="codex-recover-false-"),
        CODEX_CANVAS_HOME=tempfile.mkdtemp(prefix="canvas-recover-false-"),
    ):
        codex_root = Path(os.environ["CODEX_HOME"])
        memory = codex_root / "memories" / "raw_memories.md"
        memory.parent.mkdir(parents=True, exist_ok=True)
        memory.write_text("codex canvas checkpoint 插件调试记录，不能被 unrelated 会话当成原文。" * 8, encoding="utf-8")
        transcript = codex_root / "sessions" / "2026" / "06" / "15" / "rollout-canvas-dev.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        turns = [
            {"type": "session_meta", "payload": {"cwd": r"E:\画布SKILL"}},
            {
                "type": "event_msg",
                "timestamp": "2026-06-15T11:10:00+08:00",
                "payload": {
                    "type": "user_message",
                    "message": "codex canvas checkpoint 插件详情回填调试。" * 5,
                },
            },
            {
                "type": "event_msg",
                "timestamp": "2026-06-15T11:10:30+08:00",
                "payload": {
                    "type": "agent_message",
                    "message": "已检查 canvas rawText recover 逻辑。" * 5,
                },
            },
        ]
        transcript.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in turns), encoding="utf-8")

        from canvas_store import add_node
        from transcript_recovery import recover_session_raw_text

        add_node(
            "20260615-unrelated-live",
            {
                "type": "anchor",
                "title": "画布启用",
                "summary": "从当前对话开始启用 Codex Canvas。",
                "rawText": "从当前对话开始启用 Codex Canvas。",
                "origin": "live",
                "tags": ["canvas", "checkpoint"],
            },
        )
        result = recover_session_raw_text("20260615-unrelated-live")
        assert_equal(result["ok"], False, "recover should not use generic canvas terms to fill unrelated rawText")
        assert_equal(result["updated"], 0, "generic false recover should not update nodes")


def check_anchor_starter_backfill() -> None:
    with temp_env(
        CODEX_HOME=tempfile.mkdtemp(prefix="codex-starter-"),
        CODEX_CANVAS_HOME=tempfile.mkdtemp(prefix="canvas-starter-"),
    ):
        codex_root = Path(os.environ["CODEX_HOME"])
        transcript = codex_root / "sessions" / "2026" / "06" / "15" / "rollout-starter.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        turns = [
            {"type": "session_meta", "payload": {"cwd": r"E:\GAME"}},
        ]
        for index in range(14):
            turns.append(
                {
                    "type": "event_msg",
                    "timestamp": f"2026-06-15T10:{index:02d}:00+08:00",
                    "payload": {
                        "type": "user_message",
                        "message": f"第{index}轮需求：继续开发偷菜肉鸽版本，调整玩法、数值、发布验证和版本策略。" * 4,
                    },
                }
            )
            turns.append(
                {
                    "type": "event_msg",
                    "timestamp": f"2026-06-15T10:{index:02d}:30+08:00",
                    "payload": {
                        "type": "agent_message",
                        "message": f"第{index}轮实现：完成代码修改、回归测试、玩法验证，并记录发布结果。" * 4,
                    },
                }
            )
        transcript.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in turns), encoding="utf-8")

        from canvas_store import add_node, load_session
        from conversation_anchor import bootstrap_anchor_node

        add_node(
            "starter",
            {
                "type": "anchor",
                "title": "画布启用",
                "summary": "从当前对话开始启用 Codex Canvas，后续在阶段完成时记录 checkpoint。",
                "detailMarkdown": "## 当前项目状态\n- 项目目录：E:\\GAME。\n- 已经开发过两个版本，需要回溯生成初始节点。",
                "contextText": "从当前对话开始启用 Codex Canvas。",
                "source": "mixed",
                "origin": "live",
                "confidence": "high",
                "relatedFiles": [r"E:\GAME\src\model\data.ts", r"E:\GAME\output\demo.zip"],
                "tags": ["canvas", "checkpoint"],
            },
        )
        result = bootstrap_anchor_node("starter", workspace_hint=r"E:\wrong-workspace")
        assert_equal(result["created"], True, "starter anchor should allow historical backfill")
        data = load_session("starter")
        assert_true(len(data["nodes"]) > 1, "starter backfill did not create reconstructed nodes")
        assert_equal(data["nodes"][0]["origin"], "reconstructed", "reconstructed nodes should be placed before starter")
        assert_equal(data["nodes"][-1]["title"], "画布启用", "starter anchor should remain after reconstructed nodes")
        assert_equal(len(data["edges"]), len(data["nodes"]) - 1, "starter backfill should build a complete mainline")
        assert_true(
            any(str(transcript) in ref for node in data["nodes"] for ref in node.get("evidenceRefs", [])),
            "starter backfill did not use inferred workspace transcript",
        )


def check_anchor_starter_with_live_nodes_backfill() -> None:
    with temp_env(
        CODEX_HOME=tempfile.mkdtemp(prefix="codex-starter-live-"),
        CODEX_CANVAS_HOME=tempfile.mkdtemp(prefix="canvas-starter-live-"),
    ):
        codex_root = Path(os.environ["CODEX_HOME"])
        transcript = codex_root / "sessions" / "2026" / "06" / "15" / "rollout-toucaicai-live.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        turns = [
            {"type": "session_meta", "payload": {"cwd": r"E:\GAME"}},
        ]
        for index in range(10):
            turns.append(
                {
                    "type": "event_msg",
                    "timestamp": f"2026-06-15T12:{index:02d}:00+08:00",
                    "payload": {
                        "type": "user_message",
                        "message": f"toucaicai 第{index}轮需求：确认偷菜肉鸽玩法、经济压力、作物流派和发布 UI。" * 4,
                    },
                }
            )
            turns.append(
                {
                    "type": "event_msg",
                    "timestamp": f"2026-06-15T12:{index:02d}:30+08:00",
                    "payload": {
                        "type": "agent_message",
                        "message": f"toucaicai 第{index}轮实现：完成版本开发、验证、平衡调整和发布说明。" * 4,
                    },
                }
            )
        transcript.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in turns), encoding="utf-8")

        from canvas_store import add_edge, add_node, load_session
        from conversation_anchor import bootstrap_anchor_node

        add_node(
            "20260615-toucaicai-live",
            {
                "id": "live_anchor",
                "type": "anchor",
                "title": "画布启用",
                "summary": "从当前对话开始启用 Codex Canvas。",
                "detailMarkdown": "## 当前项目状态\n- 项目目录：E:\\GAME。\n- 已经进入 live checkpoint。",
                "contextText": "画布启用。",
                "origin": "live",
                "tags": ["canvas", "checkpoint"],
            },
        )
        add_node(
            "20260615-toucaicai-live",
            {
                "id": "live_followup",
                "type": "implementation",
                "title": "早期节点",
                "summary": "启用后马上形成的 live 节点。",
                "contextText": "早期 live 节点。",
                "origin": "live",
            },
        )
        add_edge("20260615-toucaicai-live", {"from": "live_anchor", "to": "live_followup", "label": ""})

        result = bootstrap_anchor_node("20260615-toucaicai-live")
        assert_equal(result["created"], True, "starter plus early live nodes should still allow historical backfill")
        data = load_session("20260615-toucaicai-live")
        assert_equal(data["nodes"][0]["origin"], "reconstructed", "reconstructed nodes should come before existing live nodes")
        assert_equal(data["nodes"][-2]["id"], "live_anchor", "starter anchor should remain before later live node")
        assert_equal(data["nodes"][-1]["id"], "live_followup", "early live node should remain after starter anchor")
        assert_equal(len(data["edges"]), len(data["nodes"]) - 1, "backfill should preserve a complete mainline")
        assert_true(
            any(str(transcript) in ref for node in data["nodes"] for ref in node.get("evidenceRefs", [])),
            "starter plus live backfill did not use the matching transcript",
        )


def check_checkpoint_stdin_guard() -> None:
    command = [
        sys.executable,
        str(SCRIPTS / "checkpoint.py"),
        "--session",
        "stdin-guard",
        "--type",
        "note",
        "--title",
        "t",
        "--summary",
        "s",
        "--stdin-detail-markdown",
        "--stdin-context-text",
    ]
    result = subprocess.run(command, input="x", text=True, capture_output=True, cwd=str(WORKSPACE))
    assert_equal(result.returncode, 2, "checkpoint stdin guard should return code 2")
    assert_true("只能同时使用一个 stdin 输入参数" in result.stderr, "checkpoint stdin guard message missing")


def check_live_server() -> None:
    html = http_text(f"{SERVER}/?session={SESSION}")
    app = http_text(f"{SERVER}/app.js?v={VERSION}")
    css = http_text(f"{SERVER}/styles.css?v={VERSION}")
    assert_true(VERSION in html, "live HTML did not serve current asset version")
    assert_true("anchorBootstrapBlocked" in app, "live app.js missing current bootstrap guard")
    assert_true(".tag-list .tag" in css, "live CSS missing chip fix")

    data = http_json(f"{SERVER}/api/session/{SESSION}")
    assert_equal(data.get("schemaVersion"), 1, "live session schemaVersion missing")
    assert_true(data.get("createdByPluginVersion"), "live session createdByPluginVersion missing")
    assert_true(data.get("lastOpenedByPluginVersion"), "live session lastOpenedByPluginVersion missing")
    nodes = data["nodes"]
    edges = data["edges"]
    node_ids = [node["id"] for node in nodes]
    assert_equal(len(node_ids), len(set(node_ids)), "live session has duplicate node ids")
    assert_equal(len(edges), max(0, len(nodes) - 1), "live session edge count is not mainline length")
    for edge in edges:
        assert_true(edge["from"] in node_ids and edge["to"] in node_ids, f"broken edge {edge.get('id')}")
    for node in nodes:
        assert_true(node.get("origin") in {"live", "reconstructed", "imported"}, f"node origin missing for {node.get('id')}")
        assert_true(node.get("confidence") in {"high", "medium", "low"}, f"node confidence missing for {node.get('id')}")
    for node_id in data.get("composerOrder", []):
        assert_true(node_id in node_ids, f"composerOrder references missing node {node_id}")
    raw_prompt_fallback = [
        node
        for node in nodes
        if not node.get("contextText") and not node.get("detailMarkdown") and not node.get("summary") and node.get("rawText")
    ]
    assert_equal(len(raw_prompt_fallback), 0, "prompt would fall back to rawText")
    for node in nodes:
        if node.get("id") != "current_23_regression_baseline":
            continue
        detail = node.get("detailMarkdown", "")
        assert_true("本轮硬检查" in detail, "regression checkpoint detail lost Chinese text")
        assert_true("鏈?" not in detail, "regression checkpoint detail contains mojibake")

        bootstrap = http_json(f"{SERVER}/api/session/{SESSION}/bootstrap-anchor", method="POST", body={})
        assert_equal(bootstrap["ok"], True, "bootstrap existing session should return ok")
        assert_equal(bootstrap["created"], False, "bootstrap existing session should not create a new node")
        assert_equal(len(bootstrap["session"]["nodes"]), len(nodes), "bootstrap existing session changed node count")

        protected_delete = http_json(
            f"{SERVER}/api/session/{SESSION}/nodes/{nodes[0]['id']}",
            method="DELETE",
            expected_status=405,
        )
        assert_true("cannot be deleted" in protected_delete.get("error", ""), "node delete should be explicitly blocked")
        after_protected_delete = http_json(f"{SERVER}/api/session/{SESSION}")
        assert_equal(len(after_protected_delete["nodes"]), len(nodes), "blocked node delete changed node count")

    temp_session = f"regression-{os.getpid()}"
    try:
        http_json(
            f"{SERVER}/api/session/{temp_session}/nodes",
            method="POST",
            body={"id": "a", "type": "requirement", "title": "一", "summary": "一", "contextText": "短"},
        )
        http_json(
            f"{SERVER}/api/session/{temp_session}/nodes",
            method="POST",
            body={"id": "a", "title": "一-更新"},
        )
        temp_data = http_json(f"{SERVER}/api/session/{temp_session}")
        assert_equal(len(temp_data["nodes"]), 1, "live API duplicate node id appended a second node")
        assert_equal(temp_data["nodes"][0]["contextText"], "短", "live API partial duplicate update cleared context")
    finally:
        session_file = Path.home() / ".codex-canvas" / "sessions" / f"{temp_session}.json"
        if session_file.exists():
            session_file.unlink()


def check_browser_ui() -> None:
    npx = npx_executable()
    if not npx:
        raise AssertionError("npx is required for browser UI regression")
    data = http_json(f"{SERVER}/api/session/{SESSION}")
    expected_nodes = len(data["nodes"])
    expected_edges = len(data["edges"])
    session_name = f"codex-canvas-regression-{os.getpid()}"
    run_cli([npx, "--yes", "--package", "@playwright/cli", "playwright-cli", f"-s={session_name}", "open", f"{SERVER}/?session={SESSION}"])
    try:
        console = run_cli([npx, "--yes", "--package", "@playwright/cli", "playwright-cli", f"-s={session_name}", "console", "error"])
        assert_true("Errors: 0" in console, f"browser console errors found: {console}")
        expression = (
            'JSON.stringify({'
            'formalNodes:document.querySelectorAll(".node:not(.discussion-node)").length,'
            'discussionNodes:document.querySelectorAll(".node.discussion-node").length,'
            'formalEdges:document.querySelectorAll(".edge-path:not(.discussion-edge)").length,'
            'discussionEdges:document.querySelectorAll(".edge-path.discussion-edge").length,'
            'regressionTitle:[].slice.call(document.querySelectorAll(".node-title")).filter(function(el){return el.textContent.indexOf("回归基线确认")>=0}).length,'
            'tagOverflow:[].slice.call(document.querySelectorAll(".node-tags")).some(function(el){return el.scrollWidth>el.clientWidth+1}),'
            'bodyOverflow:document.body.scrollWidth>window.innerWidth+1,'
            'versionOk:([].slice.call(document.scripts).map(function(s){return s.src}).join(" ")+" "+[].slice.call(document.querySelectorAll("link[rel=stylesheet]")).map(function(l){return l.href}).join(" ")).indexOf("'
            + VERSION
            + '")>=0'
            '})'
        )
        output = run_cli([
            npx,
            "--yes",
            "--package",
            "@playwright/cli",
            "playwright-cli",
            f"-s={session_name}",
            "eval",
            expression,
        ])
        ui = parse_cli_json_result(output)
        assert_equal(ui["formalNodes"], expected_nodes, "browser formal node count mismatch")
        assert_equal(ui["formalEdges"], expected_edges, "browser formal edge count mismatch")
        assert_equal(ui["discussionNodes"], 1 if expected_nodes else 0, "browser discussion node count mismatch")
        assert_equal(ui["discussionEdges"], 0, "browser should not render default discussion edge")
        assert_equal(ui["regressionTitle"], 1, "browser missing regression checkpoint node")
        assert_equal(ui["tagOverflow"], False, "browser node tags overflow")
        assert_equal(ui["bodyOverflow"], False, "browser body has horizontal overflow")
        assert_equal(ui["versionOk"], True, "browser did not load current asset version")
    finally:
        run_cli([npx, "--yes", "--package", "@playwright/cli", "playwright-cli", f"-s={session_name}", "close"], check=False)


def check_browser_interactions() -> None:
    npx = npx_executable()
    if not npx:
        raise AssertionError("npx is required for browser interaction regression")
    test_session = f"ui-regression-{os.getpid()}"
    browser_session = f"codex-canvas-ui-regression-{os.getpid()}"
    try:
        seed_interaction_session(test_session)
        run_cli([npx, "--yes", "--package", "@playwright/cli", "playwright-cli", f"-s={browser_session}", "open", f"{SERVER}/?session={test_session}"])
        initial = browser_eval_json(npx, browser_session, interaction_state_expression())
        assert_equal(initial["formalNodes"], 4, "interaction fixture node count mismatch")
        assert_equal(initial["formalEdges"], 3, "interaction fixture edge count mismatch")
        assert_equal(initial["discussionNodes"], 1, "interaction fixture discussion node missing")

        mainline = browser_eval_json(
            npx,
            browser_session,
            '(function(){document.getElementById("useMainlineOrderBtn").click();return JSON.stringify({prompt:document.getElementById("promptBox").value,nodeMentions:(document.getElementById("promptBox").value.match(/【/g)||[]).length});})()',
        )
        assert_equal(mainline["nodeMentions"], 4, "mainline composer did not include all nodes")
        assert_true("交互一" in mainline["prompt"] and "交互四" in mainline["prompt"], "mainline composer text missing expected nodes")

        cleared = browser_eval_json(
            npx,
            browser_session,
            '(function(){document.getElementById("clearComposerBtn").click();return JSON.stringify({prompt:document.getElementById("promptBox").value});})()',
        )
        assert_equal(cleared["prompt"], "", "clear composer did not empty prompt")

        selected = browser_eval_json(
            npx,
            browser_session,
            '(function(){document.querySelector(".node:not(.discussion-node)").click();document.getElementById("addToComposerBtn").click();return JSON.stringify({detail:document.getElementById("detailTitle").textContent,prompt:document.getElementById("promptBox").value});})()',
        )
        assert_equal(selected["detail"], "交互一", "node click did not show detail")
        assert_true("交互一" in selected["prompt"], "add selected node did not update prompt")

        after_select_edge_state = browser_eval_json(
            npx,
            browser_session,
            'JSON.stringify({discussionEdges:document.querySelectorAll(".edge-path.discussion-edge").length,formalEdges:document.querySelectorAll(".edge-path:not(.discussion-edge)").length})',
        )
        assert_equal(after_select_edge_state["discussionEdges"], 0, "selecting a node should not render a discussion edge")
        assert_equal(after_select_edge_state["formalEdges"], 3, "selecting a node should not change formal edges")

        reset = browser_eval_json(
            npx,
            browser_session,
            '(async function(){document.getElementById("resetCanvasBtn").click();await new Promise(function(resolve){setTimeout(resolve,600)});const data=await fetch("/api/session/'
            + test_session
            + '").then(function(response){return response.json()});return JSON.stringify({nodes:[].slice.call(document.querySelectorAll(".node:not(.discussion-node)")).map(function(el){return {left:el.style.left,top:el.style.top}}),edges:document.querySelectorAll(".edge-path:not(.discussion-edge)").length,edgePairs:data.edges.map(function(edge){return [edge.from,edge.to]}),undoDisabled:document.getElementById("undoEdgeBtn").disabled});})()',
        )
        assert_equal(reset["edges"], 3, "reset canvas changed formal edge count")
        assert_equal(reset["nodes"][0]["left"], "80px", "reset canvas did not restore first node x")
        assert_equal(reset["nodes"][0]["top"], "80px", "reset canvas did not restore first node y")
        assert_equal(reset["nodes"][3]["left"], "80px", "reset canvas did not wrap fourth node to first column")
        assert_equal(reset["nodes"][3]["top"], "310px", "reset canvas did not move fourth node to second row")
        assert_equal(reset["edgePairs"], [["ui_1", "ui_2"], ["ui_2", "ui_3"], ["ui_3", "ui_4"]], "reset canvas did not rebuild default mainline")
        assert_equal(reset["undoDisabled"], False, "reset canvas did not add an undo action")

        undo_reset = browser_eval_json(
            npx,
            browser_session,
            '(async function(){document.getElementById("undoEdgeBtn").click();await new Promise(function(resolve){setTimeout(resolve,700)});const data=await fetch("/api/session/'
            + test_session
            + '").then(function(response){return response.json()});return JSON.stringify({nodes:[].slice.call(document.querySelectorAll(".node:not(.discussion-node)")).map(function(el){return {left:el.style.left,top:el.style.top}}),edges:document.querySelectorAll(".edge-path:not(.discussion-edge)").length,edgePairs:data.edges.map(function(edge){return [edge.from,edge.to]}),undoDisabled:document.getElementById("undoEdgeBtn").disabled});})()',
        )
        assert_equal(undo_reset["edges"], 3, "undo reset changed formal edge count")
        assert_equal(undo_reset["nodes"][3]["left"], "1130px", "undo reset did not restore fourth node x")
        assert_equal(undo_reset["nodes"][3]["top"], "80px", "undo reset did not restore fourth node y")
        assert_equal(undo_reset["edgePairs"], [["ui_1", "ui_3"], ["ui_3", "ui_2"], ["ui_2", "ui_4"]], "undo reset did not restore previous edges")
        assert_equal(undo_reset["undoDisabled"], True, "undo stack should be empty after undoing reset in this fixture")
    finally:
        if npx:
            run_cli([npx, "--yes", "--package", "@playwright/cli", "playwright-cli", f"-s={browser_session}", "close"], check=False)
        delete_session_file(test_session)


def seed_interaction_session(session_id: str) -> None:
    nodes = [
        {"id": "ui_1", "type": "requirement", "title": "交互一", "summary": "第一节点", "contextText": "上下文一", "x": 80, "y": 80},
        {"id": "ui_2", "type": "decision", "title": "交互二", "summary": "第二节点", "contextText": "上下文二", "x": 430, "y": 80},
        {"id": "ui_3", "type": "implementation", "title": "交互三", "summary": "第三节点", "contextText": "上下文三", "x": 780, "y": 80},
        {"id": "ui_4", "type": "verification", "title": "交互四", "summary": "第四节点", "contextText": "上下文四", "x": 1130, "y": 80},
    ]
    for node in nodes:
        http_json(f"{SERVER}/api/session/{session_id}/nodes", method="POST", body=node)
    edges = [("ui_1", "ui_3"), ("ui_3", "ui_2"), ("ui_2", "ui_4")]
    for index, (from_id, to_id) in enumerate(edges, start=1):
        http_json(
            f"{SERVER}/api/session/{session_id}/edges",
            method="POST",
            body={"id": f"ui_edge_{index}", "from": from_id, "to": to_id, "label": ""},
        )


def interaction_state_expression() -> str:
    return (
        'JSON.stringify({'
        'formalNodes:document.querySelectorAll(".node:not(.discussion-node)").length,'
        'discussionNodes:document.querySelectorAll(".node.discussion-node").length,'
        'formalEdges:document.querySelectorAll(".edge-path:not(.discussion-edge)").length,'
        'discussionEdges:document.querySelectorAll(".edge-path.discussion-edge").length,'
        'prompt:document.getElementById("promptBox").value'
        '})'
    )


def browser_eval_json(npx: str, session_name: str, expression: str) -> dict[str, Any]:
    output = run_cli([
        npx,
        "--yes",
        "--package",
        "@playwright/cli",
        "playwright-cli",
        f"-s={session_name}",
        "eval",
        expression,
    ])
    return parse_cli_json_result(output)


def delete_session_file(session_id: str) -> None:
    session_file = Path.home() / ".codex-canvas" / "sessions" / f"{session_id}.json"
    if session_file.exists():
        session_file.unlink()


def npx_executable() -> str | None:
    return shutil.which("npx.cmd") or shutil.which("npx.exe") or shutil.which("npx")


def run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=str(WORKSPACE), text=True, encoding="utf-8", errors="replace", capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout or f"command failed: {' '.join(command)}")


def run_cli(command: list[str], check: bool = True) -> str:
    result = subprocess.run(command, cwd=str(WORKSPACE), text=True, encoding="utf-8", errors="replace", capture_output=True)
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    if check and result.returncode:
        raise AssertionError(output or f"command failed: {' '.join(command)}")
    return output


def parse_cli_json_result(output: str) -> dict[str, Any]:
    match = re.search(r"### Result\s*\n([\s\S]*?)(?:\n### |\Z)", output)
    if not match:
        raise AssertionError(f"could not parse playwright result: {output}")
    result_text = match.group(1).strip()
    if result_text.startswith('"'):
        return json.loads(json.loads(result_text))
    return json.loads(result_text)


def http_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def http_json(
    url: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    expected_status: int | None = None,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        request.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if expected_status is not None and response.status != expected_status:
                raise AssertionError(f"expected HTTP {expected_status} for {url}, got {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        if expected_status is not None and exc.code == expected_status:
            return json.loads(payload)
        raise AssertionError(f"HTTP {exc.code} for {url}: {payload}") from exc


class temp_env:
    def __init__(self, **values: str) -> None:
        self.values = values
        self.previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        for key, value in self.values.items():
            self.previous[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, *args: object) -> None:
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
