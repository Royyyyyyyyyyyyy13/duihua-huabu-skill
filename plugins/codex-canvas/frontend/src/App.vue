<script setup>
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import { MarkerType, VueFlow } from "@vue-flow/core";
import { MiniMap } from "@vue-flow/minimap";
import {
  Download,
  Focus,
  Redo2,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  Undo2,
  X,
} from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import CheckpointNode from "./components/CheckpointNode.vue";
import ComposerPanel from "./components/ComposerPanel.vue";
import ConversationEdge from "./components/ConversationEdge.vue";
import DiscussionNode from "./components/DiscussionNode.vue";
import InspectorPanel from "./components/InspectorPanel.vue";
import {
  createEdge,
  exportUrl,
  fetchSession,
  patchEdge,
  removeEdge,
  resetCanvas as requestResetCanvas,
  restoreCanvas,
  saveComposer,
  saveLayout,
  saveView,
  sessionId,
} from "./lib/api";
import {
  canvasSnapshot,
  clonePlain,
  DISCUSSION_NODE_ID,
  discussionAnchorKey,
  discussionAnchors,
  normalizeSession,
  resolveDiscussionPosition,
  searchNodes,
  TYPE_COLORS,
  unique,
} from "./lib/graph";
import { useCanvasHistory } from "./lib/history";

const flowRef = ref(null);
const session = ref(normalizeSession({ sessionId }, sessionId));
const canvasNodes = ref([]);
const canvasEdges = ref([]);
const selectedNodeId = ref(null);
const selectedEdgeId = ref(null);
const searchQuery = ref("");
const syncState = ref("loading");
const syncMessage = ref("正在加载");
const toastMessage = ref("");
const inspectorWidth = ref(clamp(Number(localStorage.getItem("codex-canvas:v2:inspector-width")) || 368, 300, 640));
const isInteracting = ref(false);
const pendingSession = ref(null);
const initialFocusPending = ref(true);
const nodeDragBefore = ref(null);
const placementWriteKey = ref("");
const history = useCanvasHistory(sessionId);

let pollTimer = null;
let toastTimer = null;
let viewportResizeTimer = null;
let viewportBucket = layoutBucket(window.innerWidth);
let composerQueue = Promise.resolve();

const selectedNode = computed(() => session.value.nodes.find((node) => node.id === selectedNodeId.value) || null);
const selectedFormalIds = computed(() =>
  canvasNodes.value.filter((node) => node.id !== DISCUSSION_NODE_ID && node.selected).map((node) => node.id),
);
const searchResults = computed(() => searchNodes(session.value.nodes, searchQuery.value).slice(0, 12));
const statusClass = computed(() => `status-${syncState.value}`);

watch(searchQuery, syncSearchState);

function applySession(value, options = {}) {
  const normalized = normalizeSession(value, sessionId);
  if (!options.force && normalized.revision < session.value.revision) return;
  session.value = normalized;
  syncFlowModel();
  syncState.value = "saved";
  syncMessage.value = "已同步";
  ensureDiscussionPlacement();
}

function syncFlowModel() {
  const selectedNodes = new Set(canvasNodes.value.filter((node) => node.selected).map((node) => node.id));
  const selectedEdges = new Set(canvasEdges.value.filter((edge) => edge.selected).map((edge) => edge.id));
  const query = searchQuery.value.trim().toLowerCase();
  const matchedIds = new Set(searchNodes(session.value.nodes, query).map((node) => node.id));
  canvasNodes.value = session.value.nodes.map((node) => ({
    id: node.id,
    type: "checkpoint",
    position: { x: Number(node.x) || 0, y: Number(node.y) || 0 },
    draggable: true,
    selectable: true,
    deletable: false,
    selected: selectedNodes.has(node.id) || selectedNodeId.value === node.id,
    data: {
      node,
      searchActive: Boolean(query),
      searchMatch: matchedIds.has(node.id),
    },
  }));

  if (session.value.nodes.length) {
    const placement = resolveDiscussionPosition(session.value);
    const anchors = discussionAnchors(session.value);
    canvasNodes.value.push({
      id: DISCUSSION_NODE_ID,
      type: "discussion",
      position: { x: placement.x, y: placement.y },
      draggable: true,
      selectable: false,
      deletable: false,
      selected: false,
      data: {
        mode: session.value.viewState.discussion.mode,
        anchorCount: anchors.length,
      },
    });
  }

  const marker = { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "#98a2b3" };
  canvasEdges.value = session.value.edges.map((edge) => ({
    id: edge.id,
    source: edge.from,
    target: edge.to,
    sourceHandle: "source",
    targetHandle: "target",
    type: "conversation",
    updatable: true,
    selectable: true,
    deletable: false,
    selected: selectedEdges.has(edge.id) || selectedEdgeId.value === edge.id,
    markerEnd: marker,
    data: { discussion: false, edge },
  }));
  for (const anchor of discussionAnchors(session.value)) {
    const edgeId = `discussion:${anchor.id}`;
    canvasEdges.value.push({
      id: edgeId,
      source: anchor.id,
      target: DISCUSSION_NODE_ID,
      sourceHandle: "source",
      targetHandle: "target",
      type: "conversation",
      updatable: "source",
      selectable: true,
      deletable: false,
      selected: selectedEdges.has(edgeId) || selectedEdgeId.value === edgeId,
      markerEnd: { ...marker, color: TYPE_COLORS.discussion },
      data: { discussion: true },
    });
  }
}

function syncSearchState() {
  const query = searchQuery.value.trim().toLowerCase();
  const matchedIds = new Set(searchNodes(session.value.nodes, query).map((node) => node.id));
  canvasNodes.value = canvasNodes.value.map((node) => {
    if (node.id === DISCUSSION_NODE_ID) return node;
    return {
      ...node,
      data: {
        ...node.data,
        searchActive: Boolean(query),
        searchMatch: matchedIds.has(node.id),
      },
    };
  });
}

async function refreshSession(options = {}) {
  try {
    const data = await fetchSession();
    if (!options.force && data.revision === session.value.revision) {
      syncState.value = "saved";
      syncMessage.value = "已同步";
      return;
    }
    if (isInteracting.value && !options.force) {
      pendingSession.value = data;
      return;
    }
    applySession(data, { force: options.force });
  } catch (error) {
    syncState.value = "error";
    syncMessage.value = "连接中断";
    if (options.announce) notify(error.message);
  }
}

async function ensureDiscussionPlacement() {
  if (!session.value.nodes.length) return;
  const placement = resolveDiscussionPosition(session.value);
  const current = session.value.viewState.discussion;
  if (
    current.anchorKey === placement.anchorKey &&
    current.positionMode === placement.positionMode &&
    current.position &&
    Number(current.position.x) === Number(placement.x) &&
    Number(current.position.y) === Number(placement.y)
  ) {
    return;
  }
  const writeKey = `${session.value.contentRevision}:${placement.anchorKey}`;
  if (placementWriteKey.value === writeKey) return;
  placementWriteKey.value = writeKey;
  try {
    const data = await saveView({
      discussion: {
        ...current,
        position: { x: placement.x, y: placement.y },
        positionMode: placement.positionMode,
        anchorKey: placement.anchorKey,
      },
    });
    applySession(data);
  } catch {
    placementWriteKey.value = "";
  }
}

async function focusNode(nodeId) {
  if (!session.value.nodes.some((node) => node.id === nodeId)) return;
  searchQuery.value = "";
  selectedNodeId.value = nodeId;
  selectedEdgeId.value = null;
  canvasNodes.value = canvasNodes.value.map((node) => ({ ...node, selected: node.id === nodeId }));
  canvasEdges.value = canvasEdges.value.map((edge) => ({ ...edge, selected: false }));
  await nextTick();
  await flowRef.value?.fitView({ nodes: [nodeId], padding: 1.5, duration: 320, maxZoom: 1.15 });
}

async function focusCurrent() {
  const anchors = discussionAnchors(session.value).map((node) => node.id);
  const nodes = session.value.nodes.length ? [...anchors, DISCUSSION_NODE_ID] : [];
  if (!nodes.length) return fitAll();
  await flowRef.value?.fitView({ nodes, padding: 1.2, duration: 380, maxZoom: 1.05 });
}

async function fitAll() {
  await flowRef.value?.fitView({ padding: 0.18, duration: 380, minZoom: 0.16, maxZoom: 1 });
}

function onNodesInitialized() {
  if (!initialFocusPending.value) return;
  initialFocusPending.value = false;
  nextTick(focusCurrent);
}

function onNodeClick({ node }) {
  selectedEdgeId.value = null;
  if (node.id === DISCUSSION_NODE_ID) {
    selectedNodeId.value = null;
    canvasNodes.value = canvasNodes.value.map((item) => ({ ...item, selected: false }));
    return;
  }
  selectedNodeId.value = node.id;
}

function onEdgeClick({ edge }) {
  selectedNodeId.value = null;
  selectedEdgeId.value = edge.id;
}

function onPaneClick() {
  selectedNodeId.value = null;
  selectedEdgeId.value = null;
}

function onNodeDragStart({ node, nodes }) {
  isInteracting.value = true;
  if (node.id === DISCUSSION_NODE_ID) {
    nodeDragBefore.value = {
      kind: "discussion",
      discussion: clonePlain(session.value.viewState.discussion),
    };
    return;
  }
  const formal = nodes.filter((node) => node.id !== DISCUSSION_NODE_ID);
  if (formal.length) {
    nodeDragBefore.value = {
      kind: "layout",
      positions: Object.fromEntries(formal.map((node) => [node.id, { ...node.position }])),
    };
    return;
  }
  nodeDragBefore.value = null;
}

async function onNodeDragStop({ node, nodes }) {
  try {
    if (node.id === DISCUSSION_NODE_ID) {
      const before = nodeDragBefore.value?.discussion || clonePlain(session.value.viewState.discussion);
      const after = {
        ...session.value.viewState.discussion,
        position: { x: node.position.x, y: node.position.y },
        positionMode: "manual",
        anchorKey: discussionAnchorKey(session.value),
      };
      const data = await saveView({ discussion: after });
      history.record({ type: "discussion", before, after });
      applySession(data);
      return;
    }
    const formal = nodes.filter((item) => item.id !== DISCUSSION_NODE_ID);
    const positions = Object.fromEntries(formal.map((item) => [item.id, { x: item.position.x, y: item.position.y }]));
    const before = nodeDragBefore.value?.positions || positions;
    const data = await saveLayout(positions);
    history.record({ type: "layout", before, after: positions });
    applySession(data);
  } catch (error) {
    notify(`位置保存失败：${error.message}`);
    await refreshSession({ force: true });
  } finally {
    finishInteraction();
  }
}

async function onConnect(connection) {
  try {
    if (!connection.source || !connection.target || connection.source === connection.target) return;
    if (connection.target === DISCUSSION_NODE_ID) {
      await connectDiscussionSource(connection.source);
      return;
    }
    if (connection.source === DISCUSSION_NODE_ID) return;
    const edge = await createEdge({
      id: newId("edge"),
      from: connection.source,
      to: connection.target,
      label: "",
      createdAt: new Date().toISOString(),
    });
    history.record({ type: "edge-create", edge });
    await refreshSession({ force: true });
    notify("已建立阶段关系");
  } catch (error) {
    notify(`连线失败：${error.message}`);
  } finally {
    finishInteraction();
  }
}

async function connectDiscussionSource(sourceId) {
  const before = clonePlain(session.value.viewState.discussion);
  const anchors = before.mode === "manual" ? [...before.anchorIds] : [];
  const nextAnchors = unique([...anchors, sourceId]);
  const after = {
    ...before,
    mode: "manual",
    anchorIds: nextAnchors,
    positionMode: "manual",
    anchorKey: nextAnchors.join("|"),
  };
  const data = await saveView({ discussion: after });
  history.record({ type: "discussion", before, after });
  applySession(data);
  notify("已更新当前讨论来源");
}

async function resetDiscussionToAuto() {
  const before = clonePlain(session.value.viewState.discussion);
  const after = {
    ...before,
    mode: "auto",
    anchorIds: [],
    positionMode: "auto",
    anchorKey: "",
  };
  try {
    const data = await saveView({ discussion: after });
    history.record({ type: "discussion", before, after });
    selectedEdgeId.value = null;
    applySession(data);
    notify("当前讨论已恢复自动跟随，可撤销");
  } catch (error) {
    notify(`恢复失败：${error.message}`);
  }
}

async function onEdgeUpdate({ edge, connection }) {
  if (!connection.source || !connection.target || connection.source === connection.target) return;
  try {
    if (edge.data?.discussion || edge.id.startsWith("discussion:")) {
      const before = clonePlain(session.value.viewState.discussion);
      const oldSource = edge.source;
      const currentAnchors = before.mode === "manual" ? before.anchorIds : [oldSource];
      const nextAnchors = unique(currentAnchors.map((id) => (id === oldSource ? connection.source : id)));
      const after = {
        ...before,
        mode: "manual",
        anchorIds: nextAnchors,
        anchorKey: nextAnchors.join("|"),
      };
      const data = await saveView({ discussion: after });
      history.record({ type: "discussion", before, after });
      applySession(data);
      notify("已重连当前讨论来源");
      return;
    }
    const before = { ...edge.data.edge };
    const after = await patchEdge(edge.id, { from: connection.source, to: connection.target, label: before.label || "" });
    history.record({ type: "edge-update", before, after });
    await refreshSession({ force: true });
    notify("已更新阶段关系");
  } catch (error) {
    notify(`重连失败：${error.message}`);
    await refreshSession({ force: true });
  } finally {
    finishInteraction();
  }
}

function isValidConnection(connection) {
  if (!connection.source || !connection.target || connection.source === connection.target) return false;
  return connection.source !== DISCUSSION_NODE_ID;
}

async function deleteSelectedEdge() {
  const edgeId = selectedEdgeId.value;
  if (!edgeId) return;
  const flowEdge = canvasEdges.value.find((edge) => edge.id === edgeId);
  if (!flowEdge) return;
  try {
    if (flowEdge.data?.discussion || edgeId.startsWith("discussion:")) {
      const before = clonePlain(session.value.viewState.discussion);
      const sourceId = flowEdge.source;
      const currentAnchors = before.mode === "manual" ? before.anchorIds : [sourceId];
      const nextAnchors = currentAnchors.filter((id) => id !== sourceId);
      const after = {
        ...before,
        mode: "manual",
        anchorIds: nextAnchors,
        anchorKey: nextAnchors.join("|"),
      };
      const data = await saveView({ discussion: after });
      history.record({ type: "discussion", before, after });
      applySession(data);
      selectedEdgeId.value = null;
      notify("已移除当前讨论来源，可撤销");
      return;
    }
    const edge = flowEdge.data.edge;
    await removeEdge(edgeId);
    history.record({ type: "edge-delete", edge });
    selectedEdgeId.value = null;
    await refreshSession({ force: true });
    notify("已删除阶段关系，可撤销");
  } catch (error) {
    notify(`删除失败：${error.message}`);
  }
}

async function resetCanvas() {
  const before = canvasSnapshot(session.value);
  try {
    const data = await requestResetCanvas();
    const after = canvasSnapshot(normalizeSession(data, sessionId));
    history.record({ type: "reset", before, after });
    selectedNodeId.value = null;
    selectedEdgeId.value = null;
    applySession(data);
    await nextTick();
    await fitAll();
    notify("画布已还原，可撤销");
  } catch (error) {
    notify(`还原失败：${error.message}`);
  }
}

async function undo() {
  if (!history.canUndo.value) return;
  try {
    await history.undo(applyHistoryAction);
    notify("已撤销");
  } catch (error) {
    notify(`撤销失败：${error.message}`);
  }
}

async function redo() {
  if (!history.canRedo.value) return;
  try {
    await history.redo(applyHistoryAction);
    notify("已重做");
  } catch (error) {
    notify(`重做失败：${error.message}`);
  }
}

async function applyHistoryAction(action, direction) {
  const value = direction === "undo" ? action.before : action.after;
  if (action.type === "layout") {
    applySession(await saveLayout(value));
    return;
  }
  if (action.type === "discussion") {
    applySession(await saveView({ discussion: value }));
    return;
  }
  if (action.type === "edge-create") {
    if (direction === "undo") await removeEdge(action.edge.id);
    else await createEdge(action.edge);
    await refreshSession({ force: true });
    return;
  }
  if (action.type === "edge-delete") {
    if (direction === "undo") await createEdge(action.edge);
    else await removeEdge(action.edge.id);
    await refreshSession({ force: true });
    return;
  }
  if (action.type === "edge-update") {
    await patchEdge(value.id, { from: value.from, to: value.to, label: value.label || "" });
    await refreshSession({ force: true });
    return;
  }
  if (action.type === "reset") {
    applySession(await restoreCanvas(value));
  }
}

function enqueueComposer(order, mode) {
  composerQueue = composerQueue
    .catch(() => undefined)
    .then(async () => {
      const data = await saveComposer(order, mode);
      applySession(data);
    })
    .catch((error) => notify(`组装顺序保存失败：${error.message}`));
  return composerQueue;
}

function changeComposerMode(mode) {
  enqueueComposer(session.value.composerOrder, mode);
}

function changeComposerOrder(order) {
  enqueueComposer(order, "manual");
}

function addNodeToComposer(nodeId) {
  const order = unique([...session.value.composerOrder, nodeId]);
  enqueueComposer(order, "manual");
  notify("已加入手动组装");
}

function addSelectedToComposer() {
  const ordered = session.value.nodes.map((node) => node.id).filter((id) => selectedFormalIds.value.includes(id));
  if (!ordered.length) return;
  enqueueComposer(unique([...session.value.composerOrder, ...ordered]), "manual");
  notify(`已加入 ${ordered.length} 个节点`);
}

function exportSession() {
  const link = document.createElement("a");
  link.href = exportUrl();
  link.download = `codex-canvas-${session.value.sessionId}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  notify("画布备份已导出");
}

function startInspectorResize(event) {
  if (event.button !== 0) return;
  event.preventDefault();
  const startX = event.clientX;
  const startWidth = inspectorWidth.value;
  document.body.classList.add("is-resizing-inspector");
  const move = (moveEvent) => {
    inspectorWidth.value = clamp(startWidth - (moveEvent.clientX - startX), 300, Math.min(640, window.innerWidth - 620));
  };
  const end = () => {
    document.removeEventListener("pointermove", move);
    document.removeEventListener("pointerup", end);
    document.removeEventListener("pointercancel", end);
    document.body.classList.remove("is-resizing-inspector");
    localStorage.setItem("codex-canvas:v2:inspector-width", String(inspectorWidth.value));
  };
  document.addEventListener("pointermove", move);
  document.addEventListener("pointerup", end);
  document.addEventListener("pointercancel", end);
}

function onSearchKeydown(event) {
  if (event.key === "Escape") {
    searchQuery.value = "";
    event.currentTarget.blur();
    return;
  }
  if (event.key === "Enter" && searchResults.value.length) {
    event.preventDefault();
    focusNode(searchResults.value[0].id);
  }
}

function onKeydown(event) {
  const editable = event.target instanceof Element && event.target.closest("textarea, input, select, [contenteditable='true']");
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && !editable) {
    event.preventDefault();
    event.shiftKey ? redo() : undo();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y" && !editable) {
    event.preventDefault();
    redo();
    return;
  }
  if ((event.key === "Delete" || event.key === "Backspace") && !editable && selectedEdgeId.value) {
    event.preventDefault();
    deleteSelectedEdge();
  }
}

function finishInteraction() {
  isInteracting.value = false;
  nodeDragBefore.value = null;
  if (pendingSession.value) {
    const pending = pendingSession.value;
    pendingSession.value = null;
    applySession(pending);
  }
}

function notify(message) {
  toastMessage.value = message;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toastMessage.value = "";
  }, 2200);
}

function newId(prefix) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}_${suffix}`;
}

function miniMapColor(node) {
  if (node.id === DISCUSSION_NODE_ID) return TYPE_COLORS.discussion;
  return TYPE_COLORS[node.data?.node?.type] || TYPE_COLORS.note;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function layoutBucket(width) {
  if (width <= 620) return "mobile";
  if (width <= 860) return "narrow";
  if (width <= 1120) return "compact";
  return "desktop";
}

function onViewportResize() {
  const nextBucket = layoutBucket(window.innerWidth);
  if (nextBucket === viewportBucket) return;
  viewportBucket = nextBucket;
  window.clearTimeout(viewportResizeTimer);
  viewportResizeTimer = window.setTimeout(() => nextTick(focusCurrent), 180);
}

onMounted(async () => {
  window.addEventListener("keydown", onKeydown);
  window.addEventListener("resize", onViewportResize);
  await refreshSession({ force: true, announce: true });
  pollTimer = window.setInterval(refreshSession, 2500);
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKeydown);
  window.removeEventListener("resize", onViewportResize);
  window.clearInterval(pollTimer);
  window.clearTimeout(toastTimer);
  window.clearTimeout(viewportResizeTimer);
  document.body.classList.remove("is-resizing-inspector");
});
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand-block">
        <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>
        <div>
          <h1>对话画布</h1>
          <p>{{ session.sessionId }}</p>
        </div>
      </div>

      <div class="search-block">
        <Search :size="17" aria-hidden="true" />
        <input v-model="searchQuery" type="search" placeholder="搜索检查点" aria-label="搜索检查点" @keydown="onSearchKeydown" />
        <button v-if="searchQuery" type="button" aria-label="清空搜索" @click="searchQuery = ''"><X :size="15" /></button>
        <div v-if="searchQuery" class="search-results">
          <p v-if="!searchResults.length">没有匹配的检查点</p>
          <button v-for="item in searchResults" :key="item.id" type="button" @click="focusNode(item.id)">
            <span :style="{ '--search-color': TYPE_COLORS[item.type] || TYPE_COLORS.note }"></span>
            <strong>{{ item.title }}</strong>
            <small>{{ item.summary }}</small>
          </button>
        </div>
      </div>

      <div class="topbar-actions">
        <span class="sync-status" :class="statusClass"><i></i>{{ syncMessage }}</span>
        <button class="icon-button" type="button" title="定位当前讨论" aria-label="定位当前讨论" @click="focusCurrent"><Focus :size="17" /></button>
        <button class="icon-button" type="button" title="显示全部节点" aria-label="显示全部节点" @click="fitAll"><Search :size="17" /></button>
        <button class="icon-button" type="button" title="刷新" aria-label="刷新" @click="refreshSession({ force: true, announce: true })"><RefreshCw :size="17" /></button>
        <button class="icon-button" type="button" title="撤销（Ctrl+Z）" aria-label="撤销" :disabled="!history.canUndo.value" @click="undo"><Undo2 :size="17" /></button>
        <button class="icon-button" type="button" title="重做（Ctrl+Shift+Z）" aria-label="重做" :disabled="!history.canRedo.value" @click="redo"><Redo2 :size="17" /></button>
        <button v-if="selectedEdgeId" class="icon-button danger-icon" type="button" title="删除选中关系" aria-label="删除选中关系" @click="deleteSelectedEdge"><Trash2 :size="17" /></button>
        <button class="icon-button" type="button" title="导出画布备份" aria-label="导出画布备份" @click="exportSession"><Download :size="17" /></button>
        <button class="icon-button" type="button" title="还原画布" aria-label="还原画布" @click="resetCanvas"><RotateCcw :size="17" /></button>
      </div>
    </header>

    <main class="workspace" :class="{ 'has-detail': selectedNode }" :style="{ '--inspector-width': `${inspectorWidth}px` }">
      <section class="canvas-stage" aria-label="对话检查点画布">
        <VueFlow
          id="conversation-canvas"
          ref="flowRef"
          v-model:nodes="canvasNodes"
          v-model:edges="canvasEdges"
          class="conversation-flow"
          :min-zoom="0.15"
          :max-zoom="1.8"
          :fit-view-on-init="false"
          :nodes-deletable="false"
          :edges-deletable="false"
          :edges-updatable="true"
          :connect-on-click="false"
          :zoom-on-double-click="false"
          :pan-on-scroll="true"
          :selection-key-code="true"
          :pan-on-drag="[1, 2]"
          :multi-selection-key-code="'Shift'"
          :delete-key-code="null"
          :is-valid-connection="isValidConnection"
          @nodes-initialized="onNodesInitialized"
          @node-click="onNodeClick"
          @edge-click="onEdgeClick"
          @pane-click="onPaneClick"
          @node-drag-start="onNodeDragStart"
          @node-drag-stop="onNodeDragStop"
          @connect-start="isInteracting = true"
          @connect="onConnect"
          @connect-end="finishInteraction"
          @edge-update-start="isInteracting = true"
          @edge-update="onEdgeUpdate"
          @edge-update-end="finishInteraction"
        >
          <Background pattern-color="#c7ccd7" :gap="22" :size="1.15" />
          <MiniMap :node-color="miniMapColor" :pannable="true" :zoomable="true" />
          <Controls :show-interactive="false" position="bottom-left" />
          <template #node-checkpoint="nodeProps"><CheckpointNode v-bind="nodeProps" /></template>
          <template #node-discussion="nodeProps">
            <DiscussionNode v-bind="nodeProps" @reset-auto="resetDiscussionToAuto" />
          </template>
          <template #edge-conversation="edgeProps"><ConversationEdge v-bind="edgeProps" /></template>
        </VueFlow>

        <div v-if="selectedFormalIds.length > 1" class="selection-toolbar">
          <strong>{{ selectedFormalIds.length }} 个节点</strong>
          <button type="button" @click="addSelectedToComposer">加入手动组装</button>
        </div>

        <div v-if="!session.nodes.length && syncState !== 'loading'" class="empty-state">
          <span class="empty-mark" aria-hidden="true"></span>
          <h2>等待首个检查点</h2>
          <p>当前对话完成一个阶段后，Codex 会把结果写到这里。</p>
        </div>
      </section>

      <div class="inspector-resize-handle" title="拖动改变详情栏宽度" @pointerdown="startInspectorResize"></div>
      <InspectorPanel
        :session="session"
        :node="selectedNode"
        @close="selectedNodeId = null"
        @focus-node="focusNode"
        @add-node="addNodeToComposer"
      />
    </main>

    <ComposerPanel
      :session="session"
      @mode-change="changeComposerMode"
      @order-change="changeComposerOrder"
      @notify="notify"
    />

    <div v-if="toastMessage" class="toast" role="status">{{ toastMessage }}</div>
  </div>
</template>
