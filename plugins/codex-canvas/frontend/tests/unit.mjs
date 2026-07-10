import assert from "node:assert/strict";

const storage = new Map();
globalThis.localStorage = {
  getItem(key) {
    return storage.has(key) ? storage.get(key) : null;
  },
  setItem(key, value) {
    storage.set(key, String(value));
  },
  removeItem(key) {
    storage.delete(key);
  },
  clear() {
    storage.clear();
  },
};

const graph = await import("../src/lib/graph.js");
const { useCanvasHistory } = await import("../src/lib/history.js");

const nodes = [
  checkpoint("a", 80, 80, "需求", "A context"),
  checkpoint("b", 430, 80, "决策", "B context"),
  checkpoint("c", 780, 80, "实现", "C context"),
  checkpoint("d", 80, 310, "验证", "D context"),
];

const normalized = graph.normalizeSession(
  {
    sessionId: "unit",
    nodes,
    edges: [{ id: "ab", from: "a", to: "b" }],
    viewState: { discussion: { position: { x: 900, y: 500 } } },
  },
  "fallback",
);
assert.equal(normalized.viewState.discussion.positionMode, "auto");

const autoSession = graph.normalizeSession(
  {
    sessionId: "auto",
    nodes: nodes.slice(0, 2),
    edges: [{ id: "ab", from: "a", to: "b" }],
    viewState: { discussion: { mode: "auto", positionMode: "auto" } },
  },
  "auto",
);
assert.deepEqual(graph.resolveDiscussionPosition(autoSession), {
  x: 780,
  y: 80,
  anchorKey: "b",
  positionMode: "auto",
});

const manualFree = graph.normalizeSession(
  {
    ...autoSession,
    viewState: {
      discussion: {
        mode: "auto",
        positionMode: "manual",
        position: { x: 920, y: 540 },
      },
    },
  },
  "manual-free",
);
assert.deepEqual(graph.resolveDiscussionPosition(manualFree), {
  x: 920,
  y: 540,
  anchorKey: "b",
  positionMode: "manual",
});

const manualCollision = graph.normalizeSession(
  {
    ...autoSession,
    viewState: {
      discussion: {
        mode: "auto",
        positionMode: "manual",
        position: { x: 430, y: 80 },
      },
    },
  },
  "manual-collision",
);
assert.deepEqual(graph.resolveDiscussionPosition(manualCollision), {
  x: 780,
  y: 80,
  anchorKey: "b",
  positionMode: "manual",
});

const branched = graph.normalizeSession(
  {
    sessionId: "branched",
    nodes,
    edges: [
      { id: "ac", from: "a", to: "c" },
      { id: "ab", from: "a", to: "b" },
      { id: "bd", from: "b", to: "d" },
      { id: "cd", from: "c", to: "d" },
    ],
  },
  "branched",
);
const order = graph.mainlineOrder(branched);
assert.equal(new Set(order).size, 4);
assert.ok(order.indexOf("a") < order.indexOf("b"));
assert.ok(order.indexOf("a") < order.indexOf("c"));
assert.ok(order.indexOf("b") < order.indexOf("d"));
assert.ok(order.indexOf("c") < order.indexOf("d"));

branched.nodes[0].rawText = "RAW EVIDENCE MUST NOT ENTER THE PROMPT";
branched.nodes[0].contextText = "compressed context";
const prompt = graph.buildPrompt(branched);
assert.match(prompt, /compressed context/);
assert.doesNotMatch(prompt, /RAW EVIDENCE/);
assert.ok(graph.estimateTokens(prompt) > 0);
assert.deepEqual(graph.searchNodes(nodes, "验证").map((node) => node.id), ["d"]);

const history = useCanvasHistory("history-limit");
for (let index = 0; index < 45; index += 1) {
  history.record({ type: "test", index });
}
const persisted = JSON.parse(storage.get("codex-canvas:v2:history:history-limit"));
assert.equal(persisted.undo.length, 40);
assert.equal(persisted.undo[0].index, 5);
assert.equal(persisted.undo.at(-1).index, 44);

const undone = [];
for (let index = 0; index < 40; index += 1) {
  assert.equal(await history.undo(async (action) => undone.push(action.index)), true);
}
assert.deepEqual(undone, Array.from({ length: 40 }, (_, index) => 44 - index));
assert.equal(await history.undo(async () => undefined), false);
assert.equal(history.canUndo.value, false);
assert.equal(history.canRedo.value, true);
assert.equal(await history.redo(async (action) => assert.equal(action.index, 5)), true);

console.log("PASS frontend graph, prompt, search, discussion placement, and 40-step history");

function checkpoint(id, x, y, title, contextText) {
  return {
    id,
    type: "verification",
    title,
    summary: `${title} summary`,
    detailMarkdown: `## ${title}`,
    contextText,
    rawText: "",
    tags: [],
    relatedFiles: [],
    evidenceRefs: [],
    x,
    y,
    createdAt: `2026-07-10T00:00:0${id.charCodeAt(0) - 96}+08:00`,
  };
}
