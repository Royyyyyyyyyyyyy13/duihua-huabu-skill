<script setup>
import { BaseEdge, getSmoothStepPath } from "@vue-flow/core";
import { computed } from "vue";

const props = defineProps({
  id: { type: String, required: true },
  sourceX: { type: Number, required: true },
  sourceY: { type: Number, required: true },
  targetX: { type: Number, required: true },
  targetY: { type: Number, required: true },
  sourcePosition: { type: String, required: true },
  targetPosition: { type: String, required: true },
  markerEnd: { type: String, default: undefined },
  selected: { type: Boolean, default: false },
  data: { type: Object, default: () => ({}) },
});

const path = computed(() =>
  getSmoothStepPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    targetX: props.targetX,
    targetY: props.targetY,
    sourcePosition: props.sourcePosition,
    targetPosition: props.targetPosition,
    borderRadius: 18,
    offset: 28,
  })[0],
);
</script>

<template>
  <BaseEdge
    :id="id"
    :path="path"
    :marker-end="markerEnd"
    :interaction-width="18"
    :class="[
      'conversation-edge',
      data.discussion ? 'discussion-edge' : 'formal-edge',
      selected ? 'is-selected' : '',
    ]"
  />
</template>
