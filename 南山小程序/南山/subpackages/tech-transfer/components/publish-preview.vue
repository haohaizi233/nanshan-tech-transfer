<template>
  <view v-if="visible" class="mask" @tap="onMaskTap" @touchmove.stop.prevent="noop">
    <view class="sheet" @tap.stop>
      <text class="title">发布预览</text>
      <scroll-view scroll-y class="body" :show-scrollbar="false">
        <view v-for="item in visibleItems" :key="item.label" class="row">
          <text class="label">{{ item.label }}</text>
          <text class="value">{{ item.value }}</text>
        </view>
        <view v-if="previewImages.length" :class="['preview-images', previewImages.length === 1 ? 'preview-images-single' : '']">
          <image
            v-for="(src, index) in previewImages"
            :key="index"
            class="preview-thumb"
            :src="src"
            mode="aspectFill"
            @tap.stop="previewAt(index)"
          />
        </view>
        <view v-if="!visibleItems.length && !previewImages.length" class="empty">暂无可预览内容，请返回检查必填项</view>
      </scroll-view>
      <view class="actions">
        <button class="secondary" hover-class="none" @tap="$emit('back')">返回编辑</button>
        <button class="primary" hover-class="none" :loading="submitting" @tap="$emit('confirm')">确认提交</button>
      </view>
    </view>
  </view>
</template>

<script>
export default {
  options: {
    virtualHost: true,
    styleIsolation: 'shared',
  },
  props: {
    visible: Boolean,
    items: { type: Array, default: () => [] },
    images: { type: Array, default: () => [] },
    submitting: Boolean,
  },
  emits: ['back', 'confirm'],
  computed: {
    visibleItems() {
      return (this.items || []).filter((item) => item && String(item.value || '').trim())
    },
    previewImages() {
      return (this.images || []).map((src) => String(src || '').trim()).filter(Boolean)
    },
  },
  methods: {
    noop() {},
    onMaskTap() {
      if (!this.submitting) this.$emit('back')
    },
    previewAt(index) {
      const urls = this.previewImages
      const current = urls[index]
      if (!current) return
      uni.previewImage({ urls, current })
    },
  },
}
</script>

<style scoped>
.mask {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  bottom: 0;
  width: 100%;
  height: 100%;
  z-index: 1000;
  background: rgba(20, 31, 50, 0.45);
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.sheet {
  width: 100%;
  max-width: 414px;
  max-height: 82vh;
  background: #ffffff;
  border-radius: 28rpx 28rpx 0 0;
  padding: 32rpx 32rpx calc(32rpx + env(safe-area-inset-bottom));
  box-sizing: border-box;
}
.title {
  display: block;
  font-size: 34rpx;
  font-weight: 600;
  color: #17233d;
  margin-bottom: 20rpx;
}
.body {
  height: 560rpx;
}
.row {
  padding: 18rpx 0;
  border-bottom: 1rpx solid #edf1f5;
}
.label {
  display: block;
  font-size: 24rpx;
  color: #7a879a;
  margin-bottom: 8rpx;
}
.value {
  display: block;
  font-size: 28rpx;
  color: #26364d;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
.preview-images {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
  padding: 18rpx 0 8rpx;
}
.preview-images-single {
  justify-content: center;
}
.preview-thumb {
  width: 196rpx;
  height: 148rpx;
  border-radius: 10rpx;
  background: #eef3fa;
}
.preview-images-single .preview-thumb {
  width: 480rpx;
  height: 360rpx;
  max-width: 100%;
}
.empty {
  padding: 48rpx 0;
  text-align: center;
  color: #8b98aa;
  font-size: 26rpx;
}
.actions {
  display: flex;
  flex-direction: row;
  padding-top: 24rpx;
}
.actions button {
  flex: 1;
  margin: 0;
  border-radius: 12rpx;
  font-size: 29rpx;
}
.actions .secondary {
  margin-right: 18rpx;
  color: #2b73f8 !important;
  background: #ffffff !important;
  border: 1rpx solid #2b73f8 !important;
}
.primary {
  background: #2b73f8 !important;
  color: #ffffff !important;
}
</style>
