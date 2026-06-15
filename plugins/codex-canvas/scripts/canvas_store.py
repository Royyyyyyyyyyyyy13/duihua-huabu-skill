from __future__ import annotations

import json
import math
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATA_SCHEMA_VERSION = 1
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
NODE_TYPES = {
    "anchor",
    "requirement",
    "decision",
    "plan",
    "implementation",
    "verification",
    "blocker",
    "artifact",
    "note",
}
NODE_ORIGINS = {"live", "reconstructed", "imported"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}

_STORE_LOCK = threading.RLock()
GRID_LEFT = 80
GRID_TOP = 80
GRID_COLUMN_GAP = 350
GRID_ROW_GAP = 230
GRID_COLUMNS = 3


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_session_id(session_id: str | None) -> str:
    value = (session_id or os.environ.get("CODEX_CANVAS_SESSION") or "default").strip()
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value)
    value = value.strip("-._")
    return value[:96] or "default"


def clean_text(value: Any) -> str:
    text = str(value or "")
    return text.encode("utf-8", errors="replace").decode("utf-8")


def clean_text_list(values: Any) -> list[str]:
    return [clean_text(value) for value in list(values or [])]


def plugin_version() -> str:
    manifest = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return clean_text(data.get("version") or "unknown")


def clean_enum(value: Any, allowed: set[str], fallback: str) -> str:
    text = clean_text(value).strip()
    return text if text in allowed else fallback


def data_home() -> Path:
    root = os.environ.get("CODEX_CANVAS_HOME")
    if root:
        return Path(root).expanduser()
    return Path.home() / ".codex-canvas"


def session_path(session_id: str | None) -> Path:
    session = safe_session_id(session_id)
    return data_home() / "sessions" / f"{session}.json"


def empty_session(session_id: str | None) -> dict[str, Any]:
    session = safe_session_id(session_id)
    version = plugin_version()
    return {
        "schemaVersion": DATA_SCHEMA_VERSION,
        "sessionId": session,
        "createdByPluginVersion": version,
        "lastOpenedByPluginVersion": version,
        "updatedAt": now_iso(),
        "nodes": [],
        "edges": [],
        "composerOrder": [],
    }


def normalize_session(data: dict[str, Any], session_id: str | None) -> dict[str, Any]:
    version = plugin_version()
    data["schemaVersion"] = DATA_SCHEMA_VERSION
    data.setdefault("sessionId", safe_session_id(session_id))
    data.setdefault("createdByPluginVersion", "unknown")
    data["lastOpenedByPluginVersion"] = version
    data["nodes"] = [normalize_node(node) for node in list(data.get("nodes") or []) if isinstance(node, dict)]
    data["edges"] = [normalize_edge(edge) for edge in list(data.get("edges") or []) if isinstance(edge, dict)]
    node_ids = {node.get("id") for node in data["nodes"]}
    data["edges"] = [
        edge
        for edge in data["edges"]
        if edge.get("from") in node_ids and edge.get("to") in node_ids and edge.get("from") != edge.get("to")
    ]
    data["composerOrder"] = [
        node_id for node_id in list(data.get("composerOrder") or []) if isinstance(node_id, str) and node_id in node_ids
    ]
    return data


def normalize_node(node: dict[str, Any]) -> dict[str, Any]:
    node_type = clean_enum(node.get("type"), NODE_TYPES, "note")
    tags = clean_text_list(node.get("tags"))
    default_origin = "reconstructed" if node_type == "anchor" and "启示节点" in tags else "live"
    origin = clean_enum(node.get("origin"), NODE_ORIGINS, default_origin)
    confidence = clean_enum(node.get("confidence"), CONFIDENCE_LEVELS, "medium" if origin == "reconstructed" else "high")
    return {
        "id": clean_text(node.get("id") or f"node_{uuid.uuid4().hex[:10]}").strip(),
        "type": node_type,
        "title": clean_text(node.get("title") or "Untitled checkpoint").strip(),
        "summary": clean_text(node.get("summary")).strip(),
        "rawText": clean_text(node.get("rawText")).strip(),
        "detailMarkdown": clean_text(node.get("detailMarkdown")).strip(),
        "contextText": clean_text(node.get("contextText")).strip(),
        "source": clean_enum(node.get("source"), {"user", "assistant", "mixed"}, "assistant"),
        "origin": origin,
        "confidence": confidence,
        "relatedFiles": clean_text_list(node.get("relatedFiles")),
        "evidenceRefs": clean_text_list(node.get("evidenceRefs")),
        "tags": tags,
        "status": clean_enum(node.get("status"), {"active", "resolved", "archived"}, "active"),
        "x": node.get("x", 0),
        "y": node.get("y", 0),
        "createdAt": clean_text(node.get("createdAt") or now_iso()),
    }


def normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": clean_text(edge.get("id") or f"edge_{uuid.uuid4().hex[:10]}").strip(),
        "from": clean_text(edge.get("from")).strip(),
        "to": clean_text(edge.get("to")).strip(),
        "label": clean_text(edge.get("label")).strip(),
        "createdAt": clean_text(edge.get("createdAt") or now_iso()),
    }


def clean_coordinate(value: Any, fallback: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return int(number) if number.is_integer() else number


def backup_corrupt_file(path: Path, raw: str) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
    backup.write_text(raw, encoding="utf-8")


def backup_migration_file(path: Path, raw: str, schema_version: Any) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    version = "none" if schema_version is None else clean_text(schema_version)
    backup = path.with_name(f"{path.stem}.schema-{version}-backup-{stamp}{path.suffix}")
    backup.write_text(raw, encoding="utf-8")


def recover_session(path: Path, raw: str, session_id: str | None) -> dict[str, Any]:
    backup_corrupt_file(path, raw)
    try:
        data, _ = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError:
        data = empty_session(session_id)
    if not isinstance(data, dict):
        data = empty_session(session_id)
    return save_session(session_id, normalize_session(data, session_id))


def load_session(session_id: str | None) -> dict[str, Any]:
    path = session_path(session_id)
    if not path.exists():
        return empty_session(session_id)
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = recover_session(path, raw, session_id)
    if not isinstance(data, dict):
        data = empty_session(session_id)
    previous_schema_version = data.get("schemaVersion")
    data = normalize_session(data, session_id)
    if previous_schema_version != DATA_SCHEMA_VERSION:
        backup_migration_file(path, raw, previous_schema_version)
        return save_session(session_id, data)
    return data


def save_session(session_id: str | None, data: dict[str, Any]) -> dict[str, Any]:
    path = session_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["sessionId"] = safe_session_id(session_id)
    data["updatedAt"] = now_iso()
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with _STORE_LOCK:
        try:
            with tmp_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
    return data


def add_node(session_id: str | None, node: dict[str, Any]) -> dict[str, Any]:
    with _STORE_LOCK:
        data = load_session(session_id)
        node_type = node.get("type") or "note"
        if node_type not in NODE_TYPES:
            node_type = "note"
        requested_id = clean_text(node.get("id")).strip()
        if requested_id:
            for existing in data["nodes"]:
                if existing.get("id") != requested_id:
                    continue
                if "type" in node:
                    existing["type"] = node_type
                for key in [
                    "title",
                    "summary",
                    "rawText",
                    "detailMarkdown",
                    "contextText",
                    "source",
                    "origin",
                    "confidence",
                    "status",
                ]:
                    if key in node:
                        if key == "origin":
                            existing[key] = clean_enum(node.get(key), NODE_ORIGINS, existing.get("origin") or "live")
                        elif key == "confidence":
                            existing[key] = clean_enum(
                                node.get(key), CONFIDENCE_LEVELS, existing.get("confidence") or "high"
                            )
                        elif key == "source":
                            existing[key] = clean_enum(node.get(key), {"user", "assistant", "mixed"}, "assistant")
                        elif key == "status":
                            existing[key] = clean_enum(node.get(key), {"active", "resolved", "archived"}, "active")
                        else:
                            existing[key] = clean_text(node.get(key)).strip()
                for key in ["relatedFiles", "evidenceRefs", "tags"]:
                    if key in node:
                        existing[key] = clean_text_list(node.get(key))
                if "x" in node:
                    existing["x"] = node.get("x")
                if "y" in node:
                    existing["y"] = node.get("y")
                if node.get("createdAt"):
                    existing["createdAt"] = node.get("createdAt")
                save_session(session_id, data)
                return existing
        index = len(data["nodes"])
        new_node = {
            "id": requested_id or f"node_{uuid.uuid4().hex[:10]}",
            "type": node_type,
            "title": clean_text(node.get("title") or "Untitled checkpoint").strip(),
            "summary": clean_text(node.get("summary")).strip(),
            "rawText": clean_text(node.get("rawText")).strip(),
            "detailMarkdown": clean_text(node.get("detailMarkdown")).strip(),
            "contextText": clean_text(node.get("contextText")).strip(),
            "source": clean_enum(node.get("source"), {"user", "assistant", "mixed"}, "assistant"),
            "origin": clean_enum(node.get("origin"), NODE_ORIGINS, "live"),
            "confidence": clean_enum(node.get("confidence"), CONFIDENCE_LEVELS, "high"),
            "relatedFiles": clean_text_list(node.get("relatedFiles")),
            "evidenceRefs": clean_text_list(node.get("evidenceRefs")),
            "tags": clean_text_list(node.get("tags")),
            "status": clean_enum(node.get("status"), {"active", "resolved", "archived"}, "active"),
            "x": node.get("x", GRID_LEFT + (index % GRID_COLUMNS) * GRID_COLUMN_GAP),
            "y": node.get("y", GRID_TOP + (index // GRID_COLUMNS) * GRID_ROW_GAP),
            "createdAt": node.get("createdAt") or now_iso(),
        }
        data["nodes"].append(new_node)
        save_session(session_id, data)
        return new_node


def update_node(session_id: str | None, node_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    with _STORE_LOCK:
        data = load_session(session_id)
        for node in data["nodes"]:
            if node.get("id") == node_id:
                for key in [
                    "type",
                    "title",
                    "summary",
                    "rawText",
                    "detailMarkdown",
                    "contextText",
                    "source",
                    "origin",
                    "confidence",
                    "relatedFiles",
                    "evidenceRefs",
                    "tags",
                    "status",
                    "x",
                    "y",
                ]:
                    if key in patch:
                        if key in {"title", "summary", "rawText", "detailMarkdown", "contextText"}:
                            node[key] = clean_text(patch[key])
                        elif key == "source":
                            node[key] = clean_enum(patch[key], {"user", "assistant", "mixed"}, "assistant")
                        elif key == "origin":
                            node[key] = clean_enum(patch[key], NODE_ORIGINS, node.get("origin") or "live")
                        elif key == "confidence":
                            node[key] = clean_enum(
                                patch[key], CONFIDENCE_LEVELS, node.get("confidence") or "high"
                            )
                        elif key == "status":
                            node[key] = clean_enum(patch[key], {"active", "resolved", "archived"}, "active")
                        elif key in {"relatedFiles", "evidenceRefs", "tags"}:
                            node[key] = clean_text_list(patch[key])
                        else:
                            node[key] = patch[key]
                save_session(session_id, data)
                return node
        return None


def add_edge(session_id: str | None, edge: dict[str, Any]) -> dict[str, Any]:
    with _STORE_LOCK:
        data = load_session(session_id)
        new_edge = {
            "id": edge.get("id") or f"edge_{uuid.uuid4().hex[:10]}",
            "from": edge.get("from"),
            "to": edge.get("to"),
            "label": edge.get("label") or "",
            "createdAt": edge.get("createdAt") or now_iso(),
        }
        validate_edge(data, new_edge["from"], new_edge["to"])
        exists = any(
            item.get("from") == new_edge["from"] and item.get("to") == new_edge["to"]
            for item in data["edges"]
        )
        if exists:
            return next(
                item
                for item in data["edges"]
                if item.get("from") == new_edge["from"] and item.get("to") == new_edge["to"]
            )
        data["edges"].append(new_edge)
        composer_order = data.get("composerOrder", [])
        for node_id in [new_edge["from"], new_edge["to"]]:
            if node_id not in composer_order:
                composer_order.append(node_id)
        data["composerOrder"] = composer_order
        save_session(session_id, data)
        return new_edge


def validate_edge(data: dict[str, Any], from_id: str | None, to_id: str | None) -> None:
    if not from_id or not to_id or from_id == to_id:
        raise ValueError("edge requires different from/to node ids")
    node_ids = {node.get("id") for node in data.get("nodes", [])}
    if from_id not in node_ids or to_id not in node_ids:
        raise ValueError("edge endpoint node does not exist")


def update_edge(session_id: str | None, edge_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    with _STORE_LOCK:
        data = load_session(session_id)
        for edge in data["edges"]:
            if edge.get("id") != edge_id:
                continue
            next_from = patch.get("from", edge.get("from"))
            next_to = patch.get("to", edge.get("to"))
            validate_edge(data, next_from, next_to)
            exists = any(
                item.get("id") != edge_id and item.get("from") == next_from and item.get("to") == next_to
                for item in data["edges"]
            )
            if exists:
                raise ValueError("edge already exists")
            edge["from"] = next_from
            edge["to"] = next_to
            if "label" in patch:
                edge["label"] = patch.get("label") or ""
            save_session(session_id, data)
            return edge
        return None


def reset_canvas(session_id: str | None) -> dict[str, Any]:
    with _STORE_LOCK:
        data = load_session(session_id)
        nodes = data.get("nodes", [])
        for index, node in enumerate(nodes):
            node["x"] = GRID_LEFT + (index % GRID_COLUMNS) * GRID_COLUMN_GAP
            node["y"] = GRID_TOP + (index // GRID_COLUMNS) * GRID_ROW_GAP
        data["edges"] = [
            {
                "id": f"reset_edge_{index:02d}",
                "from": previous.get("id"),
                "to": current.get("id"),
                "label": "",
                "createdAt": now_iso(),
            }
            for index, (previous, current) in enumerate(zip(nodes, nodes[1:]), start=1)
            if previous.get("id") and current.get("id")
        ]
        return save_session(session_id, data)


def restore_canvas_state(session_id: str | None, snapshot: dict[str, Any]) -> dict[str, Any]:
    with _STORE_LOCK:
        data = load_session(session_id)
        nodes = data.get("nodes", [])
        positions = snapshot.get("positions", {})
        if not isinstance(positions, dict):
            positions = {}
        for node in nodes:
            pos = positions.get(node.get("id"))
            if not isinstance(pos, dict):
                continue
            node["x"] = clean_coordinate(pos.get("x"), node.get("x", 0))
            node["y"] = clean_coordinate(pos.get("y"), node.get("y", 0))

        node_ids = {node.get("id") for node in nodes}
        next_edges = []
        seen_pairs: set[tuple[str, str]] = set()
        for item in list(snapshot.get("edges") or []):
            if not isinstance(item, dict):
                continue
            from_id = clean_text(item.get("from")).strip()
            to_id = clean_text(item.get("to")).strip()
            if not from_id or not to_id or from_id == to_id:
                continue
            if from_id not in node_ids or to_id not in node_ids:
                continue
            pair = (from_id, to_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            restored = normalize_edge(item)
            restored["from"] = from_id
            restored["to"] = to_id
            next_edges.append(restored)
        data["edges"] = next_edges
        return save_session(session_id, data)


def delete_edge(session_id: str | None, edge_id: str) -> bool:
    with _STORE_LOCK:
        data = load_session(session_id)
        before = len(data["edges"])
        data["edges"] = [edge for edge in data["edges"] if edge.get("id") != edge_id]
        save_session(session_id, data)
        return len(data["edges"]) != before
