<script setup>
import { Check, ChevronDown, ChevronUp, Copy, RefreshCw, Trash2, X } from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { buildPrompt, estimateTokens, nodeById, selectedComposerOrder, TYPE_LABELS } from "../lib/graph";

const props = defineProps({
  session: { type: Object, required: true },
});

const emit = defineEmits(["mode-change", "order-change", "notify"]);
const storageKey = `codex-canvas:v2:composer-draft:${props.session.sessionId}`;
const sizeKey = "codex-canvas:v2:composer-height";
const initialDraft = loadDraft();
const draft = ref(initialDraft.text);
const dirty = ref(initialDraft.dirty);
const stale = ref(false);
const collapsed = ref(false);
const height = ref(clamp(Number(localStorage.getItem(sizeKey)) || 258, 170, Math.round(window.innerHeight * 0.58)));
const draggingId = ref(null);

const generatedPrompt = computed(() => buildPrompt(props.session));
const activeOrder = computed(() => selectedComposerOrder(props.session));
const activeNodes = computed(() => activeOrder.value.map((id) => nodeById(props.session, id)).filter(Boolean));
const tokenEstimate = computed(() => estimateTokens(draft.value));

watch(
  generatedPrompt,
  (value) => {
    if (!dirty.value) {
      draft.value = value;
      stale.value = false;
      persistDraft();
      return;
    }
    stale.value = draft.value !== value;
  },
  { immediate: true },
);

function onInput() {
  dirty.value = draft.value !== generatedPrompt.value;
  stale.value = dirty.value;
  persistDraft();
}

function regenerate() {
  draft.value = generatedPrompt.value;
  dirty.value = false;
  stale.value = false;
  persistDraft();
}

function clearComposer() {
  emit("mode-change", "manual");
  emit("order-change", []);
  draft.value = "";
  dirty.value = false;
  stale.value = false;
  persistDraft();
}

async function copyPrompt() {
  if (!draft.value.trim()) return;
  try {
    await navigator.clipboard.writeText(draft.value);
    emit("notify", "已复制到剪贴板");
  } catch {
    emit("notify", "复制失败，请手动选择文本");
  }
}

function removeNode(nodeId) {
  if (props.session.viewState.composerMode !== "manual") return;
  emit(
    "order-change",
    props.session.composerOrder.filter((id) => id !== nodeId),
  );
}

function startReorder(event, nodeId) {
  if (props.session.viewState.composerMode !== "manual") return;
  draggingId.value = nodeId;
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", nodeId);
}

function dropBefore(event, targetId) {
  event.preventDefault();
  const sourceId = draggingId.value || event.dataTransfer.getData("text/plain");
  draggingId.value = null;
  if (!sourceId || sourceId === targetId || props.session.viewState.composerMode !== "manual") return;
  const order = props.session.composerOrder.filter((id) => id !== sourceId);
  const targetIndex = order.indexOf(targetId);
  order.splice(targetIndex < 0 ? order.length : targetIndex, 0, sourceId);
  emit("order-change", order);
}

function startResize(event) {
  if (event.button !== 0 || collapsed.value) return;
  event.preventDefault();
  const startY = event.clientY;
  const startHeight = height.value;
  document.body.classList.add("is-resizing-composer");
  const move = (moveEvent) => {
    height.value = clamp(startHeight - (moveEvent.clientY - startY), 170, Math.round(window.innerHeight * 0.58));
  };
  const end = () => {
    document.removeEventListener("pointermove", move);
    document.removeEventListener("pointerup", end);
    document.removeEventListener("pointercancel", end);
    document.body.classList.remove("is-resizing-composer");
    localStorage.setItem(sizeKey, String(height.value));
  };
  document.addEventListener("pointermove", move);
  document.addEventListener("pointerup", end);
  document.addEventListener("pointercancel", end);
}

function persistDraft() {
  try {
    localStorage.setItem(storageKey, JSON.stringify({ text: draft.value, dirty: dirty.value }));
  } catch {
    // The current in-memory draft remains intact.
  }
}

function loadDraft() {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey) || "null");
    return { text: String(value?.text || ""), dirty: Boolean(value?.dirty) };
  } catch {
    return { text: "", dirty: false };
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

onBeforeUnmount(() => document.body.classList.remove("is-resizing-composer"));
</script>

<template>
  <footer class="composer-panel" :class="{ 'is-collapsed': collapsed }" :style="{ height: collapsed ? '48px' : `${height}px` }">
    <div class="composer-resize-handle" title="拖动改变组装区高度" @pointerdown="startResize"></div>
    <div class="composer-header">
      <div class="composer-title-row">
        <h2>上下文组装</h2>
        <span class="composer-count">{{ activeNodes.length }} 个节点</span>
        <span v-if="stale" class="composer-stale">内容待更新</span>
      </div>

      <div class="composer-toolbar">
        <div class="segmented-control" aria-label="组装模式">
          <button
            type="button"
            :class="{ active: session.viewState.composerMode === 'mainline' }"
            title="实线关系改变时自动更新顺序"
            @click="emit('mode-change', 'mainline')"
          >主线</button>
          <button
            type="button"
            :class="{ active: session.viewState.composerMode === 'manual' }"
            title="只使用手动加入的节点"
            @click="emit('mode-change', 'manual')"
          >手动</button>
        </div>
        <span class="token-estimate" title="按中英文字符粗略估算">约 {{ tokenEstimate }} tokens</span>
        <button class="icon-button" type="button" title="按当前节点重新生成" aria-label="重新生成" @click="regenerate">
          <RefreshCw :size="16" />
        </button>
        <button class="icon-button" type="button" title="清空组装区" aria-label="清空组装区" @click="clearComposer">
          <Trash2 :size="16" />
        </button>
        <button class="icon-button primary-icon" type="button" title="复制到剪贴板" aria-label="复制到剪贴板" @click="copyPrompt">
          <Copy :size="16" />
        </button>
        <button class="icon-button" type="button" :title="collapsed ? '展开组装区' : '收起组装区'" :aria-label="collapsed ? '展开组装区' : '收起组装区'" @click="collapsed = !collapsed">
          <ChevronUp v-if="collapsed" :size="17" />
          <ChevronDown v-else :size="17" />
        </button>
      </div>
    </div>

    <template v-if="!collapsed">
      <div class="composer-node-strip">
        <span v-if="!activeNodes.length" class="composer-empty">暂无组装节点</span>
        <button
          v-for="(node, index) in activeNodes"
          :key="node.id"
          class="composer-chip"
          :class="{ draggable: session.viewState.composerMode === 'manual' }"
          type="button"
          :draggable="session.viewState.composerMode === 'manual'"
          @dragstart="startReorder($event, node.id)"
          @dragover.prevent
          @drop="dropBefore($event, node.id)"
        >
          <span>{{ index + 1 }}</span>
          <strong>{{ node.title }}</strong>
          <small>{{ TYPE_LABELS[node.type] || "备注" }}</small>
          <X v-if="session.viewState.composerMode === 'manual'" :size="13" @click.stop="removeNode(node.id)" />
        </button>
      </div>
      <div class="composer-editor-wrap">
        <textarea v-model="draft" aria-label="组装后的上下文" spellcheck="false" @input="onInput"></textarea>
        <span v-if="!dirty && draft" class="generated-indicator" title="内容与当前节点一致"><Check :size="13" /> 已同步</span>
      </div>
    </template>
  </footer>
</template>
