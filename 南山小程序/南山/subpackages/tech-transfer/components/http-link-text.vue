<template>
  <view v-if="standaloneLink" class="http-link-card">
    <text v-if="standaloneLink.label" class="http-link-card__label">{{ standaloneLink.label }}</text>
    <view class="http-link-card__row">
      <!-- #ifdef H5 -->
      <a class="inline-link http-link-card__url" :href="standaloneLink.url" target="_blank" rel="noopener noreferrer">{{ standaloneLink.text }}</a>
      <!-- #endif -->
      <!-- #ifndef H5 -->
      <text class="inline-link http-link-card__url" @click="$emit('open-link', standaloneLink)">{{ standaloneLink.text }}</text>
      <!-- #endif -->
      <button class="link-copy" @click.stop="copyLink(standaloneLink.url)">复制</button>
    </view>
  </view>
  <view v-else class="http-link-text">
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
import { parseStandaloneHttpLink, splitHttpLinkText } from '../utils/http-link-text.mjs'

export default {
  options: {
    virtualHost: true,
    styleIsolation: 'shared',
  },
  props: { text: { type: String, required: true } },
  emits: ['open-link'],
  computed: {
    standaloneLink() {
      return parseStandaloneHttpLink(this.text)
    },
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
  word-break: break-all;
  overflow-wrap: anywhere;
}

.http-link-card {
  display: block;
  padding: 16rpx 20rpx;
  border: 1rpx solid #e6edf5;
  border-radius: 12rpx;
  background: #f6f9fc;
  text-align: left;
  text-indent: 0;
}

.http-link-card__label {
  display: block;
  margin-bottom: 6rpx;
  font-size: 22rpx;
  color: #64748b;
  line-height: 1.4;
}

.http-link-card__row {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 16rpx;
}

.http-link-card__url {
  flex: 1;
  min-width: 0;
  font-size: 25rpx;
  line-height: 1.5;
  text-decoration: none;
  word-break: break-all;
}

.link-copy {
  display: inline-block;
  flex-shrink: 0;
  box-sizing: border-box;
  min-height: 44rpx;
  margin: 0 0 0 12rpx;
  padding: 0 16rpx;
  border-radius: 8rpx;
  background: #edf4ff;
  color: #205fc6;
  font-size: 22rpx;
  font-weight: 500;
  line-height: 44rpx;
  text-indent: 0;
  vertical-align: middle;
  white-space: nowrap;
}

.http-link-card__row .link-copy {
  margin-left: 0;
}

.link-copy::after {
  border: 0;
}
</style>
