<template>
  <view class="dev-home">
    <view class="dev-header">
      <text class="dev-title">南山科转通 · 本地开发宿主</text>
      <text class="dev-env">APP_ENV=local · HOST_MODE=local · AUTH_PROVIDER=mock</text>
    </view>

    <view class="dev-section">
      <view class="dev-card" @tap="goTo('/subpackages/tech-transfer/pages/mine/mine')">
        <text class="card-title">我的</text>
        <text class="card-desc">身份引导 · 个人资料 · 登录/注销</text>
      </view>

      <view class="dev-card" @tap="goTo('/pages/index/index')">
        <text class="card-title">首页（旧）</text>
        <text class="card-desc">原演示首页，待迁移至分包</text>
      </view>

      <view class="dev-card" @tap="goTo('/pages/capital-list/capital-list')">
        <text class="card-title">资本对接（旧）</text>
        <text class="card-desc">原资本列表页，待迁移至分包</text>
      </view>
    </view>

    <view class="dev-section">
      <text class="section-title">后端状态</text>
      <view class="dev-card">
        <text class="card-desc">API: http://127.0.0.1:8787/api/tech-transfer/v1</text>
        <text class="card-desc" :class="{ ok: healthOk, fail: !healthOk }">
          {{ healthOk ? '✓ 后端连接正常' : '✗ 后端未响应' }}
        </text>
      </view>
    </view>
  </view>
</template>

<script>
export default {
  data() {
    return {
      healthOk: false,
    }
  },
  onShow() {
    this.checkHealth()
  },
  methods: {
    goTo(url) {
      uni.navigateTo({ url, fail: () => {
        uni.switchTab({ url, fail: () => {
          uni.showToast({ title: '页面不存在: ' + url, icon: 'none' })
        }})
      }})
    },
    async checkHealth() {
      try {
        const res = await new Promise((resolve, reject) => {
          uni.request({
            url: 'http://127.0.0.1:8787/api/health',
            success: resolve,
            fail: reject,
          })
        })
        this.healthOk = res.statusCode === 200
      } catch (e) {
        this.healthOk = false
      }
    },
  },
}
</script>

<style scoped>
.dev-home {
  min-height: 100vh;
  background: #F5F6F8;
  padding: 24rpx;
}
.dev-header {
  text-align: center;
  margin-bottom: 40rpx;
  padding-top: 40rpx;
}
.dev-title {
  display: block;
  font-size: 36rpx;
  font-weight: bold;
  color: #333;
  margin-bottom: 12rpx;
}
.dev-env {
  font-size: 22rpx;
  color: #999;
}
.dev-section {
  margin-bottom: 32rpx;
}
.section-title {
  display: block;
  font-size: 28rpx;
  color: #666;
  margin-bottom: 16rpx;
  padding-left: 8rpx;
}
.dev-card {
  background: #fff;
  border-radius: 16rpx;
  padding: 32rpx;
  margin-bottom: 16rpx;
}
.card-title {
  display: block;
  font-size: 32rpx;
  font-weight: 500;
  color: #333;
  margin-bottom: 8rpx;
}
.card-desc {
  display: block;
  font-size: 24rpx;
  color: #999;
}
.ok { color: #4caf50 !important; }
.fail { color: #f44336 !important; }
</style>
