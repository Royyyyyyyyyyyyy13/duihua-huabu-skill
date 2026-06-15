const TYPE_LABELS = {
  anchor: "启示",
  discussion: "讨论中",
  requirement: "需求",
  decision: "决策",
  plan: "方案",
  implementation: "实现",
  verification: "验证",
  blocker: "阻塞",
  artifact: "产物",
  note: "备注",
};

const TYPE_COLORS = {
  anchor: "#0f9f9a",
  discussion: "#ff6d5a",
  requirement: "#4c7dff",
  decision: "#ff6d5a",
  plan: "#805ad5",
  implementation: "#18a058",
  verification: "#0f9f9a",
  blocker: "#d92d20",
  artifact: "#b7791f",
  note: "#64748b",
};

const params = new URLSearchParams(window.location.search);
const sessionId = params.get("session") || "default";
const apiRoot = `/api/session/${encodeURIComponent(sessionId)}`;
const localKey = `codex-canvas:${sessionId}`;
const discussionPositionKey = `codex-canvas:discussion-position:${sessionId}`;
const detailWidthKey = `codex-canvas:detail-width`;
const composerHeightKey = `codex-canvas:composer-height`;

let state = {
  sessionId,
  nodes: [],
  edges: [],
  composerOrder: [],
};

let selectedNodeId = null;
let selectedNodeIds = new Set();
let selectedEdgeId = null;
let hoveredEdgeId = null;
let connectSourceId = null;
let dragState = null;
let discussionDragState = null;
let selectionState = null;
let connectDragState = null;
let reconnectDragState = null;
let suppressNodeClickUntil = 0;
let suppressCanvasClickUntil = 0;
let apiAvailable = true;
let promptDirty = false;
let discussionPosition = loadDiscussionPosition();
let anchorBootstrapStarted = false;
let anchorBootstrapBlocked = false;

const canvas = document.getElementById("canvas");
const app = document.querySelector(".app");
const workspace = document.getElementById("workspace");
const nodesLayer = document.getElementById("nodesLayer");
const edgesLayer = document.getElementById("edgesLayer");
const edgeHotLayer = document.getElementById("edgeHotLayer");
const selectionBox = document.getElementById("selectionBox");
const detailResizeHandle = document.getElementById("detailResizeHandle");
const composerResizeHandle = document.getElementById("composerResizeHandle");
const emptyState = document.getElementById("emptyState");
const sessionBadge = document.getElementById("sessionBadge");
const detailEmpty = document.getElementById("detailEmpty");
const detailContent = document.getElementById("detailContent");
const promptBox = document.getElementById("promptBox");
const connectHint = document.getElementById("connectHint");
const recoveryStatus = document.getElementById("recoveryStatus");
const undoEdgeBtn = document.getElementById("undoEdgeBtn");

sessionBadge.textContent = `session: ${sessionId}`;

const DISCUSSION_NODE_ID = "__discussion__";
const undoStack = [];
const NODE_WIDTH = 270;
const NODE_HEIGHT = 150;
const GRID_LEFT = 80;
const GRID_TOP = 80;
const GRID_COLUMN_GAP = 350;
const GRID_ROW_GAP = 230;
const GRID_COLUMNS = 3;
const MIN_DETAIL_WIDTH = 280;
const MAX_DETAIL_WIDTH = 720;
const MIN_COMPOSER_HEIGHT = 150;
const MAX_COMPOSER_HEIGHT_RATIO = 0.58;

function nodeById(id) {
  return state.nodes.find((node) => node.id === id);
}

function edgeById(id) {
  return state.edges.find((edge) => edge.id === id);
}

function loadDiscussionPosition() {
  try {
    const value = JSON.parse(localStorage.getItem(discussionPositionKey) || "null");
    if (!value || typeof value !== "object") return null;
    if (!Number.isFinite(value.x) || !Number.isFinite(value.y) || !(value.anchorKey || value.anchorId)) return null;
    return value;
  } catch {
    return null;
  }
}

function saveDiscussionPosition() {
  if (!discussionPosition) {
    localStorage.removeItem(discussionPositionKey);
    return;
  }
  localStorage.setItem(discussionPositionKey, JSON.stringify(discussionPosition));
}

function clearDiscussionPosition() {
  discussionPosition = null;
  saveDiscussionPosition();
}

function initializePanelSizes() {
  const detailWidth = Number(localStorage.getItem(detailWidthKey));
  const composerHeight = Number(localStorage.getItem(composerHeightKey));
  if (Number.isFinite(detailWidth)) setDetailWidth(detailWidth);
  if (Number.isFinite(composerHeight)) setComposerHeight(composerHeight);
}

function setDetailWidth(width) {
  const maxWidth = Math.min(MAX_DETAIL_WIDTH, Math.max(MIN_DETAIL_WIDTH, window.innerWidth - 620));
  const value = clamp(width, MIN_DETAIL_WIDTH, maxWidth);
  workspace.style.setProperty("--detail-width", `${value}px`);
  localStorage.setItem(detailWidthKey, String(value));
  renderCanvasExtent();
}

function setComposerHeight(height) {
  const maxHeight = Math.max(MIN_COMPOSER_HEIGHT, Math.round(window.innerHeight * MAX_COMPOSER_HEIGHT_RATIO));
  const value = clamp(height, MIN_COMPOSER_HEIGHT, maxHeight);
  app.style.setProperty("--composer-height", `${value}px`);
  document.documentElement.style.setProperty("--composer-height", `${value}px`);
  localStorage.setItem(composerHeightKey, String(value));
  renderCanvasExtent();
}

function currentDetailWidth() {
  return Number.parseFloat(getComputedStyle(workspace).getPropertyValue("--detail-width")) || 360;
}

function currentComposerHeight() {
  return Number.parseFloat(getComputedStyle(app).getPropertyValue("--composer-height")) || 238;
}

function startDetailResize(event) {
  if (event.button !== 0) return;
  event.preventDefault();
  const startX = event.clientX;
  const startWidth = currentDetailWidth();
  document.body.classList.add("is-resizing-panel");
  const onMove = (moveEvent) => {
    setDetailWidth(startWidth - (moveEvent.clientX - startX));
  };
  const onEnd = () => {
    document.removeEventListener("pointermove", onMove);
    document.removeEventListener("pointerup", onEnd);
    document.removeEventListener("pointercancel", onEnd);
    document.body.classList.remove("is-resizing-panel");
  };
  document.addEventListener("pointermove", onMove);
  document.addEventListener("pointerup", onEnd);
  document.addEventListener("pointercancel", onEnd);
}

function startComposerResize(event) {
  if (event.button !== 0) return;
  event.preventDefault();
  const startY = event.clientY;
  const startHeight = currentComposerHeight();
  document.body.classList.add("is-resizing-composer");
  const onMove = (moveEvent) => {
    setComposerHeight(startHeight - (moveEvent.clientY - startY));
  };
  const onEnd = () => {
    document.removeEventListener("pointermove", onMove);
    document.removeEventListener("pointerup", onEnd);
    document.removeEventListener("pointercancel", onEnd);
    document.body.classList.remove("is-resizing-composer");
  };
  document.addEventListener("pointermove", onMove);
  document.addEventListener("pointerup", onEnd);
  document.addEventListener("pointercancel", onEnd);
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadState(options = {}) {
  if (!options.force && (connectDragState || reconnectDragState || dragState || discussionDragState || selectionState)) {
    return;
  }
  try {
    const data = await requestJson(apiRoot);
    apiAvailable = true;
    state = normalizeState(data);
  } catch (error) {
    apiAvailable = false;
    const fallback = localStorage.getItem(localKey);
    state = fallback ? normalizeState(JSON.parse(fallback)) : normalizeState({ sessionId });
  }
  pruneNodeSelection();
  render();
  if (!options.skipBootstrap) {
    runAnchorBootstrap();
  }
}

function normalizeState(data) {
  return {
    sessionId: data.sessionId || sessionId,
    nodes: Array.isArray(data.nodes) ? data.nodes : [],
    edges: Array.isArray(data.edges) ? data.edges : [],
    composerOrder: Array.isArray(data.composerOrder) ? data.composerOrder : [],
  };
}

function persistLocal() {
  localStorage.setItem(localKey, JSON.stringify(state));
}

async function saveComposer() {
  persistLocal();
  if (!apiAvailable) return;
  try {
    await requestJson(`${apiRoot}/composer`, {
      method: "POST",
      body: JSON.stringify({ composerOrder: state.composerOrder }),
    });
  } catch (error) {
    apiAvailable = false;
  }
}

async function saveLayout() {
  if (!apiAvailable) {
    persistLocal();
    return;
  }
  const positions = {};
  for (const node of state.nodes) {
    positions[node.id] = { x: node.x, y: node.y };
  }
  try {
    await requestJson(`${apiRoot}/layout`, {
      method: "POST",
      body: JSON.stringify({ positions }),
    });
  } catch (error) {
    apiAvailable = false;
    persistLocal();
    throw error;
  }
}

function render() {
  emptyState.classList.toggle("hidden", state.nodes.length > 0);
  renderCanvasExtent();
  renderEdges();
  renderNodes();
  renderDetail();
  renderPrompt();
  renderControls();
}

function renderCanvasExtent() {
  const visibleNodes = state.nodes.length ? [...state.nodes, discussionNode()] : [];
  const maxX = Math.max(canvas.clientWidth || 0, ...visibleNodes.map((node) => (node.x || 0) + NODE_WIDTH + 50));
  const maxY = Math.max(canvas.clientHeight || 0, ...visibleNodes.map((node) => (node.y || 0) + NODE_HEIGHT + 60));
  const width = Math.ceil(maxX);
  const height = Math.ceil(maxY);
  nodesLayer.style.width = `${width}px`;
  nodesLayer.style.height = `${height}px`;
  edgesLayer.style.width = `${width}px`;
  edgesLayer.style.height = `${height}px`;
  edgeHotLayer.style.width = `${width}px`;
  edgeHotLayer.style.height = `${height}px`;
  edgesLayer.setAttribute("viewBox", `0 0 ${width} ${height}`);
}

function renderNodes() {
  nodesLayer.innerHTML = "";
  for (const node of state.nodes) {
    const el = document.createElement("article");
    el.className = "node";
    el.dataset.id = node.id;
    el.style.left = `${node.x || 0}px`;
    el.style.top = `${node.y || 0}px`;
    el.style.borderLeftColor = TYPE_COLORS[node.type] || TYPE_COLORS.note;
    if (isNodeSelected(node.id)) el.classList.add("selected");
    if (node.id === connectSourceId) el.classList.add("connect-source");
    if (node.id === connectDragState?.hoverTargetId) el.classList.add("connect-target");
    el.innerHTML = `
      <span class="node-port node-port-in" title="接入点"></span>
      <span class="node-port node-port-out" title="拖出连线"></span>
      <span class="node-type">${escapeHtml(TYPE_LABELS[node.type] || "备注")}</span>
      <div class="node-title">${escapeHtml(node.title || "未命名节点")}</div>
      <div class="node-summary">${escapeHtml(node.summary || "")}</div>
      <div class="node-tags">${(node.tags || [])
        .slice(0, 3)
        .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
        .join("")}</div>
    `;
    el.querySelector(".node-port-out").addEventListener("pointerdown", (event) => startConnectDrag(event, node.id));
    el.addEventListener("pointerdown", (event) => startDrag(event, node.id));
    el.addEventListener("pointerenter", () => setConnectHover(node.id));
    el.addEventListener("pointerleave", () => clearConnectHover(node.id));
    el.addEventListener("click", (event) => handleNodeClick(event, node.id));
    nodesLayer.appendChild(el);
  }
  renderDiscussionNode();
}

function renderDiscussionNode() {
  if (!state.nodes.length) return;
  const node = discussionNode();
  const el = document.createElement("article");
  el.className = "node discussion-node";
  el.dataset.id = DISCUSSION_NODE_ID;
  el.style.left = `${node.x}px`;
  el.style.top = `${node.y}px`;
  el.style.borderLeftColor = TYPE_COLORS.discussion;
  el.innerHTML = `
    <span class="node-port node-port-in" title="讨论中状态入口"></span>
    <span class="node-type">讨论中</span>
    <div class="node-title">当前讨论中</div>
    <div class="node-summary">新的 checkpoint 尚未生成，当前对话还在继续沉淀。</div>
    <div class="node-tags"><span class="tag">临时状态</span></div>
  `;
  el.addEventListener("pointerdown", startDiscussionDrag);
  nodesLayer.appendChild(el);
}

function discussionNode() {
  const anchors = discussionAnchorNodes();
  const primary = anchors.at(-1);
  if (!primary) {
    return {
      id: DISCUSSION_NODE_ID,
      type: "discussion",
      x: GRID_LEFT,
      y: GRID_TOP,
    };
  }
  const anchorKey = discussionAnchorKey(anchors);
  if ((discussionPosition?.anchorKey || discussionPosition?.anchorId) === anchorKey) {
    return {
      id: DISCUSSION_NODE_ID,
      type: "discussion",
      x: discussionPosition.x,
      y: discussionPosition.y,
    };
  }
  const latestX = primary.x || GRID_LEFT;
  const latestY = primary.y || GRID_TOP;
  const latestColumn = Math.max(
    0,
    Math.min(GRID_COLUMNS - 1, Math.round((latestX - GRID_LEFT) / GRID_COLUMN_GAP)),
  );
  const wrapsToNextRow = latestColumn >= GRID_COLUMNS - 1;
  const candidate = nextFreeDiscussionSlot({
    x: wrapsToNextRow ? GRID_LEFT : latestX + GRID_COLUMN_GAP,
    y: wrapsToNextRow ? latestY + GRID_ROW_GAP : latestY,
  });
  return {
    id: DISCUSSION_NODE_ID,
    type: "discussion",
    x: candidate.x,
    y: candidate.y,
  };
}

function discussionAnchorNodes() {
  const selectedIds = state.nodes
    .map((node) => node.id)
    .filter((nodeId) => selectedNodeIds.has(nodeId));
  if (selectedIds.length) return selectedIds.map(nodeById).filter(Boolean);
  const terminal = mainlineTerminalNode();
  return terminal ? [terminal] : [];
}

function discussionAnchorKey(anchors = discussionAnchorNodes()) {
  return anchors.map((node) => node.id).join("|");
}

function mainlineTerminalNode() {
  if (!state.nodes.length) return null;
  if (!state.edges.length) return latestCreatedNode();
  const outgoing = new Set(state.edges.map((edge) => edge.from).filter(Boolean));
  const incoming = new Set(state.edges.map((edge) => edge.to).filter(Boolean));
  const terminalNodes = state.nodes.filter((node) => !outgoing.has(node.id) && incoming.has(node.id));
  if (terminalNodes.length) return latestByCreatedAt(terminalNodes);
  return latestCreatedNode();
}

function latestCreatedNode() {
  return latestByCreatedAt(state.nodes);
}

function latestByCreatedAt(nodes) {
  return [...nodes].sort((left, right) => {
    return String(left.createdAt || "").localeCompare(String(right.createdAt || ""));
  }).at(-1) || null;
}

function nextFreeDiscussionSlot(start) {
  let x = start.x;
  let y = start.y;
  for (let guard = 0; guard < state.nodes.length + GRID_COLUMNS + 3; guard += 1) {
    const candidate = { x, y };
    const occupied = state.nodes.some((node) => rectsIntersect(nodeRect(node), nodeRect(candidate)));
    if (!occupied) return candidate;
    const column = Math.max(0, Math.min(GRID_COLUMNS - 1, Math.round((x - GRID_LEFT) / GRID_COLUMN_GAP)));
    if (column >= GRID_COLUMNS - 1) {
      x = GRID_LEFT;
      y += GRID_ROW_GAP;
    } else {
      x += GRID_COLUMN_GAP;
    }
  }
  return { x, y };
}

function renderEdges() {
  edgesLayer.classList.toggle("is-editing-edge", Boolean(selectedEdgeId || hoveredEdgeId || reconnectDragState));
  edgesLayer.innerHTML = "";
  edgeHotLayer.innerHTML = "";
  ensureMarker();
  const endpointControls = [];
  for (const edge of state.edges) {
    const from = nodeById(edge.from);
    const to = nodeById(edge.to);
    if (!from || !to) continue;
    const path = edgePath(from, to);
    const selectEdgeOnPointerDown = (event) => {
      event.preventDefault();
      event.stopPropagation();
      selectEdge(edge.id);
    };
    const hit = document.createElementNS("http://www.w3.org/2000/svg", "path");
    hit.setAttribute("d", path);
    hit.setAttribute("class", "edge-hit");
    hit.setAttribute("data-edge-id", edge.id);
    hit.addEventListener("pointerdown", selectEdgeOnPointerDown);
    hit.addEventListener("click", () => selectEdge(edge.id));
    hit.addEventListener("pointerenter", () => setHoveredEdge(edge.id));
    hit.addEventListener("pointerleave", () => clearHoveredEdge(edge.id));
    const visible = document.createElementNS("http://www.w3.org/2000/svg", "path");
    visible.setAttribute("d", path);
    visible.setAttribute("class", `edge-path${edge.id === selectedEdgeId ? " selected" : ""}${edge.id === hoveredEdgeId ? " hovered" : ""}`);
    visible.setAttribute("data-edge-id", edge.id);
    visible.setAttribute("marker-end", "url(#arrowMarker)");
    visible.addEventListener("pointerdown", selectEdgeOnPointerDown);
    visible.addEventListener("click", () => selectEdge(edge.id));
    visible.addEventListener("pointerenter", () => setHoveredEdge(edge.id));
    visible.addEventListener("pointerleave", () => clearHoveredEdge(edge.id));
    renderEdgeHotspots(edge, visible, selectEdgeOnPointerDown);
    const showEdgeHandles = edge.id === selectedEdgeId || edge.id === hoveredEdgeId;
    const sourceHandle = createEdgeCircleControl({
      edge,
      cx: (from.x || 0) + NODE_WIDTH,
      cy: (from.y || 0) + NODE_HEIGHT / 2,
      className: "edge-endpoint-control edge-source-control",
      label: "拖动修改连线起点",
      title: "拖动修改起点",
      visible: showEdgeHandles,
    });
    sourceHandle.addEventListener("pointerdown", (event) => startReconnectDrag(event, edge.id, "source"));
    const targetHandle = createEdgeCircleControl({
      edge,
      cx: to.x || 0,
      cy: (to.y || 0) + NODE_HEIGHT / 2,
      className: "edge-endpoint-control edge-target-control",
      label: "拖动修改连线终点",
      title: "拖动修改终点",
      visible: showEdgeHandles,
    });
    targetHandle.addEventListener("pointerdown", (event) => startReconnectDrag(event, edge.id, "target"));
    edgesLayer.appendChild(hit);
    edgesLayer.appendChild(visible);
    endpointControls.push(sourceHandle, targetHandle);
  }
  renderDiscussionEdge();
  renderConnectPreview();
  renderReconnectPreview();
  for (const control of endpointControls) {
    edgesLayer.appendChild(control);
  }
}

function renderEdgeHotspots(edge, pathElement, onPointerDown) {
  if (typeof pathElement.getTotalLength !== "function" || typeof pathElement.getPointAtLength !== "function") {
    return;
  }
  let totalLength = 0;
  try {
    totalLength = pathElement.getTotalLength();
  } catch {
    return;
  }
  const ratios = totalLength < 140 ? [0.5] : [0.2, 0.35, 0.5, 0.65, 0.8];
  for (const ratio of ratios) {
    const point = pathElement.getPointAtLength(totalLength * ratio);
    const hotspot = document.createElement("button");
    hotspot.type = "button";
    hotspot.className = "edge-hotspot";
    hotspot.tabIndex = -1;
    hotspot.setAttribute("aria-label", "选择连线");
    hotspot.dataset.edgeId = edge.id;
    hotspot.style.left = `${point.x - 12}px`;
    hotspot.style.top = `${point.y - 12}px`;
    hotspot.addEventListener("pointerdown", onPointerDown);
    hotspot.addEventListener("click", () => selectEdge(edge.id));
    edgeHotLayer.appendChild(hotspot);
  }
}

function createEdgeCircleControl({ edge, cx, cy, className, label, title, visible }) {
  const control = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  control.setAttribute("cx", cx);
  control.setAttribute("cy", cy);
  control.setAttribute("r", "6");
  control.setAttribute("class", `${className}${edge.id === selectedEdgeId ? " selected" : ""}${edge.id === hoveredEdgeId ? " hovered" : ""}${visible ? " visible" : ""}`);
  control.setAttribute("data-edge-id", edge.id);
  control.setAttribute("aria-label", label);
  const controlTitle = document.createElementNS("http://www.w3.org/2000/svg", "title");
  controlTitle.textContent = title;
  control.appendChild(controlTitle);
  control.addEventListener("pointerenter", () => setHoveredEdge(edge.id));
  control.addEventListener("pointerleave", () => clearHoveredEdge(edge.id));
  return control;
}

function ensureMarker() {
  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  defs.appendChild(createMarker("arrowMarker", "#aab3c5"));
  defs.appendChild(createMarker("discussionArrowMarker", "#ff6d5a"));
  edgesLayer.appendChild(defs);
}

function createMarker(id, fill) {
  const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  marker.setAttribute("id", id);
  marker.setAttribute("markerWidth", "10");
  marker.setAttribute("markerHeight", "10");
  marker.setAttribute("refX", "8");
  marker.setAttribute("refY", "3");
  marker.setAttribute("orient", "auto");
  marker.setAttribute("markerUnits", "strokeWidth");
  const arrow = document.createElementNS("http://www.w3.org/2000/svg", "path");
  arrow.setAttribute("d", "M0,0 L0,6 L9,3 z");
  arrow.setAttribute("fill", fill);
  marker.appendChild(arrow);
  return marker;
}

function renderDiscussionEdge() {
  const anchors = discussionAnchorNodes();
  if (!anchors.length) return;
  const target = discussionNode();
  for (const anchor of anchors) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", edgePath(anchor, target));
    path.setAttribute("class", "edge-path discussion-edge");
    path.setAttribute("data-end-x", String(target.x || 0));
    path.setAttribute("data-end-y", String((target.y || 0) + NODE_HEIGHT / 2));
    path.setAttribute("marker-end", "url(#discussionArrowMarker)");
    edgesLayer.appendChild(path);
  }
}

function renderConnectPreview() {
  if (!connectDragState) return;
  const from = nodeById(connectDragState.from);
  if (!from) return;
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", pointerEdgePath(from, connectDragState.pointer));
  path.setAttribute("class", "edge-path connect-preview-edge");
  path.setAttribute("marker-end", "url(#discussionArrowMarker)");
  edgesLayer.appendChild(path);
}

function renderReconnectPreview() {
  if (!reconnectDragState) return;
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", reconnectPreviewPath(reconnectDragState));
  path.setAttribute("class", "edge-path connect-preview-edge");
  path.setAttribute("marker-end", "url(#discussionArrowMarker)");
  edgesLayer.appendChild(path);
}

function edgePath(from, to) {
  const startX = (from.x || 0) + NODE_WIDTH;
  const startY = (from.y || 0) + NODE_HEIGHT / 2;
  const endX = to.x || 0;
  const endY = (to.y || 0) + NODE_HEIGHT / 2;
  const delta = Math.max(40, Math.abs(endX - startX) / 2);
  return `M ${startX} ${startY} C ${startX + delta} ${startY}, ${endX - delta} ${endY}, ${endX} ${endY}`;
}

function reconnectPreviewPath(reconnect) {
  const edge = edgeById(reconnect.edgeId);
  if (!edge) return "";
  if (reconnect.endpoint === "target") {
    const from = nodeById(edge.from);
    if (!from) return "";
    return pointerEdgePath(from, reconnect.pointer);
  }
  const to = nodeById(edge.to);
  if (!to) return "";
  const startX = reconnect.pointer.x;
  const startY = reconnect.pointer.y;
  const endX = to.x || 0;
  const endY = (to.y || 0) + NODE_HEIGHT / 2;
  const delta = Math.max(40, Math.abs(endX - startX) / 2);
  return `M ${startX} ${startY} C ${startX + delta} ${startY}, ${endX - delta} ${endY}, ${endX} ${endY}`;
}

function startReconnectDrag(event, edgeId, endpoint) {
  if (event.button !== 0 || dragState || connectDragState) return;
  const edge = edgeById(edgeId);
  if (!edge) return;
  event.stopPropagation();
  event.preventDefault();
  selectedEdgeId = edgeId;
  hoveredEdgeId = edgeId;
  reconnectDragState = {
    edgeId,
    endpoint,
    from: edge.from,
    to: edge.to,
    pointer: eventToCanvasPoint(event),
    hoverTargetId: null,
    layoutSnapshot: snapshotNodePositions(),
  };
  event.currentTarget.setPointerCapture(event.pointerId);
  document.addEventListener("pointermove", onReconnectDragMove);
  document.addEventListener("pointerup", onReconnectDragEnd, { once: true });
  document.addEventListener("pointercancel", cancelReconnectDrag, { once: true });
  renderEdges();
  renderControls();
}

function onReconnectDragMove(event) {
  if (!reconnectDragState) return;
  reconnectDragState.pointer = eventToCanvasPoint(event);
  reconnectDragState.hoverTargetId = reconnectTargetNodeIdFromPoint(
    event.clientX,
    event.clientY,
    reconnectDragState,
  );
  updateConnectNodeClasses();
  renderEdges();
  renderControls();
}

async function onReconnectDragEnd(event) {
  document.removeEventListener("pointermove", onReconnectDragMove);
  document.removeEventListener("pointercancel", cancelReconnectDrag);
  const current = reconnectDragState;
  const targetId = reconnectTargetNodeIdFromPoint(event.clientX, event.clientY, current);
  reconnectDragState = null;
  suppressNodeClickUntil = Date.now() + 250;
  if (current?.layoutSnapshot) restoreNodePositions(current.layoutSnapshot);
  if (current && targetId) {
    await reconnectEdge(current.edgeId, current.endpoint, targetId);
  } else {
    render();
  }
}

function cancelReconnectDrag() {
  document.removeEventListener("pointermove", onReconnectDragMove);
  if (reconnectDragState?.layoutSnapshot) restoreNodePositions(reconnectDragState.layoutSnapshot);
  reconnectDragState = null;
  render();
}

function reconnectTargetNodeIdFromPoint(clientX, clientY, reconnect) {
  if (!reconnect) return null;
  return reconnect.endpoint === "target"
    ? targetPortNodeIdFromPoint(clientX, clientY, reconnect.from)
    : sourcePortNodeIdFromPoint(clientX, clientY, reconnect.to);
}

function sourcePortNodeIdFromPoint(clientX, clientY, targetId) {
  const elements = document.elementsFromPoint(clientX, clientY);
  const outputPort = elements.find((item) => item.classList?.contains("node-port-out"));
  const portNode = outputPort?.closest?.(".node");
  const nodeId = portNode?.dataset.id || nodeIdFromPoint(elements);
  if (!nodeId || nodeId === targetId || nodeId === DISCUSSION_NODE_ID) return null;
  return nodeId;
}

function pointerEdgePath(from, pointer) {
  const startX = (from.x || 0) + NODE_WIDTH;
  const startY = (from.y || 0) + NODE_HEIGHT / 2;
  const endX = pointer.x;
  const endY = pointer.y;
  const delta = Math.max(40, Math.abs(endX - startX) / 2);
  return `M ${startX} ${startY} C ${startX + delta} ${startY}, ${endX - delta} ${endY}, ${endX} ${endY}`;
}

function renderDetail() {
  const node = selectedNodeId ? nodeById(selectedNodeId) : null;
  detailEmpty.classList.toggle("hidden", Boolean(node));
  detailContent.classList.toggle("hidden", !node);
  if (!node) return;
  document.getElementById("detailType").textContent = TYPE_LABELS[node.type] || "备注";
  document.getElementById("detailType").style.background = TYPE_COLORS[node.type] || TYPE_COLORS.note;
  document.getElementById("detailTitle").textContent = node.title || "未命名节点";
  document.getElementById("detailSummary").textContent = node.summary || "";
  document.getElementById("detailMarkdown").innerHTML = markdownToHtml(
    node.detailMarkdown || node.summary || "这个节点还没有结构化详情。",
  );
  const rawEvidenceWrap = document.getElementById("rawEvidenceWrap");
  const hasRawText = Boolean((node.rawText || "").trim());
  rawEvidenceWrap.classList.toggle("hidden", !hasRawText);
  document.getElementById("detailRaw").textContent = hasRawText ? node.rawText : "";
  document.getElementById("detailTags").innerHTML = (node.tags || []).length
    ? node.tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")
    : `<span class="tag">无标签</span>`;
  document.getElementById("detailFiles").innerHTML = (node.relatedFiles || []).length
    ? node.relatedFiles.map((file) => `<span class="file-chip">${escapeHtml(file)}</span>`).join("")
    : `<span class="tag">无相关文件</span>`;
  document.getElementById("detailEvidence").innerHTML = (node.evidenceRefs || []).length
    ? node.evidenceRefs.map((ref) => `<span class="file-chip">${escapeHtml(ref)}</span>`).join("")
    : `<span class="tag">无证据来源</span>`;
}

function renderControls() {
  undoEdgeBtn.disabled = undoStack.length === 0;
  const activeConnection = connectDragState || reconnectDragState;
  nodesLayer.classList.toggle("is-connecting", Boolean(activeConnection));
  connectHint.classList.toggle("hidden", !activeConnection);
  if (activeConnection) {
    const source = nodeById(activeConnection.from);
    const target = nodeById(activeConnection.hoverTargetId);
    connectHint.textContent = target
      ? `${source?.title || "起点"} → ${target.title || "终点"}`
      : `拖到目标节点：${source?.title || "已选起点"}`;
  } else {
    connectHint.textContent = "";
  }
}

function renderPrompt() {
  if (promptDirty) return;
  const nodes = orderedComposerNodes();
  if (!nodes.length) {
    promptBox.value = "";
    return;
  }
  const chunks = nodes.map((node, index) => {
    const files = (node.relatedFiles || []).length ? `\n相关文件：${node.relatedFiles.join(", ")}` : "";
    const evidence = (node.evidenceRefs || []).length ? `\n证据来源：${node.evidenceRefs.join(", ")}` : "";
    const context = node.contextText || node.detailMarkdown || node.summary || node.rawText || "";
    return `【${index + 1}. ${node.title}】\n类型：${TYPE_LABELS[node.type] || node.type}\n摘要：${node.summary}${files}${evidence}\n上下文：\n${context}`;
  });
  promptBox.value = `请基于以下 Codex Canvas 检查点继续处理。本内容来自我选择的节点压缩上下文，不代表修改你的记忆或系统上下文。\n\n${chunks.join("\n\n---\n\n")}`;
}

function regeneratePrompt() {
  promptDirty = false;
  renderPrompt();
}

function orderedComposerNodes() {
  return state.composerOrder.map(nodeById).filter(Boolean);
}

function isNodeSelected(nodeId) {
  return selectedNodeIds.has(nodeId) || selectedNodeId === nodeId;
}

function selectOnlyNode(nodeId) {
  selectedNodeIds = new Set([nodeId]);
  selectedNodeId = nodeId;
  selectedEdgeId = null;
}

function toggleNodeSelection(nodeId) {
  selectedEdgeId = null;
  if (selectedNodeIds.has(nodeId)) {
    selectedNodeIds.delete(nodeId);
    selectedNodeId = [...selectedNodeIds].at(-1) || null;
  } else {
    selectedNodeIds.add(nodeId);
    selectedNodeId = nodeId;
  }
}

function clearNodeSelection() {
  selectedNodeIds = new Set();
  selectedNodeId = null;
}

function pruneNodeSelection() {
  const nodeIds = new Set(state.nodes.map((node) => node.id));
  selectedNodeIds = new Set([...selectedNodeIds].filter((nodeId) => nodeIds.has(nodeId)));
  if (selectedNodeId && !nodeIds.has(selectedNodeId)) {
    selectedNodeId = [...selectedNodeIds].at(-1) || null;
  }
}

function updateNodeSelectionClasses() {
  nodesLayer.querySelectorAll(".node").forEach((nodeEl) => {
    const nodeId = nodeEl.dataset.id;
    nodeEl.classList.toggle("selected", Boolean(nodeId && isNodeSelected(nodeId)));
  });
}

async function handleNodeClick(event, nodeId) {
  event.stopPropagation();
  if (Date.now() < suppressNodeClickUntil) return;
  if (dragState?.dragged) return;
  if (event.shiftKey) {
    toggleNodeSelection(nodeId);
  } else {
    selectOnlyNode(nodeId);
  }
  render();
}

function selectEdge(edgeId) {
  selectedEdgeId = edgeId;
  suppressCanvasClickUntil = Date.now() + 120;
  clearNodeSelection();
  render();
}

function setHoveredEdge(edgeId) {
  if (hoveredEdgeId === edgeId) return;
  hoveredEdgeId = edgeId;
  renderEdges();
}

function clearHoveredEdge(edgeId) {
  if (hoveredEdgeId !== edgeId) return;
  hoveredEdgeId = null;
  renderEdges();
}

function startDrag(event, nodeId) {
  if (connectDragState || reconnectDragState || event.target.closest?.(".node-port")) return;
  if (event.shiftKey) return;
  const node = nodeById(nodeId);
  if (!node) return;
  if (!event.shiftKey && !selectedNodeIds.has(nodeId)) {
    selectOnlyNode(nodeId);
    updateNodeSelectionClasses();
    renderDetail();
  }
  const dragNodeIds = selectedNodeIds.has(nodeId) ? [...selectedNodeIds] : [nodeId];
  dragState = {
    nodeId,
    nodeIds: dragNodeIds,
    positions: dragNodeIds
      .map((id) => nodeById(id))
      .filter(Boolean)
      .map((item) => ({ id: item.id, x: item.x || 0, y: item.y || 0 })),
    startX: event.clientX,
    startY: event.clientY,
    dragged: false,
  };
  event.currentTarget.setPointerCapture(event.pointerId);
  document.addEventListener("pointermove", onDragMove);
  document.addEventListener("pointerup", onDragEnd, { once: true });
  document.addEventListener("pointercancel", cancelNodeDrag, { once: true });
}

function startConnectDrag(event, nodeId) {
  if (event.button !== 0 || dragState) return;
  const node = nodeById(nodeId);
  if (!node) return;
  event.stopPropagation();
  event.preventDefault();
  connectSourceId = nodeId;
  selectedNodeId = nodeId;
  selectedEdgeId = null;
  connectDragState = {
    from: nodeId,
    pointer: eventToCanvasPoint(event),
    hoverTargetId: null,
    layoutSnapshot: snapshotNodePositions(),
    startedAt: Date.now(),
  };
  event.currentTarget.setPointerCapture(event.pointerId);
  document.addEventListener("pointermove", onConnectDragMove);
  document.addEventListener("pointerup", onConnectDragEnd, { once: true });
  document.addEventListener("pointercancel", cancelConnectDrag, { once: true });
  nodesLayer.querySelector(`[data-id="${CSS.escape(nodeId)}"]`)?.classList.add("connect-source");
  renderEdges();
  renderControls();
}

function onConnectDragMove(event) {
  if (!connectDragState) return;
  connectDragState.pointer = eventToCanvasPoint(event);
  connectDragState.hoverTargetId = targetNodeIdFromPoint(event.clientX, event.clientY, connectDragState.from);
  updateConnectNodeClasses();
  renderEdges();
  renderControls();
}

async function onConnectDragEnd(event) {
  document.removeEventListener("pointermove", onConnectDragMove);
  document.removeEventListener("pointercancel", cancelConnectDrag);
  const current = connectDragState;
  const targetId = targetPortNodeIdFromPoint(event.clientX, event.clientY, current?.from);
  connectDragState = null;
  connectSourceId = null;
  suppressNodeClickUntil = Date.now() + 250;
  if (current?.layoutSnapshot) restoreNodePositions(current.layoutSnapshot);
  if (current?.from && targetId) {
    await createEdge(current.from, targetId);
    render();
  } else {
    render();
  }
}

function cancelConnectDrag() {
  document.removeEventListener("pointermove", onConnectDragMove);
  if (connectDragState?.layoutSnapshot) restoreNodePositions(connectDragState.layoutSnapshot);
  connectDragState = null;
  connectSourceId = null;
  render();
}

function updateConnectNodeClasses() {
  nodesLayer.querySelectorAll(".node.connect-target").forEach((node) => node.classList.remove("connect-target"));
  const hoverTargetId = connectDragState?.hoverTargetId || reconnectDragState?.hoverTargetId;
  if (!hoverTargetId) return;
  nodesLayer
    .querySelector(`[data-id="${CSS.escape(hoverTargetId)}"]`)
    ?.classList.add("connect-target");
}

function setConnectHover(nodeId) {
  if (!connectDragState || connectDragState.from === nodeId) return;
  connectDragState.hoverTargetId = null;
  renderControls();
}

function clearConnectHover(nodeId) {
  if (!connectDragState || connectDragState.hoverTargetId !== nodeId) return;
  connectDragState.hoverTargetId = null;
  renderControls();
}

function targetNodeIdFromPoint(clientX, clientY, sourceId) {
  return targetPortNodeIdFromPoint(clientX, clientY, sourceId);
}

function targetPortNodeIdFromPoint(clientX, clientY, sourceId) {
  const elements = document.elementsFromPoint(clientX, clientY);
  const inputPort = elements.find((item) => item.classList?.contains("node-port-in"));
  const portNode = inputPort?.closest?.(".node");
  const nodeId = portNode?.dataset.id || nodeIdFromPoint(elements);
  if (!nodeId || nodeId === sourceId || nodeId === DISCUSSION_NODE_ID) return null;
  return nodeId;
}

function nodeIdFromPoint(elements) {
  const node = elements.find((item) => item.classList?.contains("node"));
  return node?.dataset.id || null;
}

function eventToCanvasPoint(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: event.clientX - rect.left + canvas.scrollLeft,
    y: event.clientY - rect.top + canvas.scrollTop,
  };
}

function snapshotNodePositions() {
  return state.nodes.map((node) => ({ id: node.id, x: node.x || 0, y: node.y || 0 }));
}

function snapshotCanvasState() {
  return {
    positions: Object.fromEntries(state.nodes.map((node) => [node.id, { x: node.x || 0, y: node.y || 0 }])),
    edges: state.edges.map((edge) => ({ ...edge })),
    discussionPosition: discussionPosition ? { ...discussionPosition } : null,
  };
}

function restoreNodePositions(snapshot) {
  const positions = new Map(snapshot.map((item) => [item.id, item]));
  for (const node of state.nodes) {
    const position = positions.get(node.id);
    if (!position) continue;
    node.x = position.x;
    node.y = position.y;
    const el = nodesLayer.querySelector(`[data-id="${CSS.escape(node.id)}"]`);
    if (el) {
      el.style.left = `${node.x}px`;
      el.style.top = `${node.y}px`;
    }
  }
  renderEdges();
}

function startDiscussionDrag(event) {
  if (event.button !== 0 || dragState || connectDragState || reconnectDragState || selectionState) return;
  const anchors = discussionAnchorNodes();
  if (!anchors.length) return;
  event.stopPropagation();
  event.preventDefault();
  const node = discussionNode();
  discussionDragState = {
    anchorKey: discussionAnchorKey(anchors),
    startX: event.clientX,
    startY: event.clientY,
    nodeX: node.x || 0,
    nodeY: node.y || 0,
    dragged: false,
  };
  event.currentTarget.setPointerCapture(event.pointerId);
  document.addEventListener("pointermove", onDiscussionDragMove);
  document.addEventListener("pointerup", onDiscussionDragEnd, { once: true });
  document.addEventListener("pointercancel", cancelDiscussionDrag, { once: true });
}

function onDiscussionDragMove(event) {
  if (!discussionDragState) return;
  const dx = event.clientX - discussionDragState.startX;
  const dy = event.clientY - discussionDragState.startY;
  if (Math.abs(dx) + Math.abs(dy) > 3) discussionDragState.dragged = true;
  discussionPosition = {
    anchorKey: discussionDragState.anchorKey,
    x: Math.max(10, discussionDragState.nodeX + dx),
    y: Math.max(10, discussionDragState.nodeY + dy),
  };
  renderCanvasExtent();
  renderEdges();
  updateDiscussionNodeElement();
}

function onDiscussionDragEnd() {
  document.removeEventListener("pointermove", onDiscussionDragMove);
  document.removeEventListener("pointercancel", cancelDiscussionDrag);
  saveDiscussionPosition();
  suppressCanvasClickUntil = Date.now() + 250;
  discussionDragState = null;
  render();
}

function cancelDiscussionDrag() {
  document.removeEventListener("pointermove", onDiscussionDragMove);
  discussionDragState = null;
  discussionPosition = loadDiscussionPosition();
  render();
}

function updateDiscussionNodeElement() {
  const el = nodesLayer.querySelector(`[data-id="${DISCUSSION_NODE_ID}"]`);
  if (!el) return;
  const node = discussionNode();
  el.style.left = `${node.x || 0}px`;
  el.style.top = `${node.y || 0}px`;
}

function startMarqueeSelection(event) {
  if (event.button !== 0 || dragState || connectDragState || reconnectDragState || selectionState) return;
  if (isEditableTarget(event.target)) return;
  const directEdgeId = event.target.closest?.(".edge-path, .edge-hit, .edge-hotspot")?.dataset.edgeId;
  if (directEdgeId) {
    event.preventDefault();
    selectEdge(directEdgeId);
    return;
  }
  if (event.target.closest?.(".node, .edge-endpoint-control")) return;
  const start = eventToCanvasPoint(event);
  const edgeId = edgeIdAtCanvasPoint(start);
  if (edgeId) {
    event.preventDefault();
    selectEdge(edgeId);
    return;
  }
  event.preventDefault();
  selectionState = {
    start,
    current: start,
    initialSelection: new Set(selectedNodeIds),
    additive: event.shiftKey,
    dragged: false,
  };
  selectedEdgeId = null;
  document.addEventListener("pointermove", onMarqueeSelectionMove);
  document.addEventListener("pointerup", onMarqueeSelectionEnd, { once: true });
  document.addEventListener("pointercancel", cancelMarqueeSelection, { once: true });
  renderSelectionBox();
}

function edgeIdAtCanvasPoint(point) {
  const hitPaths = [...edgesLayer.querySelectorAll(".edge-hit")].reverse();
  let svgPoint = null;
  if (typeof edgesLayer.createSVGPoint === "function") {
    svgPoint = edgesLayer.createSVGPoint();
    svgPoint.x = point.x;
    svgPoint.y = point.y;
  }
  let closestEdgeId = null;
  let closestDistance = Infinity;
  for (const hitPath of hitPaths) {
    const edgeId = hitPath.dataset.edgeId;
    if (!edgeId) continue;
    if (svgPoint && typeof hitPath.isPointInStroke === "function") {
      try {
        if (hitPath.isPointInStroke(svgPoint)) return edgeId;
      } catch {
        // Fall back to sampled distance below.
      }
    }
    if (typeof hitPath.getTotalLength !== "function" || typeof hitPath.getPointAtLength !== "function") continue;
    const totalLength = hitPath.getTotalLength();
    for (let index = 0; index <= 18; index += 1) {
      const pathPoint = hitPath.getPointAtLength((totalLength * index) / 18);
      const distance = Math.hypot(pathPoint.x - point.x, pathPoint.y - point.y);
      if (distance < closestDistance) {
        closestDistance = distance;
        closestEdgeId = edgeId;
      }
    }
  }
  return closestDistance <= 10 ? closestEdgeId : null;
}

function onMarqueeSelectionMove(event) {
  if (!selectionState) return;
  selectionState.current = eventToCanvasPoint(event);
  const dx = selectionState.current.x - selectionState.start.x;
  const dy = selectionState.current.y - selectionState.start.y;
  if (Math.abs(dx) + Math.abs(dy) > 4) selectionState.dragged = true;
  renderSelectionBox();
  updateMarqueeSelection();
}

function onMarqueeSelectionEnd() {
  document.removeEventListener("pointermove", onMarqueeSelectionMove);
  document.removeEventListener("pointercancel", cancelMarqueeSelection);
  const wasDragged = Boolean(selectionState?.dragged);
  hideSelectionBox();
  selectionState = null;
  if (wasDragged) {
    suppressCanvasClickUntil = Date.now() + 250;
    render();
  }
}

function cancelMarqueeSelection() {
  document.removeEventListener("pointermove", onMarqueeSelectionMove);
  hideSelectionBox();
  selectionState = null;
  render();
}

function renderSelectionBox() {
  if (!selectionState) return;
  const rect = normalizedRect(selectionState.start, selectionState.current);
  selectionBox.classList.remove("hidden");
  selectionBox.style.left = `${rect.left}px`;
  selectionBox.style.top = `${rect.top}px`;
  selectionBox.style.width = `${rect.width}px`;
  selectionBox.style.height = `${rect.height}px`;
}

function hideSelectionBox() {
  selectionBox.classList.add("hidden");
  selectionBox.style.width = "0px";
  selectionBox.style.height = "0px";
}

function updateMarqueeSelection() {
  if (!selectionState) return;
  const rect = normalizedRect(selectionState.start, selectionState.current);
  const selected = selectionState.additive ? new Set(selectionState.initialSelection) : new Set();
  for (const node of state.nodes) {
    if (rectsIntersect(rect, nodeRect(node))) selected.add(node.id);
  }
  selectedNodeIds = selected;
  selectedNodeId = [...selectedNodeIds].at(-1) || null;
  updateNodeSelectionClasses();
  renderDetail();
  renderControls();
}

function normalizedRect(start, current) {
  const left = Math.min(start.x, current.x);
  const top = Math.min(start.y, current.y);
  const right = Math.max(start.x, current.x);
  const bottom = Math.max(start.y, current.y);
  return {
    left,
    top,
    right,
    bottom,
    width: right - left,
    height: bottom - top,
  };
}

function nodeRect(node) {
  return {
    left: node.x || 0,
    top: node.y || 0,
    right: (node.x || 0) + NODE_WIDTH,
    bottom: (node.y || 0) + NODE_HEIGHT,
  };
}

function rectsIntersect(a, b) {
  return a.left <= b.right && a.right >= b.left && a.top <= b.bottom && a.bottom >= b.top;
}

function onDragMove(event) {
  if (!dragState) return;
  const dx = event.clientX - dragState.startX;
  const dy = event.clientY - dragState.startY;
  if (Math.abs(dx) + Math.abs(dy) > 3) dragState.dragged = true;
  for (const position of dragState.positions) {
    const node = nodeById(position.id);
    if (!node) continue;
    node.x = Math.max(10, position.x + dx);
    node.y = Math.max(10, position.y + dy);
    const el = nodesLayer.querySelector(`[data-id="${CSS.escape(node.id)}"]`);
    if (el) {
      el.style.left = `${node.x}px`;
      el.style.top = `${node.y}px`;
    }
  }
  renderCanvasExtent();
  renderEdges();
  updateDiscussionNodeElement();
}

async function onDragEnd(event) {
  document.removeEventListener("pointermove", onDragMove);
  document.removeEventListener("pointercancel", cancelNodeDrag);
  try {
    await saveLayout();
  } catch (error) {
    toast("布局保存失败，已先保留在本地。");
  } finally {
    setTimeout(() => {
      dragState = null;
    }, 0);
  }
}

function cancelNodeDrag() {
  document.removeEventListener("pointermove", onDragMove);
  dragState = null;
  loadState({ force: true });
}

async function createEdge(from, to) {
  const existing = state.edges.some((edge) => edge.from === from && edge.to === to);
  if (existing) {
    toast("这条连线已经存在。");
    return;
  }
  const edge = {
    id: `edge_${Date.now().toString(36)}`,
    from,
    to,
    label: "",
    createdAt: new Date().toISOString(),
  };
  if (apiAvailable) {
    try {
      const createdEdge = await requestJson(`${apiRoot}/edges`, { method: "POST", body: JSON.stringify(edge) });
      rememberUndoAction({ type: "delete-edge", edge: createdEdge });
      await loadState();
      toast("已建立连线。");
    } catch (error) {
      toast(`连线失败：${error.message}`);
    }
  } else {
    state.edges.push(edge);
    state.composerOrder = unique([...state.composerOrder, from, to]);
    rememberUndoAction({ type: "delete-edge", edge: { ...edge } });
    persistLocal();
    render();
    toast("已建立连线。");
  }
}

async function reconnectEdge(edgeId, endpoint, targetNodeId) {
  const edge = edgeById(edgeId);
  if (!edge) return;
  const previous = { ...edge };
  const next = {
    ...edge,
    id: `edge_${Date.now().toString(36)}`,
    from: endpoint === "source" ? targetNodeId : edge.from,
    to: endpoint === "target" ? targetNodeId : edge.to,
    createdAt: new Date().toISOString(),
  };
  if (!next.from || !next.to || next.from === next.to) {
    toast("不能把连线接到同一个节点。");
    render();
    return;
  }
  const exists = state.edges.some((item) => item.id !== edgeId && item.from === next.from && item.to === next.to);
  if (exists) {
    toast("这条连线已经存在。");
    render();
    return;
  }

  if (apiAvailable) {
    try {
      await requestJson(`${apiRoot}/edges/${encodeURIComponent(edgeId)}`, {
        method: "PATCH",
        body: JSON.stringify({
          from: next.from,
          to: next.to,
          label: next.label || "",
        }),
      });
      rememberUndoAction({ type: "reconnect-edge", edgeId, before: previous, after: next });
      selectedEdgeId = edgeId;
      await loadState({ force: true });
      toast("连线已更新。");
    } catch (error) {
      await loadState({ force: true });
      toast(`重连失败：${error.message}`);
    }
    return;
  }

  edge.from = next.from;
  edge.to = next.to;
  rememberUndoAction({ type: "reconnect-edge", edgeId, before: previous, after: { ...edge } });
  selectedEdgeId = edgeId;
  persistLocal();
  render();
  toast("连线已更新。");
}

async function deleteSelectedEdge() {
  if (!selectedEdgeId) return;
  const edgeToDelete = edgeById(selectedEdgeId);
  if (!edgeToDelete) return;
  if (apiAvailable) {
    await requestJson(`${apiRoot}/edges/${encodeURIComponent(selectedEdgeId)}`, { method: "DELETE" });
    rememberUndoAction({ type: "restore-edge", edge: { ...edgeToDelete } });
    selectedEdgeId = null;
    await loadState();
  } else {
    state.edges = state.edges.filter((edge) => edge.id !== selectedEdgeId);
    rememberUndoAction({ type: "restore-edge", edge: { ...edgeToDelete } });
    selectedEdgeId = null;
    persistLocal();
    render();
  }
  toast("连线已删除，可用 Ctrl+Z 撤销。");
}

function rememberUndoAction(action) {
  undoStack.push(action);
  if (undoStack.length > 40) undoStack.shift();
  renderControls();
}

async function undoLastCanvasAction() {
  const action = undoStack.pop();
  if (!action) return;
  try {
    if (action.type === "restore-edge") {
      await restoreEdge(action.edge);
      selectedEdgeId = action.edge.id;
      toast("已撤销删线。");
    } else if (action.type === "delete-edge") {
      await removeEdge(action.edge.id);
      selectedEdgeId = null;
      toast("已撤销新连线。");
    } else if (action.type === "reconnect-edge") {
      await patchEdge(action.edgeId, action.before);
      selectedEdgeId = action.edgeId;
      toast("已撤销连线修改。");
    } else if (action.type === "restore-canvas") {
      await restoreCanvasSnapshot(action.before);
      selectedEdgeId = null;
      toast("已撤销还原画布。");
    }
  } catch (error) {
    undoStack.push(action);
    toast(`撤销失败：${error.message}`);
    renderControls();
    return;
  }
  renderControls();
}

async function restoreEdge(edge) {
  if (!nodeById(edge.from) || !nodeById(edge.to)) {
    throw new Error("连线两端节点不存在");
  }
  const existing = state.edges.some((item) => item.from === edge.from && item.to === edge.to);
  if (existing) {
    throw new Error("这条连线已经存在");
  }
  const restoredEdge = { ...edge, id: edge.id || `edge_${Date.now().toString(36)}` };
  if (apiAvailable) {
    await requestJson(`${apiRoot}/edges`, {
      method: "POST",
      body: JSON.stringify(restoredEdge),
    });
    await loadState({ force: true });
    return;
  }
  state.edges.push(restoredEdge);
  state.composerOrder = unique([...state.composerOrder, restoredEdge.from, restoredEdge.to]);
  persistLocal();
  render();
}

async function removeEdge(edgeId) {
  if (apiAvailable) {
    await requestJson(`${apiRoot}/edges/${encodeURIComponent(edgeId)}`, { method: "DELETE" });
    await loadState({ force: true });
    return;
  }
  state.edges = state.edges.filter((edge) => edge.id !== edgeId);
  persistLocal();
  render();
}

async function patchEdge(edgeId, edge) {
  if (!nodeById(edge.from) || !nodeById(edge.to)) {
    throw new Error("连线两端节点不存在");
  }
  if (apiAvailable) {
    await requestJson(`${apiRoot}/edges/${encodeURIComponent(edgeId)}`, {
      method: "PATCH",
      body: JSON.stringify({ from: edge.from, to: edge.to, label: edge.label || "" }),
    });
    await loadState({ force: true });
    return;
  }
  const target = edgeById(edgeId);
  if (!target) throw new Error("找不到这条连线");
  target.from = edge.from;
  target.to = edge.to;
  target.label = edge.label || "";
  persistLocal();
  render();
}

async function restoreCanvasSnapshot(snapshot) {
  if (!snapshot) return;
  selectedEdgeId = null;
  clearNodeSelection();
  discussionPosition = snapshot.discussionPosition ? { ...snapshot.discussionPosition } : null;
  saveDiscussionPosition();
  if (apiAvailable) {
    const data = await requestJson(`${apiRoot}/restore-canvas`, {
      method: "POST",
      body: JSON.stringify({
        positions: snapshot.positions || {},
        edges: snapshot.edges || [],
      }),
    });
    state = normalizeState(data);
    render();
    return;
  }
  const positions = snapshot.positions || {};
  for (const node of state.nodes) {
    const position = positions[node.id];
    if (!position) continue;
    node.x = Number.isFinite(position.x) ? position.x : node.x;
    node.y = Number.isFinite(position.y) ? position.y : node.y;
  }
  const nodeIds = new Set(state.nodes.map((node) => node.id));
  const seenPairs = new Set();
  state.edges = (snapshot.edges || [])
    .filter((edge) => {
      if (!edge?.from || !edge?.to || edge.from === edge.to) return false;
      if (!nodeIds.has(edge.from) || !nodeIds.has(edge.to)) return false;
      const pair = `${edge.from}->${edge.to}`;
      if (seenPairs.has(pair)) return false;
      seenPairs.add(pair);
      return true;
    })
    .map((edge) => ({ ...edge }));
  persistLocal();
  render();
}

async function addSelectedToComposer() {
  const selectedIds = selectedNodeIds.size
    ? state.nodes.map((node) => node.id).filter((nodeId) => selectedNodeIds.has(nodeId))
    : [selectedNodeId].filter(Boolean);
  if (!selectedIds.length) return;
  state.composerOrder = unique([...state.composerOrder, ...selectedIds]);
  regeneratePrompt();
  await saveComposer();
}

async function useMainlineOrder() {
  state.composerOrder = mainlineComposerOrder();
  regeneratePrompt();
  await saveComposer();
}

function mainlineComposerOrder() {
  if (!state.nodes.length) return [];
  if (!state.edges.length) return state.nodes.map((node) => node.id);

  const nodesById = new Map(state.nodes.map((node) => [node.id, node]));
  const incoming = new Map();
  const outgoing = new Map();
  for (const edge of state.edges) {
    if (!nodesById.has(edge.from) || !nodesById.has(edge.to)) continue;
    if (!incoming.has(edge.to)) incoming.set(edge.to, []);
    if (!outgoing.has(edge.from)) outgoing.set(edge.from, []);
    incoming.get(edge.to).push(edge.from);
    outgoing.get(edge.from).push(edge.to);
  }

  const byTime = (leftId, rightId) => {
    const left = nodesById.get(leftId);
    const right = nodesById.get(rightId);
    return String(left?.createdAt || "").localeCompare(String(right?.createdAt || ""));
  };
  for (const targets of outgoing.values()) {
    targets.sort(byTime);
  }

  const roots = state.nodes
    .map((node) => node.id)
    .filter((nodeId) => outgoing.has(nodeId) && !incoming.has(nodeId))
    .sort(byTime);
  const fallbackRoots = roots.length ? roots : state.nodes.map((node) => node.id).sort(byTime);
  const visited = new Set();
  const order = [];

  function walk(nodeId) {
    if (!nodeId || visited.has(nodeId) || !nodesById.has(nodeId)) return;
    visited.add(nodeId);
    order.push(nodeId);
    for (const nextId of outgoing.get(nodeId) || []) {
      walk(nextId);
    }
  }

  for (const root of fallbackRoots) {
    walk(root);
  }
  for (const node of state.nodes) {
    walk(node.id);
  }
  return order;
}

async function clearComposer() {
  state.composerOrder = [];
  promptDirty = false;
  promptBox.value = "";
  await saveComposer();
}

async function resetCanvas() {
  const before = snapshotCanvasState();
  selectedEdgeId = null;
  clearNodeSelection();
  clearDiscussionPosition();
  if (apiAvailable) {
    try {
      const data = await requestJson(`${apiRoot}/reset`, { method: "POST", body: JSON.stringify({}) });
      state = normalizeState(data);
      rememberUndoAction({ type: "restore-canvas", before });
      render();
      toast("画布已还原，可用 Ctrl+Z 撤销。");
      return;
    } catch (error) {
      toast(`还原失败：${error.message}`);
      return;
    }
  }
  resetLocalCanvas();
  rememberUndoAction({ type: "restore-canvas", before });
  persistLocal();
  render();
  toast("画布已还原，可用 Ctrl+Z 撤销。");
}

function runAnchorBootstrap() {
  if (anchorBootstrapStarted || anchorBootstrapBlocked || !apiAvailable || !shouldRunAnchorBootstrap()) return;
  anchorBootstrapStarted = true;
  bootstrapAnchorNode();
}

function shouldRunAnchorBootstrap() {
  if (!state.nodes.length) return true;
  if (state.nodes.some((node) => node.origin === "reconstructed")) return false;
  return state.nodes.slice(0, 3).some(isStarterAnchorNode);
}

function isStarterAnchorNode(node) {
  const text = [
    node.type,
    node.origin,
    node.title,
    node.summary,
    node.detailMarkdown,
    ...(node.tags || []),
  ]
    .join("\n")
    .toLowerCase();
  return (
    node.type === "anchor" &&
    node.origin === "live" &&
    (text.includes("画布启用") ||
      text.includes("从当前对话开始启用") ||
      (text.includes("canvas") && text.includes("checkpoint")))
  );
}

function showRecoveryStatus(message) {
  if (!recoveryStatus) return;
  recoveryStatus.textContent = message;
  recoveryStatus.classList.remove("hidden");
  window.clearTimeout(showRecoveryStatus.timer);
  showRecoveryStatus.timer = window.setTimeout(() => {
    recoveryStatus.classList.add("hidden");
  }, 3600);
}

async function bootstrapAnchorNode() {
  try {
    const result = await requestJson(`${apiRoot}/bootstrap-anchor`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (result.created && result.session) {
      state = normalizeState(result.session);
      render();
      showRecoveryStatus("已生成当前对话起点");
    } else if (result.ok === false) {
      anchorBootstrapBlocked = true;
      showRecoveryStatus(result.message || "暂未找到可生成启示节点的记录");
    } else if (!state.nodes.length) {
      anchorBootstrapStarted = false;
    }
  } catch (error) {
    anchorBootstrapStarted = false;
    // Empty canvases can still be used manually by future checkpoints.
  }
}

function resetLocalCanvas() {
  clearDiscussionPosition();
  for (const [index, node] of state.nodes.entries()) {
    node.x = GRID_LEFT + (index % GRID_COLUMNS) * GRID_COLUMN_GAP;
    node.y = GRID_TOP + Math.floor(index / GRID_COLUMNS) * GRID_ROW_GAP;
  }
  state.edges = state.nodes.slice(1).map((node, index) => ({
    id: `reset_edge_${String(index + 1).padStart(2, "0")}`,
    from: state.nodes[index].id,
    to: node.id,
    label: "",
    createdAt: new Date().toISOString(),
  }));
}

async function copyPrompt() {
  const value = promptBox.value.trim();
  if (!value) return;
  await navigator.clipboard.writeText(value);
  toast("已复制，可以粘贴到 Codex 输入框。");
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const html = [];
  let inList = false;
  const closeList = () => {
    if (!inList) return;
    html.push("</ul>");
    inList = false;
  };
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeList();
      continue;
    }
    if (line.startsWith("## ")) {
      closeList();
      html.push(`<h4>${escapeHtml(line.slice(3))}</h4>`);
      continue;
    }
    if (line.startsWith("# ")) {
      closeList();
      html.push(`<h4>${escapeHtml(line.slice(2))}</h4>`);
      continue;
    }
    if (line.startsWith("- ")) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${escapeHtml(line.slice(2))}</li>`);
      continue;
    }
    closeList();
    html.push(`<p>${escapeHtml(line)}</p>`);
  }
  closeList();
  return html.join("");
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function toast(message) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 1800);
}

document.getElementById("refreshBtn").addEventListener("click", () => loadState({ force: true }));
document.getElementById("resetCanvasBtn").addEventListener("click", resetCanvas);
document.getElementById("addToComposerBtn").addEventListener("click", addSelectedToComposer);
document.getElementById("useMainlineOrderBtn").addEventListener("click", useMainlineOrder);
undoEdgeBtn.addEventListener("click", undoLastCanvasAction);
document.getElementById("clearComposerBtn").addEventListener("click", clearComposer);
document.getElementById("copyPromptBtn").addEventListener("click", copyPrompt);
detailResizeHandle.addEventListener("pointerdown", startDetailResize);
composerResizeHandle.addEventListener("pointerdown", startComposerResize);
promptBox.addEventListener("input", () => {
  promptDirty = true;
});

window.addEventListener("resize", () => {
  setDetailWidth(currentDetailWidth());
  setComposerHeight(currentComposerHeight());
});

document.addEventListener("keydown", (event) => {
  if (isUndoShortcut(event)) {
    if (!isEditableTarget(event.target)) {
      event.preventDefault();
      undoLastCanvasAction();
    }
    return;
  }
  if (isEditableTarget(event.target)) return;
  if (event.key === "Delete" || event.key === "Backspace") {
    if (selectedEdgeId) deleteSelectedEdge();
  }
});

function isUndoShortcut(event) {
  return (event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "z";
}

function isEditableTarget(target) {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest("textarea, input, select, [contenteditable='true'], [contenteditable='']"));
}

canvas.addEventListener("pointerdown", startMarqueeSelection);

canvas.addEventListener("click", () => {
  if (Date.now() < suppressCanvasClickUntil) return;
  clearNodeSelection();
  selectedEdgeId = null;
  render();
});

initializePanelSizes();
loadState();
setInterval(loadState, 3000);
