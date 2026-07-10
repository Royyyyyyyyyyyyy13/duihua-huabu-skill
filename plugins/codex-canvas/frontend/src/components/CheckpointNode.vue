<script setup>
import { Handle, Position } from "@vue-flow/core";

import { TYPE_COLORS, TYPE_LABELS } from "../lib/graph";

defineProps({
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
});
</script>

<template>
  <article
    class="checkpoint-node"
    :class="{
      'is-selected': selected,
      'is-archived': data.node.status === 'archived',
      'is-search-match': data.searchMatch,
      'is-search-dimmed': data.searchActive && !data.searchMatch,
    }"
    :style="{ '--node-accent': TYPE_COLORS[data.node.type] || TYPE_COLORS.note }"
  >
    <Handle id="target" type="target" :position="Position.Left" class="checkpoint-handle checkpoint-handle-in" />
    <Handle id="source" type="source" :position="Position.Right" class="checkpoint-handle checkpoint-handle-out" />

    <div class="node-topline">
      <span class="node-type">{{ TYPE_LABELS[data.node.type] || "备注" }}</span>
      <span
        class="quality-dot"
        :class="`quality-${data.node.contentQuality || 'fallback'}`"
        :title="data.node.contentQuality === 'full' ? '结构化内容完整' : '当前节点使用摘要兜底'"
      ></span>
    </div>
    <h3>{{ data.node.title || "未命名检查点" }}</h3>
    <p>{{ data.node.summary || "该阶段暂时只有标题。" }}</p>
    <div class="node-footer">
      <span v-for="tag in (data.node.tags || []).slice(0, 2)" :key="tag" class="node-tag">{{ tag }}</span>
      <span v-if="(data.node.tags || []).length > 2" class="node-tag node-tag-more">+{{ data.node.tags.length - 2 }}</span>
    </div>
  </article>
</template>
