<template>
  <view class="page">
    <!-- 加载中 -->
    <view v-if="loading" class="state-box">
      <text class="state-text">加载中...</text>
    </view>

    <!-- 不存在 -->
    <view v-else-if="!detail" class="state-box">
      <text class="state-text">成果不存在或未发布</text>
      <button class="back-btn" size="mini" @click="goBack">返回列表</button>
    </view>

    <!-- 详情 -->
    <view v-else class="detail-wrap">
      <!-- 标题区 -->
      <view class="header-card">
        <text class="title">{{ detail.title }}</text>
        <view class="header-meta">
          <text v-if="detail.categoryName" class="badge">{{ detail.categoryName }}</text>
          <text v-if="maturityText" class="maturity-tag">{{ maturityText }}</text>
        </view>
      </view>

      <!-- 来源 -->
      <view class="info-card">
        <view class="info-row">
          <text class="info-label">来源机构</text>
          <text class="info-value">{{ detail.sourceOrgName || '—' }}</text>
        </view>
        <view v-if="detail.publishedAt" class="info-row">
          <text class="info-label">发布时间</text>
          <text class="info-value">{{ detail.publishedAt }}</text>
        </view>
        <view class="info-row">
          <text class="info-label">浏览次数</text>
          <text class="info-value">{{ detail.viewCount || 0 }}</text>
        </view>
      </view>

      <!-- 技术简介 -->
      <view class="section-card">
        <text class="section-title">技术简介</text>
        <text class="section-text">{{ detail.techIntro || '—' }}</text>
      </view>

      <!-- 技术路线 -->
      <view v-if="detail.techRoute" class="section-card">
        <text class="section-title">技术路线</text>
        <text class="section-text">{{ detail.techRoute }}</text>
      </view>

      <!-- 应用领域 -->
      <view v-if="detail.applicationFields && detail.applicationFields.length" class="section-card">
        <text class="section-title">应用领域</text>
        <view class="field-tags">
          <text v-for="(field, idx) in detail.applicationFields" :key="idx" class="field-tag">{{ field }}</text>
        </view>
      </view>

      <!-- 创新点（结构化分组：技术创新点/技术成熟度/项目支持/可应用领域等） -->
      <view v-for="(group, gIdx) in innovationGroups" :key="'g' + gIdx" class="section-card">
        <text class="section-title">{{ group.title }}</text>
        <view v-for="(line, idx) in group.lines" :key="idx" class="point-item">
          <text class="point-index">{{ idx + 1 }}</text>
          <text class="point-text">{{ line }}</text>
        </view>
      </view>

      <!-- 完成人 -->
      <view v-if="detail.inventors && detail.inventors.length" class="section-card">
        <text class="section-title">完成人</text>
        <view v-for="(inv, idx) in detail.inventors" :key="idx" class="inventor-row">
          <text class="inventor-name">{{ inv.name }}</text>
          <text class="inventor-org">{{ inv.orgName || '' }}</text>
        </view>
      </view>

      <!-- 报价 -->
      <view class="section-card">
        <text class="section-title">期望报价</text>
        <view class="price-box">
          <text class="price-mode">{{ formatPricingMode(detail.pricingMode) }}</text>
          <text v-if="detail.priceMinWan" class="price-amount">
            {{ detail.priceMinWan }}{{ detail.priceMaxWan ? ' – ' + detail.priceMaxWan : '' }} 万
          </text>
          <text v-else class="price-amount price-negotiable">面议</text>
        </view>
      </view>

      <!-- 联系方式 -->
      <view v-if="detail.contactName" class="section-card">
        <text class="section-title">联系方式</text>
        <view class="info-row">
          <text class="info-label">联系人</text>
          <text class="info-value">{{ detail.contactName }}</text>
        </view>
        <view v-if="detail.contactTitle" class="info-row">
          <text class="info-label">职务</text>
          <text class="info-value">{{ detail.contactTitle }}</text>
        </view>
        <view v-if="detail.contactPhone" class="info-row">
          <text class="info-label">电话</text>
          <text class="info-value">{{ detail.contactPhone }}</text>
        </view>
        <view v-if="detail.contactEmail" class="info-row">
          <text class="info-label">邮箱</text>
          <text class="info-value">{{ detail.contactEmail }}</text>
        </view>
      </view>
    </view>

    <!-- 底部操作区：我要对接（与需求侧 dock-detail 同一对接流程） -->
    <view v-if="detail" class="dock-bar">
      <button class="dock-btn" @click="onProposeDock">我要对接</button>
    </view>

    <!-- 错误 -->
    <view v-if="error" class="state-box">
      <text class="state-text">加载失败</text>
      <text class="state-sub">{{ error }}</text>
      <button class="back-btn" size="mini" @click="loadDetail">重试</button>
    </view>
  </view>
</template>

<script>
import { getAchievementDetail } from '../../api/achievement.js'
import { formatMaturityLabel } from '../../api/achievement-dock-card.mjs'
import { ensureLoginForDock } from '../../api/user.js'
import HostBridge from '../../../../host/host-bridge.js'

const PRICING_MODE_LABELS = {
  'negotiable': '面议',
  'license': '许可',
  'transfer': '转让',
  'cooperation': '合作',
}

export default {
  data() {
    return {
      achId: null,
      detail: null,
      loading: true,
      error: '',
    }
  },
  computed: {
    maturityText() {
      const d = this.detail || {}
      const text = formatMaturityLabel(d.maturityLevel, d.maturityDesc)
      return text === '未填写' ? '' : text
    },
    // innovationPoints 存在两种形态：
    // 导入数据 [{title, content(\n 分行)}]，API 自建数据 [string]。
    // 归一化为 [{title, lines}] 分组渲染。
    innovationGroups() {
      const list = (this.detail && this.detail.innovationPoints) || []
      if (!Array.isArray(list)) return []
      const groups = []
      let strGroup = null
      for (const item of list) {
        if (item && typeof item === 'object') {
          const lines = String(item.content || '')
            .split('\n')
            .map((s) => s.trim())
            .filter(Boolean)
          const title = String(item.title || '').trim() || '技术创新点'
          if (lines.length) groups.push({ title, lines })
        } else if (item !== null && item !== undefined && String(item).trim()) {
          if (!strGroup) {
            strGroup = { title: '技术创新点', lines: [] }
            groups.push(strGroup)
          }
          strGroup.lines.push(String(item).trim())
        }
      }
      return groups
    },
  },
  onLoad(options) {
    this.achId = parseInt(options.id, 10)
    this.loadDetail()
  },
  methods: {
    async loadDetail() {
      if (!this.achId) {
        this.loading = false
        this.error = '缺少成果 ID'
        return
      }
      this.loading = true
      this.error = ''
      try {
        const data = await getAchievementDetail(this.achId)
        this.detail = data
      } catch (e) {
        console.error('[achievement-detail] loadDetail failed:', e)
        this.error = e.message || '请求失败'
      } finally {
        this.loading = false
      }
    },
    formatPricingMode(mode) {
      return PRICING_MODE_LABELS[mode] || '面议'
    },
    onProposeDock() {
      if (!ensureLoginForDock()) return
      if (!this.achId) return
      HostBridge.navigate('pages/dock-detail/dock-detail', { type: 'result', id: this.achId })
    },
    goBack() {
      uni.navigateBack()
    },
  },
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f5f6f8;
  padding-bottom: calc(140rpx + env(safe-area-inset-bottom));
}

.dock-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  background: #ffffff;
  border-top: 1rpx solid #e8ecf2;
  padding: 16rpx 24rpx calc(16rpx + env(safe-area-inset-bottom));
  z-index: 100;
}

.dock-btn {
  background: #2b73f8 !important;
  color: #ffffff !important;
  border-radius: 12rpx;
  font-size: 32rpx;
  font-weight: 600;
  height: 88rpx;
  line-height: 88rpx;
}

.state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 120rpx 40rpx;
}

.state-text {
  font-size: 30rpx;
  color: #666;
}

.state-sub {
  font-size: 24rpx;
  color: #bbb;
  margin-top: 12rpx;
}

.back-btn {
  margin-top: 24rpx;
  background: #2b73f8 !important;
  color: #fff !important;
}

.detail-wrap {
  padding: 24rpx;
}

.header-card {
  background: #fff;
  border-radius: 16rpx;
  padding: 32rpx;
  margin-bottom: 24rpx;
}

.title {
  display: block;
  font-size: 36rpx;
  font-weight: 700;
  color: #1a1a1a;
  line-height: 1.4;
  margin-bottom: 20rpx;
}

.header-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}

.badge {
  font-size: 24rpx;
  color: #2b73f8;
  background: rgba(43, 115, 248, 0.1);
  padding: 6rpx 16rpx;
  border-radius: 8rpx;
}

.maturity-tag {
  font-size: 24rpx;
  color: #0f9d58;
  background: rgba(15, 157, 88, 0.08);
  padding: 6rpx 16rpx;
  border-radius: 8rpx;
}

.info-card,
.section-card {
  background: #fff;
  border-radius: 16rpx;
  padding: 32rpx;
  margin-bottom: 24rpx;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16rpx 0;
  border-bottom: 1rpx solid #f0f0f0;
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  font-size: 28rpx;
  color: #999;
}

.info-value {
  font-size: 28rpx;
  color: #333;
}

.section-title {
  display: block;
  font-size: 30rpx;
  font-weight: 600;
  color: #1a1a1a;
  margin-bottom: 20rpx;
}

.section-text {
  display: block;
  font-size: 28rpx;
  color: #555;
  line-height: 1.6;
}

.field-tags {
  display: flex;
  flex-wrap: wrap;
}

.field-tag {
  font-size: 24rpx;
  color: #666;
  background: #f5f6f8;
  padding: 8rpx 20rpx;
  border-radius: 24rpx;
  margin-right: 12rpx;
  margin-bottom: 12rpx;
}

.point-item {
  display: flex;
  align-items: flex-start;
  margin-bottom: 16rpx;
}

.point-index {
  flex-shrink: 0;
  width: 40rpx;
  height: 40rpx;
  line-height: 40rpx;
  text-align: center;
  font-size: 22rpx;
  color: #2b73f8;
  background: rgba(43, 115, 248, 0.1);
  border-radius: 50%;
  margin-right: 16rpx;
}

.point-text {
  flex: 1;
  font-size: 28rpx;
  color: #555;
  line-height: 1.6;
}

.inventor-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16rpx 0;
  border-bottom: 1rpx solid #f0f0f0;
}

.inventor-row:last-child {
  border-bottom: none;
}

.inventor-name {
  font-size: 28rpx;
  color: #333;
  font-weight: 500;
}

.inventor-org {
  font-size: 26rpx;
  color: #999;
}

.price-box {
  display: flex;
  align-items: center;
  gap: 20rpx;
}

.price-mode {
  font-size: 26rpx;
  color: #a67c52;
  background: #fff8f0;
  padding: 8rpx 20rpx;
  border-radius: 8rpx;
}

.price-amount {
  font-size: 32rpx;
  color: #e67e22;
  font-weight: 700;
}

.price-negotiable {
  font-size: 28rpx;
  font-weight: 500;
}
</style>
