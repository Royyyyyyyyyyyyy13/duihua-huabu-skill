from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from canvas_store import (
    DATA_SCHEMA_VERSION,
    SessionConflictError,
    add_edge,
    add_node,
    delete_edge,
    load_session,
    plugin_version,
    reset_canvas,
    restore_canvas_state,
    safe_session_id,
    set_composer_state,
    update_edge,
    update_layout,
    update_node,
    update_view_state,
)
from conversation_anchor import bootstrap_anchor_node
from transcript_recovery import recover_session_raw_text


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PLUGIN_ROOT / "assets" / "canvas"
MAX_REQUEST_BYTES = 2 * 1024 * 1024
APP_ID = "codex-canvas"


class RequestError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class CanvasHandler(BaseHTTPRequestHandler):
    server_version = "CodexCanvas/2.0"

    def do_GET(self) -> None:
        self.handle_request(self.dispatch_get)

    def do_POST(self) -> None:
        self.handle_request(self.dispatch_post)

    def do_PATCH(self) -> None:
        self.handle_request(self.dispatch_patch)

    def do_DELETE(self) -> None:
        self.handle_request(self.dispatch_delete)

    def handle_request(self, handler) -> None:
        try:
            handler()
        except RequestError as exc:
            self.send_json({"error": str(exc)}, status=exc.status)
        except (ValueError, SessionConflictError, TimeoutError) as exc:
            self.send_json({"error": str(exc)}, status=409 if isinstance(exc, SessionConflictError) else 400)
        except BrokenPipeError:
            return
        except Exception as exc:
            self.send_json({"error": f"本地画布服务处理失败：{exc}"}, status=500)

    def dispatch_get(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/health":
            self.send_json(
                {
                    "ok": True,
                    "app": APP_ID,
                    "pluginVersion": plugin_version(),
                    "schemaVersion": DATA_SCHEMA_VERSION,
                }
            )
            return
        parts = self.api_parts(path)
        if len(parts) == 3 and parts[:2] == ["api", "session"]:
            self.send_json(load_session(parts[2]))
            return
        if len(parts) == 4 and parts[:2] == ["api", "session"] and parts[3] == "export":
            session = load_session(parts[2])
            filename = f"codex-canvas-{safe_session_id(parts[2])}.json"
            encoded_filename = urllib.parse.quote(filename, safe="")
            disposition = f"attachment; filename=\"codex-canvas-export.json\"; filename*=UTF-8''{encoded_filename}"
            self.send_json(session, extra_headers={"content-disposition": disposition})
            return
        if path.startswith("/api/"):
            raise RequestError("接口不存在", status=404)
        self.serve_static(path)

    def dispatch_post(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        parts = self.api_parts(path)
        body = self.read_json()
        if len(parts) != 4 or parts[:2] != ["api", "session"]:
            raise RequestError("接口不存在", status=404)
        session_id = parts[2]
        action = parts[3]
        if action == "nodes":
            self.send_json(add_node(session_id, body), status=201)
            return
        if action == "edges":
            self.send_json(add_edge(session_id, body), status=201)
            return
        if action == "layout":
            self.send_json(update_layout(session_id, body.get("positions", {})))
            return
        if action == "composer":
            self.send_json(
                set_composer_state(
                    session_id,
                    body.get("composerOrder", []),
                    body.get("composerMode"),
                )
            )
            return
        if action == "view":
            self.send_json(update_view_state(session_id, body))
            return
        if action == "reset":
            self.send_json(reset_canvas(session_id))
            return
        if action == "restore-canvas":
            self.send_json(restore_canvas_state(session_id, body))
            return
        if action == "bootstrap-anchor":
            self.send_json(bootstrap_anchor_node(session_id, workspace_hint=body.get("workspaceHint")))
            return
        if action == "recover-raw-text":
            result = recover_session_raw_text(session_id, workspace_hint=body.get("workspaceHint"))
            self.send_json(result, status=200 if result.get("ok") else 404)
            return
        raise RequestError("接口不存在", status=404)

    def dispatch_patch(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        parts = self.api_parts(path)
        if len(parts) != 5 or parts[:2] != ["api", "session"]:
            raise RequestError("接口不存在", status=404)
        body = self.read_json()
        if parts[3] == "nodes":
            node = update_node(parts[2], parts[4], body)
            if not node:
                raise RequestError("节点不存在", status=404)
            self.send_json(node)
            return
        if parts[3] == "edges":
            edge = update_edge(parts[2], parts[4], body)
            if not edge:
                raise RequestError("连线不存在", status=404)
            self.send_json(edge)
            return
        raise RequestError("接口不存在", status=404)

    def dispatch_delete(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        parts = self.api_parts(path)
        if len(parts) != 5 or parts[:2] != ["api", "session"]:
            raise RequestError("接口不存在", status=404)
        if parts[3] == "nodes":
            raise RequestError("checkpoint 节点属于对话记录，不能删除", status=405)
        if parts[3] == "edges":
            self.send_json({"ok": delete_edge(parts[2], parts[4])})
            return
        raise RequestError("接口不存在", status=404)

    def api_parts(self, path: str) -> list[str]:
        return [urllib.parse.unquote(part) for part in path.strip("/").split("/")]

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("content-length", "0") or "0")
        except ValueError as exc:
            raise RequestError("Content-Length 无效") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise RequestError("请求内容过大", status=413)
        if not length:
            return {}
        try:
            raw = self.rfile.read(length).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RequestError("请求必须使用 UTF-8 编码") from exc
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RequestError(f"JSON 格式错误：{exc.msg}") from exc
        if not isinstance(value, dict):
            raise RequestError("JSON 顶层必须是对象")
        return value

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else urllib.parse.unquote(request_path.lstrip("/"))
        target = (WEB_ROOT / relative).resolve()
        web_root = WEB_ROOT.resolve()
        if web_root not in target.parents and target != web_root:
            raise RequestError("禁止访问该路径", status=403)
        if not target.exists() or not target.is_file():
            raise RequestError("资源不存在", status=404)
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_common_headers(content_type=content_type, length=len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_common_headers(self, *, content_type: str, length: int) -> None:
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(length))
        self.send_header("cache-control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("pragma", "no-cache")
        self.send_header("expires", "0")
        self.send_header("x-content-type-options", "nosniff")
        self.send_header("x-frame-options", "DENY")
        self.send_header("referrer-policy", "no-referrer")
        self.send_header(
            "content-security-policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; frame-ancestors 'none'",
        )

    def send_json(
        self,
        data: Any,
        status: int = 200,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_common_headers(content_type="application/json; charset=utf-8", length=len(body))
        for key, value in dict(extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0


def running_canvas_port(host: str, start: int) -> int | None:
    for port in range(start, start + 40):
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=0.25) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if payload.get("ok") and payload.get("app") == APP_ID:
            return port
    return None


def choose_port(host: str, start: int) -> int:
    for port in range(start, start + 40):
        if port_is_free(host, port):
            return port
    raise RuntimeError("没有可用的本地端口")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex Canvas local server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--session", default=None)
    parser.add_argument("--open", action="store_true", help="Open the canvas in the default browser.")
    parser.add_argument("--no-reuse", action="store_true", help="Always start a new server process.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = safe_session_id(args.session)
    existing_port = None if args.no_reuse else running_canvas_port(args.host, args.port)
    if existing_port is not None:
        url = f"http://{args.host}:{existing_port}/?session={urllib.parse.quote(session, safe='')}"
        print(f"Codex Canvas session: {session}")
        print(f"Codex Canvas URL: {url}")
        print("Reusing the running Codex Canvas server.")
        if args.open:
            webbrowser.open(url)
        return 0

    port = choose_port(args.host, args.port)
    url = f"http://{args.host}:{port}/?session={urllib.parse.quote(session, safe='')}"
    server = ThreadingHTTPServer((args.host, port), CanvasHandler)
    print(f"Codex Canvas session: {session}")
    print(f"Codex Canvas URL: {url}")
    print("Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped Codex Canvas.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
