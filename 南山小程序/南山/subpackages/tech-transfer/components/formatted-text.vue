<template>
  <text
    v-if="mode === 'preview' && previewText"
    :class="['ft-preview', { 'ft-indent': indent, 'ft-muted': muted }, textClass]"
    :style="{ '-webkit-line-clamp': lines }"
  >{{ previewText }}</text>
  <view v-else-if="paragraphs.length" :class="['ft-paragraphs', { 'ft-list': mode === 'list' }]">
    <view
      v-for="(para, idx) in paragraphs"
      :key="idx"
      :class="['ft-paragraph', { 'ft-indent': indent && mode !== 'list', 'ft-muted': muted, 'ft-list-row': mode === 'list' }, textClass]"
    >
      <HttpLinkText v-if="linkify" :text="para" @open-link="$emit('open-link', $event)" />
      <text v-else>{{ para }}</text>
    </view>
  </view>
</template>

<script>
import { formatPreviewText, splitParagraphs } from '../utils/paragraph-text.mjs'
import HttpLinkText from './http-link-text.vue'

export default {
  name: 'FormattedText',
  components: { HttpLinkText },
  emits: ['open-link'],
  options: {
    virtualHost: true,
    styleIsolation: 'shared',
  },
  props: {
    text: {
      type: [String, Number],
      default: '',
    },
    mode: {
      type: String,
      default: 'paragraphs',
    },
    indent: {
      type: Boolean,
      default: true,
    },
    muted: {
      type: Boolean,
      default: false,
    },
    linkify: {
      type: Boolean,
      default: false,
    },
    lines: {
      type: Number,
      default: 2,
    },
    textClass: {
      type: String,
      default: '',
    },
  },
  computed: {
    paragraphs() {
      if (this.mode === 'preview') return []
      return splitParagraphs(this.text)
    },
    previewText() {
      if (this.mode !== 'preview') return ''
      return formatPreviewText(this.text)
    },
  },
}
</script>

<style scoped>
.ft-paragraph {
  display: block;
  font-size: 26rpx;
  color: #555555;
  line-height: 1.8;
  text-align: justify;
  word-break: break-word;
  overflow-wrap: break-word;
  margin-bottom: 14rpx;
}

.ft-paragraph:last-child {
  margin-bottom: 0;
}

.ft-preview {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 26rpx;
  color: #4a5568;
  line-height: 1.75;
  text-align: justify;
  word-break: break-word;
}

.ft-indent {
  text-indent: 2em;
}

.ft-muted {
  color: #666666;
}

.ft-list {
  padding: 4rpx 20rpx;
  border: 1rpx solid #e6edf5;
  border-radius: 12rpx;
  background: #f6f9fc;
}

.ft-list-row {
  position: relative;
  margin-bottom: 0;
  padding: 14rpx 0 14rpx 24rpx;
  color: #405168;
  text-align: left;
}

.ft-list-row + .ft-list-row {
  border-top: 1rpx solid #e6edf5;
}

.ft-list-row::before {
  content: '';
  position: absolute;
  top: 33rpx;
  left: 2rpx;
  width: 8rpx;
  height: 8rpx;
  border-radius: 50%;
  background: #2b73f8;
}
</style>
