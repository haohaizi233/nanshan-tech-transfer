<template>
  <view v-if="visible" class="pdf-overlay" @touchmove.stop>
    <view class="pdf-bar">
      <text class="pdf-bar-btn" @click="onClose">关闭</text>
      <text class="pdf-bar-title">{{ barTitle }}</text>
      <view class="pdf-zoom">
        <text class="pdf-bar-btn" @click="zoomOut">－</text>
        <text class="pdf-zoom-label">{{ zoomLabel }}</text>
        <text class="pdf-bar-btn" @click="zoomIn">＋</text>
      </view>
    </view>

    <scroll-view
      class="pdf-stage"
      scroll-y
      scroll-x
      :scroll-top="scrollTop"
      @scrolltolower="loadMore"
      @touchstart="onTouchStart"
      @touchmove="onTouchMove"
      @touchend="onTouchEnd"
    >
      <view class="pdf-pages" :style="pagesStyle">
        <view v-if="loading && pages.length === 0" class="pdf-state">
          <text class="pdf-state-text">正在加载说明书</text>
        </view>
        <view v-else-if="error && pages.length === 0" class="pdf-state">
          <text class="pdf-state-text">无法预览说明书</text>
          <text class="pdf-state-sub">{{ error }}</text>
          <text class="pdf-retry" @click="start">重试</text>
        </view>
        <block v-else>
          <view v-for="item in pages" :key="item.page" class="pdf-page-wrap">
            <image
              v-if="item.src"
              class="pdf-page"
              :src="item.src"
              mode="widthFix"
              :show-menu-by-longpress="false"
            />
            <view v-else-if="item.error" class="pdf-page-fallback" @click="loadPage(item.page)">
              <text class="pdf-state-text">第 {{ item.page }} 页加载失败</text>
              <text class="pdf-retry">点击重试</text>
            </view>
            <view v-else class="pdf-page-fallback">
              <text class="pdf-state-text">第 {{ item.page }} 页加载中</text>
            </view>
          </view>
          <view v-if="pages.length < pageCount" class="pdf-more">
            <text class="pdf-state-sub">下滑加载后续页面</text>
          </view>
        </block>
      </view>
    </scroll-view>
  </view>
</template>

<script>
import { getPatentPdfPagesMeta, loadPatentPdfPage } from '../api/patent.js'

const MIN_ZOOM = 1
const MAX_ZOOM = 4
const ZOOM_STEP = 0.25
const INITIAL_PAGES = 2
const MORE_PAGES = 2

export default {
  name: 'PdfPreviewOverlay',
  props: {
    visible: { type: Boolean, default: false },
    publicationNo: { type: String, default: '' },
  },
  data() {
    return {
      loading: false,
      error: '',
      pageCount: 0,
      pages: [],
      zoom: 1,
      scrollTop: 0,
      seq: 0,
      pinching: false,
      pinchStartDist: 0,
      pinchStartZoom: 1,
      loadingMore: false,
    }
  },
  computed: {
    barTitle() {
      if (!this.pageCount) return '说明书'
      const current = this.pages.length
      return `${Math.min(current, this.pageCount)} / ${this.pageCount}`
    },
    zoomLabel() {
      return Math.round(this.zoom * 100) + '%'
    },
    pagesStyle() {
      return { width: this.zoom * 100 + '%' }
    },
  },
  watch: {
    visible(val) {
      if (val) this.start()
      else this.reset()
    },
  },
  methods: {
    onClose() {
      this.$emit('close')
    },
    zoomIn() {
      this.zoom = Math.min(MAX_ZOOM, Math.round((this.zoom + ZOOM_STEP) * 100) / 100)
    },
    zoomOut() {
      this.zoom = Math.max(MIN_ZOOM, Math.round((this.zoom - ZOOM_STEP) * 100) / 100)
    },
    touchDist(a, b) {
      const dx = (a.clientX || a.pageX || 0) - (b.clientX || b.pageX || 0)
      const dy = (a.clientY || a.pageY || 0) - (b.clientY || b.pageY || 0)
      return Math.sqrt(dx * dx + dy * dy)
    },
    onTouchStart(e) {
      const touches = (e && e.touches) || []
      if (touches.length === 2) {
        this.pinching = true
        this.pinchStartDist = this.touchDist(touches[0], touches[1])
        this.pinchStartZoom = this.zoom
      }
    },
    onTouchMove(e) {
      const touches = (e && e.touches) || []
      if (!this.pinching || touches.length !== 2 || !this.pinchStartDist) return
      const dist = this.touchDist(touches[0], touches[1])
      const next = this.pinchStartZoom * (dist / this.pinchStartDist)
      this.zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(next * 20) / 20))
    },
    onTouchEnd(e) {
      const touches = (e && e.touches) || []
      if (touches.length < 2) this.pinching = false
    },
    reset() {
      this.seq += 1
      this.pages.forEach((item) => {
        if (item.src && String(item.src).indexOf('blob:') === 0) {
          try {
            URL.revokeObjectURL(item.src)
          } catch (e) {}
        }
      })
      this.loading = false
      this.error = ''
      this.pageCount = 0
      this.pages = []
      this.zoom = 1
      this.scrollTop = 0
      this.pinching = false
      this.loadingMore = false
    },
    async start() {
      if (!this.publicationNo) {
        this.error = '缺少专利公开号'
        return
      }
      this.reset()
      const seq = this.seq
      this.loading = true
      try {
        const meta = await getPatentPdfPagesMeta(this.publicationNo)
        if (seq !== this.seq) return
        const pageCount = Number((meta && meta.pageCount) || 0)
        if (!pageCount) {
          this.error = '说明书没有可预览的页面'
          return
        }
        this.pageCount = pageCount
        await this.ensurePages(Math.min(INITIAL_PAGES, pageCount), seq)
      } catch (e) {
        if (seq !== this.seq) return
        this.error = (e && e.message) || '加载失败'
      } finally {
        if (seq === this.seq) this.loading = false
      }
    },
    loadMore() {
      if (this.loading || this.loadingMore || this.pages.length >= this.pageCount) return
      this.ensurePages(this.pages.length + MORE_PAGES, this.seq)
    },
    async ensurePages(upto, seq) {
      if (this.loadingMore) return
      const end = Math.min(upto, this.pageCount)
      if (end <= this.pages.length) return
      this.loadingMore = true
      const jobs = []
      for (let page = this.pages.length + 1; page <= end; page++) {
        this.pages.push({ page, src: '', error: false })
        jobs.push(this.loadPage(page, seq))
      }
      try {
        await Promise.all(jobs)
      } finally {
        if (seq === this.seq) this.loadingMore = false
      }
    },
    async loadPage(page, seq) {
      const token = seq == null ? this.seq : seq
      const item = this.pages.find((row) => row.page === page)
      if (!item) return
      item.error = false
      try {
        const src = await loadPatentPdfPage(this.publicationNo, page)
        if (token !== this.seq) {
          if (src && String(src).indexOf('blob:') === 0) {
            try {
              URL.revokeObjectURL(src)
            } catch (e) {}
          }
          return
        }
        item.src = src
      } catch (e) {
        if (token !== this.seq) return
        item.error = true
      }
    },
  },
}
</script>

<style scoped>
.pdf-overlay {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  bottom: 0;
  width: 100%;
  height: 100%;
  z-index: 999;
  background: #111111;
  display: flex;
  flex-direction: column;
}

.pdf-bar {
  flex-shrink: 0;
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  padding: 16rpx 24rpx;
  padding-top: calc(16rpx + env(safe-area-inset-top));
  background: #1b1b1b;
}

.pdf-bar-btn {
  color: #5b9dff;
  font-size: 28rpx;
  min-width: 72rpx;
}

.pdf-bar-title {
  flex: 1;
  text-align: center;
  color: #ffffff;
  font-size: 28rpx;
}

.pdf-zoom {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: flex-end;
  min-width: 200rpx;
}

.pdf-zoom-label {
  color: #dddddd;
  font-size: 24rpx;
  min-width: 80rpx;
  text-align: center;
}

.pdf-stage {
  flex: 1;
  width: 100%;
  height: calc(100% - 100rpx);
  background: #111111;
}

.pdf-pages {
  min-height: 100%;
  box-sizing: border-box;
  padding: 16rpx 12rpx 48rpx;
}

.pdf-page-wrap {
  margin-bottom: 16rpx;
  background: #ffffff;
  border-radius: 8rpx;
  overflow: hidden;
}

.pdf-page {
  width: 100%;
  display: block;
  vertical-align: top;
}

.pdf-page-fallback,
.pdf-state {
  min-height: 320rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48rpx 24rpx;
}

.pdf-state-text {
  color: #eeeeee;
  font-size: 28rpx;
}

.pdf-state-sub {
  margin-top: 12rpx;
  color: #999999;
  font-size: 24rpx;
  text-align: center;
}

.pdf-retry {
  margin-top: 20rpx;
  color: #5b9dff;
  font-size: 26rpx;
}

.pdf-more {
  padding: 12rpx 0 32rpx;
  display: flex;
  justify-content: center;
}
</style>
