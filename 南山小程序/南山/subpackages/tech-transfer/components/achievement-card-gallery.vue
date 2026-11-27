<template>
  <view v-if="slides.length" class="card-gallery" @click.stop>
    <swiper v-if="slides.length > 1" class="gallery-frame" :current="activeIndex" circular @change="onSlideChange">
      <swiper-item v-for="slide in slides" :key="slide.url" class="gallery-slide">
        <image class="gallery-image" :style="imageStyle(slide)" :src="slide.src" :aria-label="title" mode="aspectFit" lazy-load
          @click.stop="openImage(slide)" @load="onImageLoad(slide, $event)" @error="onImageError(slide)" />
      </swiper-item>
    </swiper>
    <image v-else class="gallery-image" :style="imageStyle(slides[0])" :src="slides[0].src" :aria-label="title" mode="aspectFit" lazy-load
      @click.stop="openImage(slides[0])" @load="onImageLoad(slides[0], $event)" @error="onImageError(slides[0])" />

    <view v-if="slides.length > 1" class="gallery-controls">
      <button class="gallery-arrow" aria-label="上一张图片" @click.stop="move(-1)">‹</button>
      <text class="gallery-count">{{ activeIndex + 1 }}/{{ slides.length }}</text>
      <button class="gallery-arrow" aria-label="下一张图片" @click.stop="move(1)">›</button>
    </view>
  </view>
</template>

<script>
import HostBridge from '../../../host/host-bridge.js'
import { resolveMediaUrl } from '../api/media-url.mjs'
import { previewImageUrls } from '../utils/image-preview.mjs'

export default {
  props: {
    images: { type: Array, default: () => [] },
    title: { type: String, default: '' },
  },
  data() {
    return { current: 0, imageErrors: {}, imageRatios: {} }
  },
  computed: {
    resolvedImages() {
      const env = HostBridge.getEnvironment() || {}
      return this.images.map((image) => {
        const url = resolveMediaUrl(image?.url || image?.thumbnailUrl, env)
        return { url, thumbnail: resolveMediaUrl(image?.thumbnailUrl, env) || url }
      }).filter((image) => image.url)
    },
    imageSignature() {
      return JSON.stringify(this.resolvedImages)
    },
    slides() {
      return this.resolvedImages
        .filter((image) => this.imageErrors[image.url] !== 'hidden')
        .map((image) => ({
          ...image,
          src: this.imageErrors[image.url] === 'original' ? image.url : image.thumbnail,
        }))
    },
    activeIndex() {
      return Math.min(this.current, Math.max(0, this.slides.length - 1))
    },
  },
  watch: {
    imageSignature() {
      this.current = 0
      this.imageErrors = {}
      this.imageRatios = {}
    },
  },
  methods: {
    imageStyle(slide) {
      const ratio = this.imageRatios[slide.src]
      if (!ratio) return {}
      const height = Math.max(1, Math.min(360, 640 / ratio))
      return { width: `${Math.max(1, Math.min(640, height * ratio))}rpx`, height: `${height}rpx` }
    },
    onImageLoad(slide, event) {
      const { width, height } = event.detail
      if (width > 0 && height > 0) this.imageRatios[slide.src] = width / height
    },
    onSlideChange(event) {
      this.current = event.detail.current
    },
    move(step) {
      this.current = (this.activeIndex + step + this.slides.length) % this.slides.length
    },
    openImage(slide) {
      previewImageUrls(this.slides.map((image) => image.url), slide.url)
    },
    onImageError(slide) {
      if (this.imageErrors[slide.url] === 'hidden') return
      if (slide.src !== slide.url && this.imageErrors[slide.url] === 'original') return
      this.imageErrors[slide.url] = slide.src === slide.url ? 'hidden' : 'original'
    },
  },
}
</script>

<style scoped>
.card-gallery {
  position: relative;
  margin-bottom: 18rpx;
  border-radius: 16rpx;
  overflow: hidden;
}

.gallery-frame,
.gallery-image {
  width: 100%;
  height: 360rpx;
}

.gallery-image {
  display: block;
  max-width: 100%;
  margin: 0 auto;
  border-radius: 14rpx;
  overflow: hidden;
}

.gallery-slide {
  display: flex;
  align-items: center;
  justify-content: center;
}

.gallery-controls {
  position: absolute;
  right: 12rpx;
  bottom: 12rpx;
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 0 6rpx;
  border-radius: 24rpx;
  background: rgba(15, 29, 48, 0.78);
  color: #fff;
}

.gallery-count {
  font-size: 22rpx;
  font-variant-numeric: tabular-nums;
}

.gallery-arrow {
  width: 44rpx;
  height: 44rpx;
  margin: 0;
  padding: 0;
  background: transparent;
  color: inherit;
  font-size: 29rpx;
  line-height: 42rpx;
}

.gallery-arrow::after {
  border: 0;
}
</style>
