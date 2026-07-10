export const DISCUSSION_NODE_ID = "__discussion__";

export function clonePlain(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

export const TYPE_LABELS = {
  anchor: "启示",
  requirement: "需求",
  decision: "决策",
  plan: "方案",
  implementation: "实现",
  verification: "验证",
  blocker: "阻塞",
  artifact: "产物",
  note: "备注",
  discussion: "讨论中",
};

export const TYPE_COLORS = {
  anchor: "#0b8f8a",
  requirement: "#4776e6",
  decision: "#f05b49",
  plan: "#7655b5",
  implementation: "#168a54",
  verification: "#087f8c",
  blocker: "#c9362b",
  artifact: "#a86c16",
  note: "#667085",
  discussion: "#f05b49",
};

export const NODE_WIDTH = 280;
export const NODE_HEIGHT = 156;
export const GRID_LEFT = 80;
export const GRID_TOP = 80;
export const GRID_COLUMN_GAP = 350;
export const GRID_ROW_GAP = 230;
export const GRID_COLUMNS = 3;

export function normalizeSession(value, fallbackSessionId) {
  const data = value && typeof value === "object" ? value : {};
  const nodes = Array.isArray(data.nodes) ? data.nodes : [];
  const nodeIds = new Set(nodes.map((node) => node.id));
  const composerOrder = unique(data.composerOrder).filter((id) => nodeIds.has(id));
  const rawView = data.viewState && typeof data.viewState === "object" ? data.viewState : {};
  const rawDiscussion = rawView.discussion && typeof rawView.discussion === "object" ? rawView.discussion : {};
  return {
    schemaVersion: Number(data.schemaVersion) || 2,
    sessionId: data.sessionId || fallbackSessionId,
    revision: Number(data.revision) || 0,
    contentRevision: Number(data.contentRevision) || 0,
    createdByPluginVersion: data.createdByPluginVersion || "unknown",
    lastOpenedByPluginVersion: data.lastOpenedByPluginVersion || "unknown",
    updatedAt: data.updatedAt || "",
    nodes,
    edges: Array.isArray(data.edges) ? data.edges : [],
    composerOrder,
    viewState: {
      composerMode: rawView.composerMode === "manual" ? "manual" : "mainline",
      discussion: {
        mode: rawDiscussion.mode === "manual" ? "manual" : "auto",
        anchorIds: unique(rawDiscussion.anchorIds).filter((id) => nodeIds.has(id)),
        position: validPosition(rawDiscussion.position) ? rawDiscussion.position : null,
        positionMode: rawDiscussion.positionMode === "manual" ? "manual" : "auto",
        anchorKey: String(rawDiscussion.anchorKey || ""),
      },
    },
    migrations: Array.isArray(data.migrations) ? data.migrations : [],
  };
}

export function nodeById(session, id) {
  return session.nodes.find((node) => node.id === id) || null;
}

export function latestNode(nodes) {
  return [...nodes].sort(compareNodes).at(-1) || null;
}

export function compareNodes(left, right) {
  const byTime = String(left?.createdAt || "").localeCompare(String(right?.createdAt || ""));
  if (byTime) return byTime;
  return String(left?.id || "").localeCompare(String(right?.id || ""));
}

export function mainlineOrder(session) {
  const nodesById = new Map(session.nodes.map((node) => [node.id, node]));
  const incomingCount = new Map(session.nodes.map((node) => [node.id, 0]));
  const outgoing = new Map(session.nodes.map((node) => [node.id, []]));
  for (const edge of session.edges) {
    if (!nodesById.has(edge.from) || !nodesById.has(edge.to)) continue;
    outgoing.get(edge.from).push(edge.to);
    incomingCount.set(edge.to, (incomingCount.get(edge.to) || 0) + 1);
  }
  const byTime = (leftId, rightId) => compareNodes(nodesById.get(leftId), nodesById.get(rightId));
  for (const targets of outgoing.values()) targets.sort(byTime);
  const queue = session.nodes
    .filter((node) => (incomingCount.get(node.id) || 0) === 0)
    .map((node) => node.id)
    .sort(byTime);
  const order = [];
  const visited = new Set();
  while (queue.length) {
    const nodeId = queue.shift();
    if (visited.has(nodeId)) continue;
    visited.add(nodeId);
    order.push(nodeId);
    for (const nextId of outgoing.get(nodeId) || []) {
      incomingCount.set(nextId, (incomingCount.get(nextId) || 0) - 1);
      if (incomingCount.get(nextId) === 0) {
        queue.push(nextId);
        queue.sort(byTime);
      }
    }
  }
  for (const node of [...session.nodes].sort(compareNodes)) {
    if (!visited.has(node.id)) order.push(node.id);
  }
  return order;
}

export function mainlineTerminal(session) {
  if (!session.nodes.length) return null;
  const outgoing = new Set(session.edges.map((edge) => edge.from));
  const incoming = new Set(session.edges.map((edge) => edge.to));
  const terminals = session.nodes.filter((node) => !outgoing.has(node.id) && incoming.has(node.id));
  return latestNode(terminals.length ? terminals : session.nodes);
}

export function discussionAnchors(session) {
  const discussion = session.viewState.discussion;
  if (discussion.mode === "manual") {
    return discussion.anchorIds.map((id) => nodeById(session, id)).filter(Boolean);
  }
  const terminal = mainlineTerminal(session);
  return terminal ? [terminal] : [];
}

export function discussionAnchorKey(session) {
  return discussionAnchors(session).map((node) => node.id).join("|");
}

export function resolveDiscussionPosition(session) {
  const discussion = session.viewState.discussion;
  const anchors = discussionAnchors(session);
  const anchorKey = anchors.map((node) => node.id).join("|");
  if (
    discussion.positionMode === "manual" &&
    validPosition(discussion.position) &&
    !session.nodes.some((node) => intersects(nodeRect(node), nodeRect(discussion.position)))
  ) {
    return { ...discussion.position, anchorKey, positionMode: "manual" };
  }
  const primary = anchors.at(-1) || latestNode(session.nodes);
  if (!primary) return { x: GRID_LEFT, y: GRID_TOP, anchorKey, positionMode: discussion.positionMode };
  const column = clamp(Math.round(((primary.x || GRID_LEFT) - GRID_LEFT) / GRID_COLUMN_GAP), 0, GRID_COLUMNS - 1);
  const start = {
    x: column >= GRID_COLUMNS - 1 ? GRID_LEFT : (primary.x || GRID_LEFT) + GRID_COLUMN_GAP,
    y: column >= GRID_COLUMNS - 1 ? (primary.y || GRID_TOP) + GRID_ROW_GAP : primary.y || GRID_TOP,
  };
  const candidate = nextFreeSlot(start, session.nodes);
  return { ...candidate, anchorKey, positionMode: discussion.positionMode };
}

export function nextFreeSlot(start, nodes) {
  let x = start.x;
  let y = start.y;
  for (let guard = 0; guard < nodes.length + GRID_COLUMNS + 4; guard += 1) {
    const candidate = { x, y };
    if (!nodes.some((node) => intersects(nodeRect(node), nodeRect(candidate)))) return candidate;
    const column = clamp(Math.round((x - GRID_LEFT) / GRID_COLUMN_GAP), 0, GRID_COLUMNS - 1);
    if (column >= GRID_COLUMNS - 1) {
      x = GRID_LEFT;
      y += GRID_ROW_GAP;
    } else {
      x += GRID_COLUMN_GAP;
    }
  }
  return { x, y };
}

export function canvasSnapshot(session) {
  return {
    nodeIds: session.nodes.map((node) => node.id),
    positions: Object.fromEntries(session.nodes.map((node) => [node.id, { x: node.x || 0, y: node.y || 0 }])),
    edges: session.edges.map((edge) => ({ ...edge })),
    discussion: clonePlain(session.viewState.discussion),
  };
}

export function selectedComposerOrder(session) {
  return session.viewState.composerMode === "mainline" ? mainlineOrder(session) : session.composerOrder;
}

export function buildPrompt(session) {
  const nodes = selectedComposerOrder(session).map((id) => nodeById(session, id)).filter(Boolean);
  if (!nodes.length) return "";
  const chunks = nodes.map((node, index) => {
    const files = node.relatedFiles?.length ? `\n相关文件：${node.relatedFiles.join("、")}` : "";
    const evidence = node.evidenceRefs?.length ? `\n证据来源：${node.evidenceRefs.join("、")}` : "";
    const context = node.contextText || node.detailMarkdown || node.summary || node.rawText || "";
    return `【${index + 1}. ${node.title}】\n类型：${TYPE_LABELS[node.type] || node.type}\n摘要：${node.summary || ""}${files}${evidence}\n上下文：\n${context}`;
  });
  return `请基于以下对话画布检查点继续处理。这些内容是我选择的压缩上下文，不会修改你的记忆或系统上下文。\n\n${chunks.join("\n\n---\n\n")}`;
}

export function estimateTokens(text) {
  let units = 0;
  for (const char of String(text || "")) {
    units += /[\u3400-\u9fff\uf900-\ufaff]/.test(char) ? 0.9 : /\s/.test(char) ? 0.08 : 0.28;
  }
  return Math.max(0, Math.ceil(units));
}

export function searchNodes(nodes, query) {
  const value = String(query || "").trim().toLowerCase();
  if (!value) return [];
  return nodes
    .filter((node) => {
      const text = [node.title, node.summary, node.detailMarkdown, node.contextText, ...(node.tags || [])]
        .join("\n")
        .toLowerCase();
      return text.includes(value);
    })
    .sort(compareNodes)
    .reverse();
}

export function unique(values) {
  return [...new Set((Array.isArray(values) ? values : []).filter(Boolean))];
}

function validPosition(value) {
  return value && Number.isFinite(Number(value.x)) && Number.isFinite(Number(value.y));
}

function nodeRect(node) {
  return {
    left: Number(node.x) || 0,
    top: Number(node.y) || 0,
    right: (Number(node.x) || 0) + NODE_WIDTH,
    bottom: (Number(node.y) || 0) + NODE_HEIGHT,
  };
}

function intersects(left, right) {
  return left.left <= right.right && left.right >= right.left && left.top <= right.bottom && left.bottom >= right.top;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
