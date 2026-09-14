<template>
  <web-view v-if="url" :src="url" />
</template>

<script>
export default {
  data() {
    return { url: '' }
  },
  onLoad(options) {
    try {
      const value = decodeURIComponent((options && options.url) || '')
      const parsed = new URL(value)
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') this.url = parsed.href
    } catch (e) {
      uni.showToast({ title: '网址无效', icon: 'none' })
    }
  },
}
</script>
