<template>
  <web-view v-if="url" :src="url" />
</template>

<script>
import { getScannedHttpUrl } from '../../utils/scanned-url.mjs'

export default {
  data() {
    return { url: '' }
  },
  onLoad(options) {
    const value = decodeURIComponent((options && options.url) || '')
    this.url = getScannedHttpUrl(value)
    if (!this.url) {
      uni.showToast({ title: '网址无效', icon: 'none' })
    }
  },
}
</script>
