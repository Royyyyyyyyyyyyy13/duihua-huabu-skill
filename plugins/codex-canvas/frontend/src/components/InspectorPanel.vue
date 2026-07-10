<script setup>
import DOMPurify from "dompurify";
import { marked } from "marked";
import { ArrowRight, Plus, X } from "@lucide/vue";
import { computed } from "vue";

import { TYPE_COLORS, TYPE_LABELS } from "../lib/graph";

const props = defineProps({
  session: { type: Object, required: true },
  node: { type: Object, default: null },
});

const emit = defineEmits(["close", "focus-node", "add-node"]);

const latestNodes = computed(() =>
  [...props.session.nodes]
    .sort((left, right) => String(right.createdAt || "").localeCompare(String(left.createdAt || "")))
    .slice(0, 8),
);

const reconstructedCount = computed(() => props.session.nodes.filter((item) => item.origin === "reconstructed").length);
const detailHtml = computed(() => renderMarkdown(props.node?.detailMarkdown || props.node?.summary || ""));
const evidenceEntries = computed(() => parseEvidence(props.node?.rawText || ""));

function renderMarkdown(value) {
  const clean = DOMPurify.sanitize(marked.parse(String(value || ""), { breaks: true }));
  const template = document.createElement("template");
  template.innerHTML = clean;
  for (const link of template.content.querySelectorAll("a")) {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
  return template.innerHTML;
}

function parseEvidence(raw) {
  const text = String(raw || "").trim();
  if (!text) return [];
  const entries = [];
  let current = null;
  const speakerPattern = /^(用户|助手)(?:（([^）]+)）)?：(.*)$/;
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(speakerPattern);
    if (match) {
      if (current) entries.push(current);
      current = { role: match[1], time: match[2] || "", text: match[3] || "" };
      continue;
    }
    if (!current) current = { role: "记录", time: "", text: "" };
    current.text += `${current.text ? "\n" : ""}${line}`;
  }
  if (current) entries.push(current);
  return entries.filter((entry) => entry.text.trim()).map((entry) => ({ ...entry, html: renderMarkdown(entry.text) }));
}

function originLabel(origin) {
  return { live: "实时", reconstructed: "回溯", imported: "导入" }[origin] || "未知";
}

function confidenceLabel(confidence) {
  return { high: "高可信", medium: "中可信", low: "低可信" }[confidence] || "未标注";
}
</script>

<template>
  <aside class="inspector-panel">
    <template v-if="node">
      <div class="inspector-toolbar">
        <span class="inspector-type" :style="{ '--type-color': TYPE_COLORS[node.type] || TYPE_COLORS.note }">
          {{ TYPE_LABELS[node.type] || "备注" }}
        </span>
        <button class="icon-button" type="button" title="关闭详情" aria-label="关闭详情" @click="emit('close')">
          <X :size="17" />
        </button>
      </div>

      <div class="inspector-scroll">
        <h2>{{ node.title }}</h2>
        <p class="inspector-summary">{{ node.summary }}</p>

        <div class="meta-line">
          <span>{{ originLabel(node.origin) }}</span>
          <span>{{ confidenceLabel(node.confidence) }}</span>
          <span v-if="node.contentQuality === 'fallback'">摘要兜底</span>
        </div>

        <section class="inspector-section">
          <h3>结构化详情</h3>
          <div class="markdown-content" v-html="detailHtml"></div>
        </section>

        <section v-if="node.tags?.length" class="inspector-section">
          <h3>标签</h3>
          <div class="chip-list">
            <span v-for="tag in node.tags" :key="tag" class="info-chip">{{ tag }}</span>
          </div>
        </section>

        <section v-if="node.relatedFiles?.length" class="inspector-section">
          <h3>相关文件</h3>
          <div class="file-list">
            <code v-for="file in node.relatedFiles" :key="file">{{ file }}</code>
          </div>
        </section>

        <section v-if="node.evidenceRefs?.length" class="inspector-section">
          <h3>证据来源</h3>
          <div class="file-list">
            <code v-for="reference in node.evidenceRefs" :key="reference">{{ reference }}</code>
          </div>
        </section>

        <details v-if="evidenceEntries.length" class="evidence-section">
          <summary>相关对话片段</summary>
          <div class="evidence-timeline">
            <article v-for="(entry, index) in evidenceEntries" :key="`${entry.role}-${index}`" class="evidence-entry">
              <div class="evidence-meta">
                <strong>{{ entry.role }}</strong>
                <time v-if="entry.time">{{ entry.time }}</time>
              </div>
              <div class="markdown-content evidence-copy" v-html="entry.html"></div>
            </article>
          </div>
        </details>
      </div>

      <div class="inspector-actionbar">
        <button class="primary-command" type="button" @click="emit('add-node', node.id)">
          <Plus :size="16" />
          加入手动组装
        </button>
      </div>
    </template>

    <template v-else>
      <div class="overview-header">
        <p class="section-eyebrow">当前会话</p>
        <h2>画布总览</h2>
      </div>
      <div class="overview-stats">
        <div><strong>{{ session.nodes.length }}</strong><span>检查点</span></div>
        <div><strong>{{ session.edges.length }}</strong><span>关系</span></div>
        <div><strong>{{ reconstructedCount }}</strong><span>回溯</span></div>
      </div>
      <section class="latest-section">
        <h3>最近检查点</h3>
        <button
          v-for="item in latestNodes"
          :key="item.id"
          class="latest-row"
          type="button"
          @click="emit('focus-node', item.id)"
        >
          <span class="latest-type" :style="{ '--type-color': TYPE_COLORS[item.type] || TYPE_COLORS.note }"></span>
          <span class="latest-copy"><strong>{{ item.title }}</strong><small>{{ TYPE_LABELS[item.type] || "备注" }}</small></span>
          <ArrowRight :size="15" />
        </button>
      </section>
    </template>
  </aside>
</template>
