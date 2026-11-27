<template>
  <view>
    <template v-for="(segment, index) in segments" :key="index">
      <template v-if="segment.url">
        <!-- #ifdef H5 -->
        <a class="inline-link" :href="segment.url" target="_blank" rel="noopener noreferrer">{{ segment.text }}</a>
        <!-- #endif -->
        <!-- #ifndef H5 -->
        <text class="inline-link" @click="$emit('open-link', segment)">{{ segment.text }}</text>
        <!-- #endif -->
      </template>
      <text v-else>{{ segment.text }}</text>
    </template>
  </view>
</template>

<script>
import { splitHttpLinkText } from '../utils/http-link-text.mjs'

export default {
  props: { text: { type: String, required: true } },
  emits: ['open-link'],
  computed: {
    segments() {
      return splitHttpLinkText(this.text)
    },
  },
}
</script>

<style scoped>
.inline-link {
  color: #2b73f8;
  text-decoration: underline;
}
</style>
