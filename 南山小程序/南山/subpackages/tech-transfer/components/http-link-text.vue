<template>
  <view class="http-link-text">
    <template v-for="(segment, index) in segments" :key="index">
      <template v-if="segment.url">
        <!-- #ifdef H5 -->
        <a class="inline-link" :href="segment.url" target="_blank" rel="noopener noreferrer">{{ segment.text }}</a>
        <!-- #endif -->
        <!-- #ifndef H5 -->
        <text class="inline-link" @click="$emit('open-link', segment)">{{ segment.text }}</text>
        <!-- #endif -->
        <button class="link-copy" @click.stop="copyLink(segment.url)">复制</button>
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
  methods: {
    async copyLink(url) {
      // #ifdef H5
      if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(url)
          uni.showToast({ title: '链接已复制', icon: 'none' })
          return
        } catch {
          // 浏览器限制剪贴板权限时，尝试 uni-app 的兼容实现。
        }
      }
      // #endif
      uni.setClipboardData({
        data: url,
        showToast: false,
        success: () => uni.showToast({ title: '链接已复制', icon: 'none' }),
        fail: () => uni.showToast({ title: '复制失败，请重试', icon: 'none' }),
      })
    },
  },
}
</script>

<style scoped>
.http-link-text {
  display: inline;
}

.inline-link {
  color: #2b73f8;
  text-decoration: underline;
}

.link-copy {
  display: inline-block;
  box-sizing: border-box;
  min-height: 48rpx;
  margin: 0 0 0 12rpx;
  padding: 0 14rpx;
  border-radius: 8rpx;
  background: #edf4ff;
  color: #205fc6;
  font-size: 22rpx;
  line-height: 48rpx;
  text-indent: 0;
  vertical-align: middle;
  white-space: nowrap;
}

.link-copy::after {
  border: 0;
}
</style>
