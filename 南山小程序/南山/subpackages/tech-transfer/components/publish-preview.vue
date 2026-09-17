<template>
  <view v-if="visible" class="mask" @click="$emit('back')">
    <view class="sheet" @click.stop>
      <text class="title">发布预览</text>
      <scroll-view scroll-y class="body">
        <view v-for="item in items" v-if="item.value" :key="item.label" class="row">
          <text class="label">{{ item.label }}</text><text class="value">{{ item.value }}</text>
        </view>
      </scroll-view>
      <view class="actions"><button class="secondary" @click="$emit('back')">返回编辑</button><button class="primary" :loading="submitting" @click="$emit('confirm')">确认提交</button></view>
    </view>
  </view>
</template>
<script>
export default { props: { visible: Boolean, items: { type: Array, default: () => [] }, submitting: Boolean } }
</script>
<style scoped>
.mask{position:fixed;inset:0;z-index:1000;background:rgba(20,31,50,.45);display:flex;align-items:flex-end;justify-content:center}.sheet{width:100%;max-width:414px;max-height:82vh;background:#fff;border-radius:28rpx 28rpx 0 0;padding:32rpx;box-sizing:border-box}.title{display:block;font-size:34rpx;font-weight:600;color:#17233d;margin-bottom:20rpx}.body{max-height:54vh}.row{padding:18rpx 0;border-bottom:1rpx solid #edf1f5}.label{display:block;font-size:24rpx;color:#7a879a;margin-bottom:8rpx}.value{display:block;font-size:28rpx;color:#26364d;line-height:1.55;white-space:pre-wrap;word-break:break-word}.actions{display:flex;gap:18rpx;padding-top:24rpx}.actions button{flex:1;border-radius:12rpx;font-size:29rpx}.secondary{color:#2b73f8!important;background:#fff!important;border:1rpx solid #2b73f8!important}.primary{background:#2b73f8!important;color:#fff!important}
</style>
