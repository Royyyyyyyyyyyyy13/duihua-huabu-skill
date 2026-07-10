from __future__ import annotations

import json
import http.client
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
SCRIPTS = ROOT / "scripts"


def main() -> int:
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.path.insert(0, str(SCRIPTS))
    checks = [
        check_v2_static_files,
        check_v2_store_invariants,
        check_v2_checkpoint_json_aliases,
        check_v2_concurrent_writes,
        check_anchor_no_source,
        check_anchor_no_false_match,
        check_recover_no_false_match,
        check_anchor_starter_backfill,
        check_anchor_starter_with_live_nodes_backfill,
        check_checkpoint_stdin_guard,
        check_v2_isolated_server,
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


def check_v2_static_files() -> None:
    frontend = ROOT / "frontend"
    npm = shutil.which("npm.cmd") or shutil.which("npm.exe") or shutil.which("npm")
    if not npm:
        raise AssertionError("npm is required for frontend validation")
    run_cli([npm, "--prefix", str(frontend), "run", "build"])
    run_cli([npm, "--prefix", str(frontend), "test"])
    run_cli([npm, "--prefix", str(frontend), "run", "notices"])

    for script_name in [
        "canvas_server.py",
        "canvas_store.py",
        "checkpoint.py",
        "conversation_anchor.py",
        "transcript_recovery.py",
    ]:
        script_path = SCRIPTS / script_name
        compile(script_path.read_text(encoding="utf-8"), str(script_path), "exec")

    schema = json.loads((ROOT / "data" / "schema.json").read_text(encoding="utf-8"))
    assert_equal(schema["schemaVersion"], 2, "schema version")
    notices = (WORKSPACE / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    plugin_notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert_true("## License Texts" in notices, "third-party license texts missing")
    assert_true("`dompurify@3.4.11`" in notices, "DOMPurify license notice missing")
    assert_equal(plugin_notices, notices, "plugin and repository license notices differ")
    assert_true((ROOT / "LICENSE").is_file(), "plugin package license missing")
    assert_true("positionMode" in schema["session"]["viewState"]["discussion"], "discussion position mode missing")

    web_root = ROOT / "assets" / "canvas"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    js_match = re.search(r'src="\./([^\"]+\.js)"', html)
    css_match = re.search(r'href="\./([^\"]+\.css)"', html)
    assert_true(bool(js_match and css_match), "hashed Vite assets missing from built index")
    assert_true((web_root / js_match.group(1)).is_file(), "built JavaScript asset missing")
    assert_true((web_root / css_match.group(1)).is_file(), "built CSS asset missing")
    assert_true((web_root / "favicon.svg").is_file(), "favicon missing")
    assert_true(not (web_root / "app.js").exists(), "legacy app.js should not remain")
    assert_true(not (web_root / "styles.css").exists(), "legacy styles.css should not remain")

    app_source = (frontend / "src" / "App.vue").read_text(encoding="utf-8")
    graph_source = (frontend / "src" / "lib" / "graph.js").read_text(encoding="utf-8")
    assert_true(':selection-key-code="true"' in app_source, "Vue Flow lasso configuration missing")
    assert_true("selection-on-drag" not in app_source, "unsupported Vue Flow selection prop returned")
    assert_true("clonePlain" in app_source, "reactive history snapshot guard missing")
    assert_true("positionMode" in app_source and "positionMode" in graph_source, "discussion collision state missing")
    assert_true('window.addEventListener("resize", onViewportResize)' in app_source, "responsive canvas refit missing")
    assert_true("删除选中关系" in app_source, "selected-edge delete command missing")
    assert_true((frontend / "tests" / "browser-regression.js").is_file(), "browser regression script missing")


def check_v2_store_invariants() -> None:
    with tempfile.TemporaryDirectory(prefix="canvas-v2-store-") as root, temp_env(CODEX_CANVAS_HOME=root):
        from canvas_store import (
            add_edge,
            add_node,
            load_session,
            reset_canvas,
            restore_canvas_state,
            safe_session_id,
            session_path,
            update_view_state,
        )

        add_node(
            "store-v2",
            {
                "id": "n1",
                "type": "requirement",
                "title": "需求",
                "summary": "保留摘要",
                "contextText": "压缩上下文",
            },
        )
        updated = add_node("store-v2", {"id": "n1", "title": "需求更新"})
        assert_equal(updated["summary"], "保留摘要", "partial node update cleared summary")
        assert_equal(updated["contextText"], "压缩上下文", "partial node update cleared context")
        add_node("store-v2", {"id": "n2", "type": "decision", "title": "决策", "summary": "二"})
        add_node("store-v2", {"id": "n3", "type": "verification", "title": "验证", "summary": "三"})
        add_edge("store-v2", {"id": "e12", "from": "n1", "to": "n2"})
        add_edge("store-v2", {"id": "e23", "from": "n2", "to": "n3"})
        duplicate = add_edge("store-v2", {"id": "duplicate", "from": "n1", "to": "n2"})
        assert_equal(duplicate["id"], "e12", "duplicate edge should return stored edge")
        try:
            add_edge("store-v2", {"id": "cycle", "from": "n3", "to": "n1"})
        except ValueError:
            pass
        else:
            raise AssertionError("cycle edge was accepted")

        view = update_view_state(
            "store-v2",
            {
                "discussion": {
                    "mode": "manual",
                    "anchorIds": ["n2"],
                    "position": {"x": 940, "y": 540},
                    "positionMode": "manual",
                    "anchorKey": "n2",
                }
            },
        )
        assert_equal(view["viewState"]["discussion"]["positionMode"], "manual", "manual position mode not stored")
        before = load_session("store-v2")
        snapshot = {
            "nodeIds": [node["id"] for node in before["nodes"]],
            "positions": {node["id"]: {"x": node["x"], "y": node["y"]} for node in before["nodes"]},
            "edges": before["edges"],
            "discussion": before["viewState"]["discussion"],
        }
        reset = reset_canvas("store-v2")
        assert_equal(len(reset["nodes"]), 3, "reset changed node count")
        assert_equal(len(reset["edges"]), 2, "reset did not rebuild mainline")
        assert_equal(reset["viewState"]["discussion"]["positionMode"], "auto", "reset did not restore auto discussion position")
        add_node("store-v2", {"id": "n4", "type": "artifact", "title": "新增", "summary": "四"})
        add_edge("store-v2", {"id": "e34", "from": "n3", "to": "n4"})
        restored = restore_canvas_state("store-v2", snapshot)
        assert_equal(len(restored["nodes"]), 4, "undo reset lost a newly generated node")
        assert_true(any(edge["from"] == "n3" and edge["to"] == "n4" for edge in restored["edges"]), "undo reset lost new-node edge")
        assert_equal(restored["viewState"]["discussion"]["positionMode"], "manual", "undo reset lost discussion position mode")
        assert_equal(restored["schemaVersion"], 2, "store schema version")
        assert_true(restored["revision"] > 0 and restored["contentRevision"] > 0, "session revisions did not advance")

        legacy_id = "中文 会话"
        legacy_path = session_path(legacy_id)
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "sessionId": "stale-copy-name",
                    "nodes": [{"id": "old", "type": "note", "title": "旧节点", "summary": "旧摘要"}],
                    "edges": [],
                    "composerOrder": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        legacy = load_session(legacy_id)
        assert_equal(legacy["sessionId"], safe_session_id(legacy_id), "requested session id did not override copied metadata")
        assert_equal(legacy["schemaVersion"], 2, "legacy session was not migrated")
        assert_equal(legacy["nodes"][0]["contentQuality"], "fallback", "legacy content quality missing")
        assert_true(bool(legacy["nodes"][0]["detailMarkdown"]), "legacy detail fallback missing")
        assert_equal(legacy["viewState"]["discussion"]["positionMode"], "auto", "legacy discussion position mode missing")
        backups = list(legacy_path.parent.glob(f"{legacy_path.stem}.schema-1-backup-*.json"))
        assert_equal(len(backups), 1, "legacy migration backup count")


def check_v2_checkpoint_json_aliases() -> None:
    with tempfile.TemporaryDirectory(prefix="canvas-v2-json-") as root:
        env = os.environ.copy()
        env.update({"CODEX_CANVAS_HOME": root, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        payload = {
            "sessionId": "批量 会话",
            "autoLink": True,
            "nodes": [
                {"id": "j1", "type": "requirement", "title": "批量一", "summary": "一", "contextText": "上下文一"},
                {"id": "j2", "type": "decision", "title": "批量二", "summary": "二", "detailMarkdown": "## 二"},
            ],
        }
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "checkpoint.py"), "--stdin-json"],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=env,
            cwd=str(WORKSPACE),
        )
        assert_equal(result.returncode, 0, f"checkpoint JSON aliases failed: {result.stderr}")
        output = json.loads(result.stdout)
        assert_equal(len(output["nodes"]), 2, "batch checkpoint output node count")
        assert_equal(len(output["edges"]), 1, "batch checkpoint output edge count")
        with temp_env(CODEX_CANVAS_HOME=root):
            from canvas_store import load_session

            data = load_session("批量 会话")
        assert_equal(len(data["nodes"]), 2, "batch checkpoint stored node count")
        assert_equal(len(data["edges"]), 1, "batch checkpoint stored edge count")
        assert_equal(data["revision"], 1, "batch checkpoints should commit atomically")
        assert_equal(data["contentRevision"], 1, "batch content revision should advance once")


def check_v2_concurrent_writes() -> None:
    with tempfile.TemporaryDirectory(prefix="canvas-v2-concurrency-") as root:
        env = os.environ.copy()
        env.update({"CODEX_CANVAS_HOME": root, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        processes = []
        for index in range(12):
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(SCRIPTS / "checkpoint.py"),
                        "--session",
                        "concurrent",
                        "--auto-link",
                        "--type",
                        "note",
                        "--title",
                        f"node-{index:02d}",
                        "--summary",
                        f"summary-{index:02d}",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    cwd=str(WORKSPACE),
                )
            )
        failures = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            if process.returncode:
                failures.append(stderr or stdout)
        assert_true(not failures, f"concurrent checkpoint process failed: {failures}")
        with temp_env(CODEX_CANVAS_HOME=root):
            from canvas_store import load_session, session_path

            data = load_session("concurrent")
            path = session_path("concurrent")
        assert_equal(len(data["nodes"]), 12, "concurrent writes lost nodes")
        assert_equal(len(data["edges"]), 11, "concurrent auto-link lost edges")
        assert_equal(len({node["id"] for node in data["nodes"]}), 12, "concurrent node ids collided")
        assert_equal(data["revision"], 12, "concurrent revision count")
        assert_true(not path.with_name(f".{path.name}.lock").exists(), "session lock file leaked")


def check_v2_isolated_server() -> None:
    with tempfile.TemporaryDirectory(prefix="canvas-v2-server-") as root:
        env = os.environ.copy()
        env.update({"CODEX_CANVAS_HOME": root, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        with temp_env(CODEX_CANVAS_HOME=root):
            from canvas_store import record_checkpoints

            record_checkpoints(
                "ui-regression",
                [
                    {
                        "id": f"ui_{index}",
                        "type": ["requirement", "decision", "plan", "implementation", "verification", "artifact"][index - 1],
                        "title": f"UI 节点 {index}",
                        "summary": f"第 {index} 个浏览器回归节点",
                        "detailMarkdown": (
                            "## 安全详情\n- [项目链接](https://example.com)\n<p onclick=\"window.__canvasXss=1\">安全正文</p>"
                            "<script>window.__canvasXss=1</script>"
                            if index == 1
                            else f"## 节点 {index}\n- 结构化详情"
                        ),
                        "contextText": f"压缩上下文 {index}",
                        "rawText": "用户（10:00）：浏览器回归。\n\n助手（10:01）：已记录。" if index == 1 else "",
                        "tags": ["浏览器", "回归"],
                        "origin": "live",
                        "confidence": "high",
                        "createdAt": f"2026-07-10T10:00:{index:02d}+08:00",
                    }
                    for index in range(1, 7)
                ],
                auto_link=True,
            )

        port = free_port()
        base = f"http://127.0.0.1:{port}"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        server = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPTS / "canvas_server.py"),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--session",
                "ui-regression",
                "--no-reuse",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=str(WORKSPACE),
            creationflags=creationflags,
        )
        browser_session = f"codex-canvas-v2-{os.getpid()}"
        npx = npx_executable()
        try:
            wait_for_server(f"{base}/api/health")
            health = http_json(f"{base}/api/health")
            assert_equal(health["schemaVersion"], 2, "health schema version")
            data = http_json(f"{base}/api/session/ui-regression")
            assert_equal(len(data["nodes"]), 6, "server fixture node count")
            assert_equal(len(data["edges"]), 5, "server fixture edge count")

            with urllib.request.urlopen(f"{base}/", timeout=5) as response:
                page_html = response.read().decode("utf-8")
                headers = response.headers
            assert_equal(response.status, 200, "static page status")
            assert_true("对话画布" in page_html, "static page title missing")
            assert_equal(headers.get("X-Content-Type-Options"), "nosniff", "nosniff header missing")
            assert_true("default-src 'self'" in (headers.get("Content-Security-Policy") or ""), "CSP header missing")
            expect_http_error(f"{base}/..%2f..%2fetc%2fpasswd", method="GET", data=None, status=403)
            with urllib.request.urlopen(f"{base}/favicon.svg", timeout=5) as response:
                assert_equal(response.status, 200, "favicon status")

            encoded_session = urllib.parse.quote("接口 测试", safe="")
            http_json(
                f"{base}/api/session/{encoded_session}/nodes",
                method="POST",
                body={"id": "api1", "type": "requirement", "title": "接口一", "summary": "一"},
            )
            http_json(
                f"{base}/api/session/{encoded_session}/nodes",
                method="POST",
                body={"id": "api2", "type": "verification", "title": "接口二", "summary": "二"},
            )
            api_data = http_json(f"{base}/api/session/{encoded_session}")
            assert_equal(api_data["sessionId"], "接口-测试", "Unicode session id API normalization")
            http_json(
                f"{base}/api/session/{encoded_session}/layout",
                method="POST",
                body={"positions": {"api1": {"x": 321, "y": 654}}},
            )
            api_data = http_json(f"{base}/api/session/{encoded_session}")
            assert_equal(len(api_data["nodes"]), 2, "partial layout save lost a node")
            assert_equal(next(node for node in api_data["nodes"] if node["id"] == "api1")["x"], 321, "layout position not stored")
            http_json(f"{base}/api/session/{encoded_session}/nodes/api1", method="DELETE", expected_status=405)
            cycle = http_json(
                f"{base}/api/session/ui-regression/edges",
                method="POST",
                body={"id": "cycle", "from": "ui_6", "to": "ui_1"},
                expected_status=400,
            )
            assert_true("环" in cycle.get("error", "") or "cycle" in cycle.get("error", "").lower(), "cycle error message missing")
            expect_http_error(
                f"{base}/api/session/{encoded_session}/nodes",
                method="POST",
                data=b"{",
                status=400,
            )
            expect_oversized_request_rejected(base, f"/api/session/{encoded_session}/nodes")
            with urllib.request.urlopen(f"{base}/api/session/{encoded_session}/export", timeout=5) as response:
                assert_true("attachment" in (response.headers.get("Content-Disposition") or ""), "export disposition missing")

            if not npx:
                raise AssertionError("npx is required for browser regression")
            run_cli(
                [
                    npx,
                    "--yes",
                    "--package",
                    "@playwright/cli",
                    "playwright-cli",
                    f"-s={browser_session}",
                    "open",
                    f"{base}/?session=ui-regression",
                ]
            )
            browser_output = run_cli(
                [
                    npx,
                    "--yes",
                    "--package",
                    "@playwright/cli",
                    "playwright-cli",
                    f"-s={browser_session}",
                    "run-code",
                    "--filename",
                    str(ROOT / "frontend" / "tests" / "browser-regression.js"),
                ]
            )
            assert_true("ok" in browser_output and "true" in browser_output.lower(), f"browser regression result missing: {browser_output}")
            console = run_cli(
                [
                    npx,
                    "--yes",
                    "--package",
                    "@playwright/cli",
                    "playwright-cli",
                    f"-s={browser_session}",
                    "console",
                    "error",
                ]
            )
            assert_true("Errors: 0" in console, f"browser console errors found: {console}")
        finally:
            if npx:
                run_cli(
                    [npx, "--yes", "--package", "@playwright/cli", "playwright-cli", f"-s={browser_session}", "close"],
                    check=False,
                )
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(url: str) -> None:
    last_error: Exception | None = None
    for _ in range(80):
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.1)
    raise AssertionError(f"server did not start: {last_error}")


def expect_http_error(url: str, *, method: str, data: bytes | None, status: int) -> None:
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("content-type", "application/json")
    try:
        urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        exc.read()
        assert_equal(exc.code, status, f"HTTP status for {url}")
        return
    raise AssertionError(f"expected HTTP {status} for {url}")


def expect_oversized_request_rejected(base: str, path: str) -> None:
    parsed = urllib.parse.urlparse(base)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    try:
        connection.putrequest("POST", path)
        connection.putheader("content-type", "application/json")
        connection.putheader("content-length", str(2 * 1024 * 1024 + 1))
        connection.endheaders()
        response = connection.getresponse()
        response.read()
        assert_equal(response.status, 413, "oversized request status")
    finally:
        connection.close()



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
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        command,
        input="x",
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=str(WORKSPACE),
        env=env,
    )
    assert_equal(result.returncode, 2, "checkpoint stdin guard should return code 2")
    assert_true("一次只能使用一个" in result.stderr, "checkpoint stdin guard message missing")



def npx_executable() -> str | None:
    return shutil.which("npx.cmd") or shutil.which("npx.exe") or shutil.which("npx")



def run_cli(command: list[str], check: bool = True) -> str:
    result = subprocess.run(command, cwd=str(WORKSPACE), text=True, encoding="utf-8", errors="replace", capture_output=True)
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    if check and result.returncode:
        raise AssertionError(output or f"command failed: {' '.join(command)}")
    return output



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
