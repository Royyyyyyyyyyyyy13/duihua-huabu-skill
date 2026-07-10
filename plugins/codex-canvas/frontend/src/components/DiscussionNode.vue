<script setup>
import { Handle, Position } from "@vue-flow/core";
import { RefreshCw } from "@lucide/vue";

const emit = defineEmits(["reset-auto"]);

defineProps({
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
});
</script>

<template>
  <article class="checkpoint-node discussion-node" :class="{ 'is-selected': selected }">
    <Handle id="target" type="target" :position="Position.Left" class="checkpoint-handle checkpoint-handle-in" />
    <div class="node-topline">
      <span class="node-type discussion-type">
        <span class="discussion-pulse" aria-hidden="true"></span>
        讨论中
      </span>
      <span class="discussion-source-count" :title="data.mode === 'auto' ? '自动跟随当前主线末端' : '手动指定当前来源'">
        {{ data.anchorCount }} 个来源
      </span>
    </div>
    <h3>当前讨论中</h3>
    <p>这一阶段仍在推进，完成后会沉淀为新的 checkpoint。</p>
    <div class="node-footer">
      <span class="node-tag">{{ data.mode === "auto" ? "自动跟随" : "手动来源" }}</span>
      <button
        v-if="data.mode === 'manual'"
        class="discussion-auto-button nodrag nopan"
        type="button"
        title="恢复自动跟随"
        aria-label="恢复自动跟随"
        @click.stop="emit('reset-auto')"
      >
        <RefreshCw :size="13" />
      </button>
    </div>
  </article>
</template>
