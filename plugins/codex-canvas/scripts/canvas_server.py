from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from canvas_store import (
    add_edge,
    add_node,
    delete_edge,
    load_session,
    reset_canvas,
    restore_canvas_state,
    safe_session_id,
    save_session,
    update_edge,
    update_node,
)
from conversation_anchor import bootstrap_anchor_node
from transcript_recovery import recover_session_raw_text


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PLUGIN_ROOT / "assets" / "canvas"


class CanvasHandler(BaseHTTPRequestHandler):
    server_version = "CodexCanvas/0.1"

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/session/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                self.send_json(load_session(parts[2]))
                return
            self.send_error(404)
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        parts = path.strip("/").split("/")
        body = self.read_json()
        if len(parts) == 4 and parts[:2] == ["api", "session"] and parts[3] == "nodes":
            self.send_json(add_node(parts[2], body), status=201)
            return
        if len(parts) == 4 and parts[:2] == ["api", "session"] and parts[3] == "edges":
            try:
                self.send_json(add_edge(parts[2], body), status=201)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        if len(parts) == 4 and parts[:2] == ["api", "session"] and parts[3] == "layout":
            data = load_session(parts[2])
            positions = body.get("positions", {})
            for node in data["nodes"]:
                pos = positions.get(node.get("id"))
                if pos:
                    node["x"] = pos.get("x", node.get("x", 0))
                    node["y"] = pos.get("y", node.get("y", 0))
            self.send_json(save_session(parts[2], data))
            return
        if len(parts) == 4 and parts[:2] == ["api", "session"] and parts[3] == "composer":
            data = load_session(parts[2])
            node_ids = {node.get("id") for node in data.get("nodes", [])}
            requested = body.get("composerOrder", [])
            data["composerOrder"] = [
                node_id for node_id in requested if isinstance(node_id, str) and node_id in node_ids
            ]
            self.send_json(save_session(parts[2], data))
            return
        if len(parts) == 4 and parts[:2] == ["api", "session"] and parts[3] == "reset":
            self.send_json(reset_canvas(parts[2]))
            return
        if len(parts) == 4 and parts[:2] == ["api", "session"] and parts[3] == "restore-canvas":
            self.send_json(restore_canvas_state(parts[2], body))
            return
        if len(parts) == 4 and parts[:2] == ["api", "session"] and parts[3] == "bootstrap-anchor":
            result = bootstrap_anchor_node(parts[2], workspace_hint=str(Path.cwd()))
            self.send_json(result)
            return
        if len(parts) == 4 and parts[:2] == ["api", "session"] and parts[3] == "recover-raw-text":
            result = recover_session_raw_text(parts[2], workspace_hint=str(Path.cwd()))
            self.send_json(result, status=200 if result.get("ok") else 404)
            return
        self.send_error(404)

    def do_PATCH(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) == 5 and parts[:2] == ["api", "session"] and parts[3] == "nodes":
            node = update_node(parts[2], parts[4], self.read_json())
            if node:
                self.send_json(node)
            else:
                self.send_error(404)
            return
        if len(parts) == 5 and parts[:2] == ["api", "session"] and parts[3] == "edges":
            try:
                edge = update_edge(parts[2], parts[4], self.read_json())
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
                return
            if edge:
                self.send_json(edge)
            else:
                self.send_error(404)
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) == 5 and parts[:2] == ["api", "session"] and parts[3] == "nodes":
            self.send_json({"error": "checkpoint nodes are preserved and cannot be deleted"}, status=405)
            return
        if len(parts) == 5 and parts[:2] == ["api", "session"] and parts[3] == "edges":
            self.send_json({"ok": delete_edge(parts[2], parts[4])})
            return
        self.send_error(404)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or "0")
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
            self.send_error(403)
            return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("pragma", "no-cache")
        self.send_header("expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0


def choose_port(host: str, start: int) -> int:
    for port in range(start, start + 40):
        if port_is_free(host, port):
            return port
    raise RuntimeError("No free port found")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex Canvas local server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--session", default=None)
    parser.add_argument("--open", action="store_true", help="Open the canvas in the default browser.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = safe_session_id(args.session)
    port = choose_port(args.host, args.port)
    url = f"http://{args.host}:{port}/?session={urllib.parse.quote(session)}"
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
