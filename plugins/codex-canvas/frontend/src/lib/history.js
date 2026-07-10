import { computed, ref } from "vue";

const MAX_HISTORY = 40;

export function useCanvasHistory(sessionId) {
  const storageKey = `codex-canvas:v2:history:${sessionId}`;
  const initial = loadHistory(storageKey);
  const undoStack = ref(initial.undo);
  const redoStack = ref(initial.redo);

  const canUndo = computed(() => undoStack.value.length > 0);
  const canRedo = computed(() => redoStack.value.length > 0);

  function persist() {
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({
          undo: undoStack.value.slice(-MAX_HISTORY),
          redo: redoStack.value.slice(-MAX_HISTORY),
        }),
      );
    } catch {
      // History remains available for the current page even if storage is full.
    }
  }

  function record(action) {
    undoStack.value.push({ ...action, recordedAt: new Date().toISOString() });
    if (undoStack.value.length > MAX_HISTORY) undoStack.value.shift();
    redoStack.value = [];
    persist();
  }

  async function undo(apply) {
    const action = undoStack.value.pop();
    if (!action) return false;
    try {
      await apply(action, "undo");
      redoStack.value.push(action);
      if (redoStack.value.length > MAX_HISTORY) redoStack.value.shift();
      persist();
      return true;
    } catch (error) {
      undoStack.value.push(action);
      persist();
      throw error;
    }
  }

  async function redo(apply) {
    const action = redoStack.value.pop();
    if (!action) return false;
    try {
      await apply(action, "redo");
      undoStack.value.push(action);
      if (undoStack.value.length > MAX_HISTORY) undoStack.value.shift();
      persist();
      return true;
    } catch (error) {
      redoStack.value.push(action);
      persist();
      throw error;
    }
  }

  return { canUndo, canRedo, record, undo, redo };
}

function loadHistory(key) {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || "null");
    return {
      undo: Array.isArray(parsed?.undo) ? parsed.undo.slice(-MAX_HISTORY) : [],
      redo: Array.isArray(parsed?.redo) ? parsed.redo.slice(-MAX_HISTORY) : [],
    };
  } catch {
    return { undo: [], redo: [] };
  }
}
