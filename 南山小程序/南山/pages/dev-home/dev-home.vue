<template>
  <view class="dev-home">
    <view class="dev-header">
      <text class="dev-title">南山科转通 · 本地开发宿主</text>
      <text class="dev-env">HOST_MODE=local · AUTH_PROVIDER=mock</text>
    </view>

    <view class="dev-cards">
      <view class="dev-card" @tap="goTo('/subpackages/tech-transfer/pages/home/home')">
        <view class="card-icon"><text class="card-icon-text">首</text></view>
        <text class="card-title">首页</text>
        <text class="card-desc">成果 · 需求 · 资本对接</text>
      </view>

      <view class="dev-card" @tap="goTo('/subpackages/tech-transfer/pages/ai-match/ai-match')">
        <view class="card-icon"><text class="card-icon-text">AI</text></view>
        <text class="card-title">AI 匹配</text>
        <text class="card-desc">需求 → 成果匹配任务</text>
      </view>

      <view class="dev-card" @tap="goTo('/subpackages/tech-transfer/pages/mine/mine')">
        <view class="card-icon"><text class="card-icon-text">我</text></view>
        <text class="card-title">我的</text>
        <text class="card-desc">身份引导 · 个人资料</text>
      </view>
    </view>

    <view class="dev-footer">
      <text class="footer-text" :class="{ ok: healthOk, fail: !healthOk }">
        {{ healthOk ? '✓ 后端正常' : '✗ 后端未响应' }} · http://127.0.0.1:8787
      </text>
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
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0 32rpx;
}
.dev-header {
  text-align: center;
  margin-top: 120rpx;
  margin-bottom: 80rpx;
}
.dev-title {
  display: block;
  font-size: 40rpx;
  font-weight: bold;
  color: #333;
  margin-bottom: 16rpx;
}
.dev-env {
  font-size: 22rpx;
  color: #999;
}
.dev-cards {
  width: 100%;
  display: flex;
  flex-direction: row;
  justify-content: space-between;
}
.dev-card {
  flex: 1;
  background: #fff;
  border-radius: 20rpx;
  padding: 40rpx 20rpx;
  margin: 0 8rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.card-icon {
  width: 88rpx;
  height: 88rpx;
  border-radius: 50%;
  background: #2B73F8;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20rpx;
}
.card-icon-text {
  font-size: 32rpx;
  color: #fff;
  font-weight: bold;
}
.card-title {
  display: block;
  font-size: 30rpx;
  font-weight: 500;
  color: #333;
  margin-bottom: 8rpx;
}
.card-desc {
  display: block;
  font-size: 20rpx;
  color: #999;
  text-align: center;
}
.dev-footer {
  margin-top: auto;
  margin-bottom: 60rpx;
  padding-bottom: env(safe-area-inset-bottom);
}
.footer-text {
  font-size: 22rpx;
  color: #999;
}
.ok { color: #4caf50; }
.fail { color: #f44336; }
</style>
