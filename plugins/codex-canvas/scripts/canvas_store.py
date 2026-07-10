from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar


DATA_SCHEMA_VERSION = 2
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
CONTENT_QUALITIES = {"full", "compact", "fallback"}
NODE_STATUSES = {"active", "resolved", "archived"}
COMPOSER_MODES = {"mainline", "manual"}
DISCUSSION_MODES = {"auto", "manual"}
DISCUSSION_POSITION_MODES = {"auto", "manual"}

GRID_LEFT = 80
GRID_TOP = 80
GRID_COLUMN_GAP = 350
GRID_ROW_GAP = 230
GRID_COLUMNS = 3

_STORE_LOCK = threading.RLock()
_FILE_LOCK_TIMEOUT_SECONDS = 10.0
_STALE_LOCK_SECONDS = 60.0
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

T = TypeVar("T")
Mutator = Callable[[dict[str, Any]], tuple[T, bool, bool]]


class SessionConflictError(RuntimeError):
    """Raised when a caller attempts to save an outdated full-session snapshot."""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_session_id(session_id: str | None) -> str:
    value = str(session_id or os.environ.get("CODEX_CANVAS_SESSION") or "default").strip()
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-._ ")
    value = value[:96].rstrip(". ") or "default"
    if value.upper() in _WINDOWS_RESERVED_NAMES:
        value = f"session-{value}"
    return value


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def clean_text_list(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        text = clean_text(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def clean_enum(value: Any, allowed: set[str], fallback: str) -> str:
    text = clean_text(value).strip()
    return text if text in allowed else fallback


def clean_coordinate(value: Any, fallback: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return int(number) if number.is_integer() else number


def clean_non_negative_int(value: Any, fallback: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, number)


def plugin_version() -> str:
    manifest = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return clean_text(data.get("version") or "unknown")


def data_home() -> Path:
    root = os.environ.get("CODEX_CANVAS_HOME")
    if root:
        return Path(root).expanduser()
    return Path.home() / ".codex-canvas"


def session_path(session_id: str | None) -> Path:
    return data_home() / "sessions" / f"{safe_session_id(session_id)}.json"


def empty_session(session_id: str | None) -> dict[str, Any]:
    version = plugin_version()
    return {
        "schemaVersion": DATA_SCHEMA_VERSION,
        "sessionId": safe_session_id(session_id),
        "revision": 0,
        "contentRevision": 0,
        "createdByPluginVersion": version,
        "lastOpenedByPluginVersion": version,
        "updatedAt": now_iso(),
        "nodes": [],
        "edges": [],
        "composerOrder": [],
        "viewState": default_view_state(),
        "migrations": [],
    }


def default_view_state() -> dict[str, Any]:
    return {
        "composerMode": "mainline",
        "discussion": {
            "mode": "auto",
            "anchorIds": [],
            "position": None,
            "positionMode": "auto",
            "anchorKey": "",
        },
    }


def fallback_detail(title: str, summary: str) -> str:
    content = summary or title or "该阶段只有简要记录。"
    return f"## 阶段摘要\n\n{content}"


def normalize_node(node: dict[str, Any]) -> dict[str, Any]:
    node_type = clean_enum(node.get("type"), NODE_TYPES, "note")
    tags = clean_text_list(node.get("tags"))
    default_origin = "reconstructed" if node_type == "anchor" and "启示节点" in tags else "live"
    origin = clean_enum(node.get("origin"), NODE_ORIGINS, default_origin)
    confidence = clean_enum(
        node.get("confidence"),
        CONFIDENCE_LEVELS,
        "medium" if origin == "reconstructed" else "high",
    )
    title = clean_text(node.get("title") or "未命名检查点").strip()
    summary = clean_text(node.get("summary")).strip()
    raw_text = clean_text(node.get("rawText")).strip()
    original_detail = clean_text(node.get("detailMarkdown")).strip()
    original_context = clean_text(node.get("contextText")).strip()
    detail = original_detail or fallback_detail(title, summary)
    context = original_context or summary or title
    inferred_quality = "full" if original_detail and original_context else "compact" if original_detail or original_context else "fallback"
    quality = clean_enum(node.get("contentQuality"), CONTENT_QUALITIES, inferred_quality)
    return {
        "id": clean_text(node.get("id") or f"node_{uuid.uuid4().hex[:10]}").strip(),
        "type": node_type,
        "title": title,
        "summary": summary,
        "rawText": raw_text,
        "detailMarkdown": detail,
        "contextText": context,
        "contentQuality": quality,
        "source": clean_enum(node.get("source"), {"user", "assistant", "mixed"}, "assistant"),
        "origin": origin,
        "confidence": confidence,
        "relatedFiles": clean_text_list(node.get("relatedFiles")),
        "evidenceRefs": clean_text_list(node.get("evidenceRefs")),
        "tags": tags,
        "status": clean_enum(node.get("status"), NODE_STATUSES, "active"),
        "x": clean_coordinate(node.get("x"), 0),
        "y": clean_coordinate(node.get("y"), 0),
        "createdAt": clean_text(node.get("createdAt") or now_iso()),
        "updatedAt": clean_text(node.get("updatedAt") or node.get("createdAt") or now_iso()),
    }


def normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": clean_text(edge.get("id") or f"edge_{uuid.uuid4().hex[:10]}").strip(),
        "from": clean_text(edge.get("from")).strip(),
        "to": clean_text(edge.get("to")).strip(),
        "label": clean_text(edge.get("label")).strip(),
        "createdAt": clean_text(edge.get("createdAt") or now_iso()),
        "updatedAt": clean_text(edge.get("updatedAt") or edge.get("createdAt") or now_iso()),
    }


def normalize_view_state(value: Any, node_ids: set[str], composer_order: list[str]) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    composer_mode = clean_enum(
        raw.get("composerMode"),
        COMPOSER_MODES,
        "manual" if composer_order else "mainline",
    )
    raw_discussion = raw.get("discussion") if isinstance(raw.get("discussion"), dict) else {}
    anchor_ids = [node_id for node_id in clean_text_list(raw_discussion.get("anchorIds")) if node_id in node_ids]
    position = raw_discussion.get("position")
    if isinstance(position, dict):
        x = clean_coordinate(position.get("x"), None)
        y = clean_coordinate(position.get("y"), None)
        position = {"x": x, "y": y} if x is not None and y is not None else None
    else:
        position = None
    return {
        "composerMode": composer_mode,
        "discussion": {
            "mode": clean_enum(raw_discussion.get("mode"), DISCUSSION_MODES, "auto"),
            "anchorIds": anchor_ids,
            "position": position,
            "positionMode": clean_enum(
                raw_discussion.get("positionMode"),
                DISCUSSION_POSITION_MODES,
                "auto",
            ),
            "anchorKey": clean_text(raw_discussion.get("anchorKey")).strip(),
        },
    }


def normalize_session(data: dict[str, Any], session_id: str | None) -> dict[str, Any]:
    version = plugin_version()
    nodes: list[dict[str, Any]] = []
    seen_node_ids: set[str] = set()
    for item in list(data.get("nodes") or []):
        if not isinstance(item, dict):
            continue
        node = normalize_node(item)
        if not node["id"] or node["id"] in seen_node_ids:
            continue
        seen_node_ids.add(node["id"])
        nodes.append(node)

    edges: list[dict[str, Any]] = []
    seen_edge_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for item in list(data.get("edges") or []):
        if not isinstance(item, dict):
            continue
        edge = normalize_edge(item)
        pair = (edge["from"], edge["to"])
        if (
            not edge["id"]
            or edge["id"] in seen_edge_ids
            or edge["from"] not in seen_node_ids
            or edge["to"] not in seen_node_ids
            or edge["from"] == edge["to"]
            or pair in seen_pairs
        ):
            continue
        seen_edge_ids.add(edge["id"])
        seen_pairs.add(pair)
        edges.append(edge)

    composer_order = [
        node_id
        for node_id in clean_text_list(data.get("composerOrder"))
        if node_id in seen_node_ids
    ]
    migrations = [item for item in list(data.get("migrations") or []) if isinstance(item, dict)][-20:]
    return {
        "schemaVersion": DATA_SCHEMA_VERSION,
        "sessionId": safe_session_id(session_id if session_id is not None else data.get("sessionId")),
        "revision": clean_non_negative_int(data.get("revision")),
        "contentRevision": clean_non_negative_int(data.get("contentRevision")),
        "createdByPluginVersion": clean_text(data.get("createdByPluginVersion") or "unknown"),
        "lastOpenedByPluginVersion": version,
        "updatedAt": clean_text(data.get("updatedAt") or now_iso()),
        "nodes": nodes,
        "edges": edges,
        "composerOrder": composer_order,
        "viewState": normalize_view_state(data.get("viewState"), seen_node_ids, composer_order),
        "migrations": migrations,
    }


def backup_corrupt_file(path: Path, raw: str) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}").write_text(raw, encoding="utf-8")


def backup_migration_file(path: Path, raw: str, schema_version: Any) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    version = "none" if schema_version is None else clean_text(schema_version)
    path.with_name(f"{path.stem}.schema-{version}-backup-{stamp}{path.suffix}").write_text(raw, encoding="utf-8")


@contextmanager
def session_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    started = time.monotonic()
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"pid={os.getpid()} time={time.time()}".encode("ascii", errors="replace"))
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > _STALE_LOCK_SECONDS:
                    lock_path.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() - started >= _FILE_LOCK_TIMEOUT_SECONDS:
                raise TimeoutError(f"session file is busy: {path.name}")
            time.sleep(0.05)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _read_session_unlocked(path: Path, session_id: str | None) -> tuple[dict[str, Any], str, Any, bool]:
    if not path.exists():
        return empty_session(session_id), "", DATA_SCHEMA_VERSION, False
    raw = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        backup_corrupt_file(path, raw)
        return empty_session(session_id), raw, None, True
    if not isinstance(parsed, dict):
        backup_corrupt_file(path, raw)
        return empty_session(session_id), raw, None, True
    previous_schema = parsed.get("schemaVersion")
    normalized = normalize_session(parsed, session_id)
    return normalized, raw, previous_schema, normalized != parsed


def _record_migration(data: dict[str, Any], previous_schema: Any) -> None:
    if previous_schema == DATA_SCHEMA_VERSION:
        return
    entry = {
        "from": previous_schema,
        "to": DATA_SCHEMA_VERSION,
        "at": now_iso(),
        "pluginVersion": plugin_version(),
    }
    data["migrations"] = [*list(data.get("migrations") or []), entry][-20:]


def _write_session_unlocked(path: Path, data: dict[str, Any], *, bump_revision: bool = True) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if bump_revision:
        data["revision"] = clean_non_negative_int(data.get("revision")) + 1
    data["schemaVersion"] = DATA_SCHEMA_VERSION
    data["lastOpenedByPluginVersion"] = plugin_version()
    data["updatedAt"] = now_iso()
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return data


def load_session(session_id: str | None) -> dict[str, Any]:
    path = session_path(session_id)
    if not path.exists():
        return empty_session(session_id)
    with _STORE_LOCK, session_file_lock(path):
        data, raw, previous_schema, changed = _read_session_unlocked(path, session_id)
        if previous_schema != DATA_SCHEMA_VERSION:
            if raw:
                backup_migration_file(path, raw, previous_schema)
            _record_migration(data, previous_schema)
            changed = True
        if changed:
            _write_session_unlocked(path, data)
        return data


def save_session(session_id: str | None, data: dict[str, Any]) -> dict[str, Any]:
    """Save a full snapshot only when its revision is still current."""

    path = session_path(session_id)
    expected_revision = clean_non_negative_int(data.get("revision"))
    with _STORE_LOCK, session_file_lock(path):
        current, raw, previous_schema, migration_changed = _read_session_unlocked(path, session_id)
        if path.exists() and current.get("revision") != expected_revision:
            raise SessionConflictError(
                f"session revision changed: expected {expected_revision}, current {current.get('revision')}"
            )
        normalized = normalize_session(dict(data), session_id)
        normalized["createdByPluginVersion"] = current.get("createdByPluginVersion") or normalized["createdByPluginVersion"]
        if previous_schema != DATA_SCHEMA_VERSION:
            if raw:
                backup_migration_file(path, raw, previous_schema)
            _record_migration(normalized, previous_schema)
        elif migration_changed:
            normalized["migrations"] = current.get("migrations", normalized.get("migrations", []))
        return _write_session_unlocked(path, normalized)


def _mutate_session(session_id: str | None, mutator: Mutator[T]) -> tuple[T, dict[str, Any]]:
    path = session_path(session_id)
    with _STORE_LOCK, session_file_lock(path):
        data, raw, previous_schema, migration_changed = _read_session_unlocked(path, session_id)
        if previous_schema != DATA_SCHEMA_VERSION:
            if raw:
                backup_migration_file(path, raw, previous_schema)
            _record_migration(data, previous_schema)
            migration_changed = True
        result, changed, content_changed = mutator(data)
        if content_changed:
            data["contentRevision"] = clean_non_negative_int(data.get("contentRevision")) + 1
        if changed or migration_changed or not path.exists():
            _write_session_unlocked(path, data)
        return result, data


def _upsert_node_data(data: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
    requested_id = clean_text(payload.get("id")).strip()
    for index, existing in enumerate(data["nodes"]):
        if requested_id and existing.get("id") == requested_id:
            merged = dict(existing)
            for key in [
                "type",
                "title",
                "summary",
                "rawText",
                "detailMarkdown",
                "contextText",
                "contentQuality",
                "source",
                "origin",
                "confidence",
                "relatedFiles",
                "evidenceRefs",
                "tags",
                "status",
                "x",
                "y",
                "createdAt",
            ]:
                if key in payload and payload.get(key) is not None:
                    merged[key] = payload.get(key)
            merged["id"] = requested_id
            merged["updatedAt"] = now_iso()
            normalized = normalize_node(merged)
            changed = normalized != existing
            data["nodes"][index] = normalized
            content_changed = changed and any(
                key in payload
                for key in [
                    "type",
                    "title",
                    "summary",
                    "rawText",
                    "detailMarkdown",
                    "contextText",
                    "contentQuality",
                    "source",
                    "origin",
                    "confidence",
                    "relatedFiles",
                    "evidenceRefs",
                    "tags",
                    "status",
                ]
            )
            return normalized, False, content_changed

    index = len(data["nodes"])
    candidate = dict(payload)
    candidate["id"] = requested_id or f"node_{uuid.uuid4().hex[:10]}"
    candidate.setdefault("x", GRID_LEFT + (index % GRID_COLUMNS) * GRID_COLUMN_GAP)
    candidate.setdefault("y", GRID_TOP + (index // GRID_COLUMNS) * GRID_ROW_GAP)
    candidate.setdefault("createdAt", now_iso())
    candidate.setdefault("updatedAt", candidate["createdAt"])
    node = normalize_node(candidate)
    data["nodes"].append(node)
    return node, True, True


def _append_edge_data(data: dict[str, Any], payload: dict[str, Any], *, validate_cycle: bool = True) -> tuple[dict[str, Any], bool]:
    from_id = clean_text(payload.get("from")).strip()
    to_id = clean_text(payload.get("to")).strip()
    validate_edge(data, from_id, to_id, validate_cycle=validate_cycle)
    for existing in data["edges"]:
        if existing.get("from") == from_id and existing.get("to") == to_id:
            return existing, False
    requested_id = clean_text(payload.get("id")).strip()
    if requested_id and any(edge.get("id") == requested_id for edge in data["edges"]):
        raise ValueError("连线 id 已存在")
    edge = normalize_edge(
        {
            "id": requested_id or f"edge_{uuid.uuid4().hex[:10]}",
            "from": from_id,
            "to": to_id,
            "label": payload.get("label") or "",
            "createdAt": payload.get("createdAt") or now_iso(),
            "updatedAt": now_iso(),
        }
    )
    data["edges"].append(edge)
    return edge, True


def add_node(session_id: str | None, node: dict[str, Any]) -> dict[str, Any]:
    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        saved, created, content_changed = _upsert_node_data(data, node)
        return saved, created or content_changed, content_changed

    result, _ = _mutate_session(session_id, mutate)
    return result


def record_checkpoint(
    session_id: str | None,
    node: dict[str, Any],
    *,
    auto_link: bool = False,
) -> dict[str, Any]:
    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        previous = data["nodes"][-1] if data["nodes"] else None
        saved, created, content_changed = _upsert_node_data(data, node)
        edge = None
        edge_changed = False
        if auto_link and created and previous and previous.get("id") != saved.get("id"):
            edge, edge_changed = _append_edge_data(
                data,
                {"from": previous.get("id"), "to": saved.get("id"), "label": ""},
            )
        return {"node": saved, "edge": edge}, created or content_changed or edge_changed, content_changed

    result, _ = _mutate_session(session_id, mutate)
    return result


def record_checkpoints(
    session_id: str | None,
    nodes: list[dict[str, Any]],
    *,
    auto_link: bool = True,
) -> dict[str, Any]:
    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        previous = data["nodes"][-1] if data["nodes"] else None
        saved_nodes: list[dict[str, Any]] = []
        saved_edges: list[dict[str, Any]] = []
        changed = False
        content_changed = False
        for payload in nodes:
            saved, created, node_content_changed = _upsert_node_data(data, payload)
            saved_nodes.append(saved)
            changed = changed or created or node_content_changed
            content_changed = content_changed or node_content_changed
            if auto_link and created and previous and previous.get("id") != saved.get("id"):
                edge, edge_changed = _append_edge_data(
                    data,
                    {"from": previous.get("id"), "to": saved.get("id"), "label": ""},
                )
                if edge_changed:
                    saved_edges.append(edge)
                    changed = True
            if created:
                previous = saved
        return {"nodes": saved_nodes, "edges": saved_edges}, changed, content_changed

    result, data = _mutate_session(session_id, mutate)
    result["session"] = data
    return result


def insert_reconstructed_nodes(
    session_id: str | None,
    nodes: list[dict[str, Any]],
    existing_ids: list[str] | None = None,
) -> dict[str, Any]:
    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        saved_nodes: list[dict[str, Any]] = []
        new_ids: list[str] = []
        content_changed = False
        for payload in nodes:
            saved, created, node_content_changed = _upsert_node_data(data, payload)
            saved_nodes.append(saved)
            new_ids.append(saved["id"])
            content_changed = content_changed or node_content_changed

        node_by_id = {item["id"]: item for item in data["nodes"]}
        ordered_ids = [node_id for node_id in new_ids if node_id in node_by_id]
        for node_id in list(existing_ids or []):
            if node_id in node_by_id and node_id not in ordered_ids:
                ordered_ids.append(node_id)
        for item in data["nodes"]:
            if item["id"] not in ordered_ids:
                ordered_ids.append(item["id"])
        data["nodes"] = [node_by_id[node_id] for node_id in ordered_ids]
        for index, item in enumerate(data["nodes"]):
            item["x"] = GRID_LEFT + (index % GRID_COLUMNS) * GRID_COLUMN_GAP
            item["y"] = GRID_TOP + (index // GRID_COLUMNS) * GRID_ROW_GAP

        changed = bool(nodes)
        previous = None
        for item in saved_nodes:
            if previous:
                _, edge_changed = _append_edge_data(
                    data,
                    {"from": previous["id"], "to": item["id"], "label": ""},
                )
                changed = changed or edge_changed
            previous = item
        first_existing = next((node_id for node_id in list(existing_ids or []) if node_id in node_by_id), None)
        if previous and first_existing and previous["id"] != first_existing:
            _, edge_changed = _append_edge_data(
                data,
                {"from": previous["id"], "to": first_existing, "label": ""},
            )
            changed = changed or edge_changed
        return {"nodes": saved_nodes}, changed, content_changed

    result, data = _mutate_session(session_id, mutate)
    result["session"] = data
    return result


def update_node(session_id: str | None, node_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    payload = dict(patch)
    payload["id"] = node_id

    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any] | None, bool, bool]:
        if not any(item.get("id") == node_id for item in data["nodes"]):
            return None, False, False
        saved, _, content_changed = _upsert_node_data(data, payload)
        changed = content_changed or any(key in patch for key in {"x", "y"})
        return saved, changed, content_changed

    result, _ = _mutate_session(session_id, mutate)
    return result


def update_nodes_bulk(session_id: str | None, patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def mutate(data: dict[str, Any]) -> tuple[list[dict[str, Any]], bool, bool]:
        saved_nodes: list[dict[str, Any]] = []
        changed = False
        content_changed = False
        ids = {item.get("id") for item in data["nodes"]}
        for patch in patches:
            node_id = clean_text(patch.get("id")).strip()
            if not node_id or node_id not in ids:
                continue
            saved, _, node_content_changed = _upsert_node_data(data, patch)
            saved_nodes.append(saved)
            changed = changed or node_content_changed
            content_changed = content_changed or node_content_changed
        return saved_nodes, changed, content_changed

    result, _ = _mutate_session(session_id, mutate)
    return result


def add_edge(session_id: str | None, edge: dict[str, Any]) -> dict[str, Any]:
    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        saved, changed = _append_edge_data(data, edge)
        return saved, changed, False

    result, _ = _mutate_session(session_id, mutate)
    return result


def validate_edge(
    data: dict[str, Any],
    from_id: str | None,
    to_id: str | None,
    *,
    ignore_edge_id: str | None = None,
    validate_cycle: bool = True,
) -> None:
    if not from_id or not to_id or from_id == to_id:
        raise ValueError("连线起点和终点必须是两个不同节点")
    node_ids = {node.get("id") for node in data.get("nodes", [])}
    if from_id not in node_ids or to_id not in node_ids:
        raise ValueError("连线端点不存在")
    if validate_cycle and _would_create_cycle(data, from_id, to_id, ignore_edge_id=ignore_edge_id):
        raise ValueError("这条连线会形成循环，无法用于主线组装")


def _would_create_cycle(
    data: dict[str, Any],
    from_id: str,
    to_id: str,
    *,
    ignore_edge_id: str | None = None,
) -> bool:
    outgoing: dict[str, list[str]] = {}
    for edge in data.get("edges", []):
        if edge.get("id") == ignore_edge_id:
            continue
        outgoing.setdefault(clean_text(edge.get("from")), []).append(clean_text(edge.get("to")))
    outgoing.setdefault(from_id, []).append(to_id)
    stack = [to_id]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current == from_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(outgoing.get(current, []))
    return False


def update_edge(session_id: str | None, edge_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any] | None, bool, bool]:
        for index, edge in enumerate(data["edges"]):
            if edge.get("id") != edge_id:
                continue
            next_from = clean_text(patch.get("from", edge.get("from"))).strip()
            next_to = clean_text(patch.get("to", edge.get("to"))).strip()
            validate_edge(data, next_from, next_to, ignore_edge_id=edge_id)
            if any(
                item.get("id") != edge_id and item.get("from") == next_from and item.get("to") == next_to
                for item in data["edges"]
            ):
                raise ValueError("这条连线已经存在")
            updated = normalize_edge(
                {
                    **edge,
                    "from": next_from,
                    "to": next_to,
                    "label": patch.get("label", edge.get("label")) or "",
                    "updatedAt": now_iso(),
                }
            )
            changed = updated != edge
            data["edges"][index] = updated
            return updated, changed, False
        return None, False, False

    result, _ = _mutate_session(session_id, mutate)
    return result


def delete_edge(session_id: str | None, edge_id: str) -> bool:
    def mutate(data: dict[str, Any]) -> tuple[bool, bool, bool]:
        before = len(data["edges"])
        data["edges"] = [edge for edge in data["edges"] if edge.get("id") != edge_id]
        changed = len(data["edges"]) != before
        return changed, changed, False

    result, _ = _mutate_session(session_id, mutate)
    return result


def update_layout(session_id: str | None, positions: Any) -> dict[str, Any]:
    requested = positions if isinstance(positions, dict) else {}

    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        changed = False
        for node in data["nodes"]:
            position = requested.get(node.get("id"))
            if not isinstance(position, dict):
                continue
            next_x = clean_coordinate(position.get("x"), node.get("x", 0))
            next_y = clean_coordinate(position.get("y"), node.get("y", 0))
            if next_x != node.get("x") or next_y != node.get("y"):
                node["x"] = next_x
                node["y"] = next_y
                node["updatedAt"] = now_iso()
                changed = True
        return data, changed, False

    _, data = _mutate_session(session_id, mutate)
    return data


def set_composer_state(
    session_id: str | None,
    composer_order: Any,
    composer_mode: Any = None,
) -> dict[str, Any]:
    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        node_ids = {node.get("id") for node in data["nodes"]}
        order = [node_id for node_id in clean_text_list(composer_order) if node_id in node_ids]
        mode = clean_enum(
            composer_mode,
            COMPOSER_MODES,
            data.get("viewState", {}).get("composerMode", "manual"),
        )
        changed = order != data.get("composerOrder") or mode != data["viewState"].get("composerMode")
        data["composerOrder"] = order
        data["viewState"]["composerMode"] = mode
        return data, changed, False

    _, data = _mutate_session(session_id, mutate)
    return data


def update_view_state(session_id: str | None, patch: Any) -> dict[str, Any]:
    requested = patch if isinstance(patch, dict) else {}

    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        merged = dict(data.get("viewState") or {})
        if "composerMode" in requested:
            merged["composerMode"] = requested.get("composerMode")
        if isinstance(requested.get("discussion"), dict):
            merged["discussion"] = {
                **dict(merged.get("discussion") or {}),
                **requested["discussion"],
            }
        normalized = normalize_view_state(
            merged,
            {node.get("id") for node in data["nodes"]},
            data.get("composerOrder", []),
        )
        changed = normalized != data.get("viewState")
        data["viewState"] = normalized
        return data, changed, False

    _, data = _mutate_session(session_id, mutate)
    return data


def reset_canvas(session_id: str | None) -> dict[str, Any]:
    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        before = json.dumps(
            {
                "positions": [(node.get("id"), node.get("x"), node.get("y")) for node in data["nodes"]],
                "edges": [(edge.get("from"), edge.get("to")) for edge in data["edges"]],
                "discussion": data["viewState"].get("discussion"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for index, node in enumerate(data["nodes"]):
            node["x"] = GRID_LEFT + (index % GRID_COLUMNS) * GRID_COLUMN_GAP
            node["y"] = GRID_TOP + (index // GRID_COLUMNS) * GRID_ROW_GAP
            node["updatedAt"] = now_iso()
        data["edges"] = [
            normalize_edge(
                {
                    "id": f"reset_edge_{index:02d}",
                    "from": previous.get("id"),
                    "to": current.get("id"),
                    "label": "",
                    "createdAt": now_iso(),
                }
            )
            for index, (previous, current) in enumerate(zip(data["nodes"], data["nodes"][1:]), start=1)
            if previous.get("id") and current.get("id")
        ]
        data["viewState"]["discussion"] = default_view_state()["discussion"]
        after = json.dumps(
            {
                "positions": [(node.get("id"), node.get("x"), node.get("y")) for node in data["nodes"]],
                "edges": [(edge.get("from"), edge.get("to")) for edge in data["edges"]],
                "discussion": data["viewState"].get("discussion"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return data, before != after, False

    _, data = _mutate_session(session_id, mutate)
    return data


def restore_canvas_state(session_id: str | None, snapshot: dict[str, Any]) -> dict[str, Any]:
    requested = snapshot if isinstance(snapshot, dict) else {}

    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        before = json.dumps(data, ensure_ascii=False, sort_keys=True)
        positions = requested.get("positions") if isinstance(requested.get("positions"), dict) else {}
        snapshot_node_ids = set(clean_text_list(requested.get("nodeIds"))) or set(positions.keys())
        for node in data["nodes"]:
            position = positions.get(node.get("id"))
            if not isinstance(position, dict):
                continue
            node["x"] = clean_coordinate(position.get("x"), node.get("x", 0))
            node["y"] = clean_coordinate(position.get("y"), node.get("y", 0))
            node["updatedAt"] = now_iso()

        node_ids = {node.get("id") for node in data["nodes"]}
        restored_edges: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for item in list(requested.get("edges") or []):
            if not isinstance(item, dict):
                continue
            edge = normalize_edge(item)
            pair = (edge["from"], edge["to"])
            if edge["from"] not in node_ids or edge["to"] not in node_ids or edge["from"] == edge["to"] or pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            restored_edges.append(edge)
        for edge in data["edges"]:
            if edge.get("from") in snapshot_node_ids and edge.get("to") in snapshot_node_ids:
                continue
            pair = (edge.get("from"), edge.get("to"))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            restored_edges.append(edge)
        data["edges"] = restored_edges

        if isinstance(requested.get("discussion"), dict):
            data["viewState"] = normalize_view_state(
                {
                    **data["viewState"],
                    "discussion": requested["discussion"],
                },
                node_ids,
                data.get("composerOrder", []),
            )
        changed = before != json.dumps(data, ensure_ascii=False, sort_keys=True)
        return data, changed, False

    _, data = _mutate_session(session_id, mutate)
    return data
