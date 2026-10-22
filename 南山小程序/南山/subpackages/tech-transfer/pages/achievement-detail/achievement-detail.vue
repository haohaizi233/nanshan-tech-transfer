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
        <text v-if="detail.titleEn" class="title-en">{{ detail.titleEn }}</text>
        <view class="header-meta">
          <text v-if="detail.categoryName" class="badge">{{ detail.categoryName }}</text>
          <text v-if="maturityText" class="maturity-tag">{{ maturityText }}</text>
        </view>
      </view>

      <!-- AI 智能评估入口（仅成果所有者可见）：已有评估展示最近结果摘要 + 查看报告/重新评估，
           没有评估时才显示“发起 AI 评估” -->
      <view v-if="showAiEval" class="section-card ai-eval-card">
        <view class="ai-eval-head">
          <text class="section-title ai-eval-title">AI 智能评估</text>
          <text v-if="latestEval && latestEval.ratingLabel" class="ai-eval-rating">{{ latestEval.ratingLabel }}</text>
        </view>
        <view v-if="evalLoading" class="ai-eval-loading">
          <view class="ai-spinner"></view>
          <text class="ai-eval-hint">正在获取评估结果…</text>
        </view>
        <view v-else-if="evalRunning" class="ai-eval-loading">
          <view class="ai-spinner"></view>
          <text class="ai-eval-hint">评估进行中，点击查看进度 →</text>
          <button class="ai-eval-btn ai-eval-btn--ghost" size="mini" @click="onViewRunning">查看进度</button>
        </view>
        <block v-else-if="latestEval">
          <view class="ai-eval-summary">
            <text class="ai-eval-score">{{ latestEval.totalScore }}</text>
            <text class="ai-eval-score-unit">/ 100</text>
            <text v-if="latestEval.createdAt" class="ai-eval-time">评估于 {{ latestEval.createdAt }}</text>
          </view>
          <view class="ai-eval-actions">
            <button class="ai-eval-btn ai-eval-btn--ghost" size="mini" :disabled="evalSubmitting" @click="onStartEval">重新评估</button>
            <button class="ai-eval-btn" size="mini" @click="onViewEval">查看评估报告</button>
          </view>
        </block>
        <block v-else>
          <text class="ai-eval-hint">对成果进行多维智能评估，自动生成综合评分与评价报告</text>
          <view class="ai-eval-actions">
            <button class="ai-eval-btn" size="mini" :disabled="evalSubmitting" @click="onStartEval">{{ evalSubmitting ? '提交中…' : '发起 AI 评估' }}</button>
          </view>
        </block>
      </view>

      <!-- 来源 -->
      <view class="info-card">
        <view class="info-row">
          <text class="info-label">来源机构</text>
          <text class="info-value">{{ detail.sourceOrgName }}</text>
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
      <view v-if="detail.techIntro" class="section-card">
        <text class="section-title">技术简介</text>
        <text class="section-text">{{ detail.techIntro }}</text>
      </view>

      <view v-if="detail.media && detail.media.length" class="section-card">
        <text class="section-title">成果资料</text>
        <view class="media-grid">
          <image v-for="media in detail.media" :key="media.fileId" class="media-image" :src="mediaSrc(media)" mode="aspectFill" />
        </view>
      </view>

      <view v-for="section in dynamicSections" :key="section.code + section.sortOrder" class="section-card">
        <text class="section-title">{{ section.title }}</text>
        <text class="section-text">{{ section.content }}</text>
      </view>

      <view v-if="detail.patents && detail.patents.length" class="section-card">
        <text class="section-title">关联专利</text>
        <view v-for="patent in detail.patents" :key="patent.patentNo" :class="['link-row', { 'link-row-clickable': canOpenPatent(patent) }]" @click="openPatent(patent)">
          <text class="link-text">{{ patent.patentNo }}{{ patent.title ? ' · ' + patent.title : '' }}</text>
          <text v-if="patent.internalDetailAvailable || patent.externalUrl" class="link-arrow">›</text>
        </view>
      </view>

      <view v-if="detail.links && detail.links.length" class="section-card">
        <text class="section-title">相关链接</text>
        <view v-for="link in detail.links" :key="link.url" class="link-row" @click="openLink(link.url)">
          <text class="link-text">{{ link.label }}</text><text class="link-arrow">›</text>
        </view>
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
      <view v-if="hasPricing" class="section-card">
        <text class="section-title">期望报价</text>
        <view class="price-box">
          <text class="price-mode">{{ formatPricingMode(detail.pricingMode) }}</text>
          <text v-if="detail.priceMinWan" class="price-amount">
            {{ detail.priceMinWan }}{{ detail.priceMaxWan ? ' – ' + detail.priceMaxWan : '' }} 万
          </text>
          <text v-else-if="detail.pricingMode === 'negotiable'" class="price-amount price-negotiable">面议</text>
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
import { createEvaluationTask, getEvaluationHistory } from '../../api/ai.js'
import { formatMaturityLabel } from '../../api/achievement-dock-card.mjs'
import { mediaDisplayUrl } from '../../api/media-url.mjs'
import { createPageStateMixin } from '../../api/page-state-cache.mjs'
import HostBridge from '../../../../host/host-bridge.js'
import { AI_FEATURE_ENABLED } from '../../../../config/feature-flags.js'
import { safeNavigateBack } from '../../utils/nav.mjs'

const PRICING_MODE_LABELS = {
  'negotiable': '面议',
  'license': '许可',
  'transfer': '转让',
  'cooperation': '合作',
}

export default {
  mixins: [createPageStateMixin({
    route: 'pages/achievement-detail/achievement-detail',
    groups: [{ name: 'detail', dataClass: 'detail', fields: ['achId', 'detail'] }],
  })],
  data() {
    return {
      achId: null,
      detail: null,
      loading: true,
      error: '',
      // AI 评估入口状态：最近一次评估摘要 / 加载与提交中标记
      aiEnabled: AI_FEATURE_ENABLED,
      latestEval: null,
      evalLoading: false,
      evalSubmitting: false,
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
    dynamicSections() {
      return Array.isArray(this.detail && this.detail.sections)
        ? this.detail.sections.filter((section) => section && section.title && section.content)
        : []
    },
    hasPricing() {
      const d = this.detail || {}
      return d.pricingMode === 'negotiable' || d.priceMinWan != null || d.priceMaxWan != null
    },
    // AI 评估入口仅成果所有者可见（后端发起评估为 owner-only），AI 关闭时整体隐藏
    showAiEval() {
      return this.aiEnabled && !!(this.detail && this.detail.isMine)
    },
  },
  onLoad(options) {
    this.achId = parseInt(options.id, 10)
    this.loading = !this.detail
  },
  onShow() {
    // 每次进入页面只拉一次接口；缓存详情仅用于首屏渲染（不闪烁），不作为跳过刷新的依据
    this.loading = !this.detail
    return this.loadDetail()
  },
  methods: {
    async loadDetail() {
      if (!this.achId) {
        this.loading = false
        this.error = '缺少成果 ID'
        return
      }
      this.loading = !this.detail
      this.error = ''
      try {
        const data = await getAchievementDetail(this.achId)
        this.detail = data
        this.markPageStateFresh('detail')
        // 入口摘要：拉取最近一次 AI 评估（仅所有者可见），已有结果显示总分+等级
        this.loadEvalSummary()
      } catch (e) {
        console.error('[achievement-detail] loadDetail failed:', e)
        if (!this.detail) this.error = e.message || '请求失败'
        else uni.showToast({ title: '网络异常，暂显示已缓存详情', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    formatPricingMode(mode) {
      return PRICING_MODE_LABELS[mode] || ''
    },
    // ── AI 评估入口 ─────────────────────────────────────────
    async loadEvalSummary() {
      if (!this.showAiEval) return
      this.evalLoading = true
      try {
        const data = await getEvaluationHistory(this.achId, 1, 20)
        const list = (data && data.list) || []
        // 列表按时间倒序，首个即最近一次评估
        this.latestEval = list[0] || null
      } catch (e) {
        // 摘要拉取失败不影响详情展示：入口回退为“发起 AI 评估”
        console.error('[achievement-detail] getEvaluationHistory failed:', e)
      } finally {
        this.evalLoading = false
      }
    },
    onViewEval() {
      const ev = this.latestEval
      if (!ev || !ev.taskId) {
        uni.showToast({ title: '暂无可查看的评估报告', icon: 'none' })
        return
      }
      HostBridge.navigate('pages/ai-eval-detail/ai-eval-detail', {
        taskId: ev.taskId,
        achievementId: this.achId,
      })
    },
    onViewRunning() {
      if (this._runningTaskId) {
        uni.navigateTo({
          url: `/subpackages/tech-transfer/pages/ai-eval-detail/ai-eval-detail?taskId=${this._runningTaskId}&achievementId=${this.achId}`
        })
      }
    },
    async onStartEval() {
      if (!this.showAiEval || this.evalSubmitting || !this.achId) return
      this.evalSubmitting = true
      // 检查是否有进行中的任务，有则直接跳转，不创建新任务
      try {
        const { getEvaluationHistory } = await import('../../api/ai.js')
        const history = await getEvaluationHistory(this.achId)
        const running = (history.list || []).find(t => t.status === 'queued' || t.status === 'running')
        if (running) {
          this.evalSubmitting = false
          uni.navigateTo({
            url: `/subpackages/tech-transfer/pages/ai-eval-detail/ai-eval-detail?taskId=${running.taskId}&achievementId=${this.achId}`
          })
          return
        }
      } catch (e) {}
      try {
        // 服务端同成果 10 分钟去重：有进行中的任务会直接复用并跳转查看
        const task = await createEvaluationTask(this.achId)
        HostBridge.navigate('pages/ai-eval-detail/ai-eval-detail', {
          taskId: task.taskId,
          achievementId: this.achId,
        })
      } catch (e) {
        console.error('[achievement-detail] createEvaluationTask failed:', e)
        uni.showToast({ title: (e && e.message) || '评估发起失败', icon: 'none' })
      } finally {
        this.evalSubmitting = false
      }
    },
    mediaSrc(media) {
      // 与 dock-detail.vue 的 mediaSrc 一致：把相对 /api/... 补成绝对地址并附带 access_token，
      // 否则 WeChat MP 的 <image> 无法加载需要鉴权的成果资料图。
      return mediaDisplayUrl(
        media,
        HostBridge.getEnvironment() || {},
        HostBridge.getStorage('tt_access_token') || '',
      )
    },
    onProposeDock() {
      if (!this.achId) return
      HostBridge.navigate('pages/dock-detail/dock-detail', { type: 'result', id: this.achId })
    },
    canOpenPatent(patent) {
      return !!(patent && (patent.internalDetailAvailable || patent.externalUrl))
    },
    openPatent(patent) {
      if (!this.canOpenPatent(patent)) return
      if (patent.internalDetailAvailable) {
        HostBridge.navigate('pages/patent-detail/patent-detail', { publicationNo: patent.patentNo })
      } else if (patent.externalUrl) {
        this.openLink(patent.externalUrl)
      }
    },
    openLink(url) {
      if (!url) return
      HostBridge.navigate('pages/web-view/web-view', { url })
    },
    goBack() {
      safeNavigateBack(1)
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
  left: var(--window-left, 0px);
  right: var(--window-right, 0px);
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
.title-en { display: block; font-size: 25rpx; color: #718096; line-height: 1.5; margin: -8rpx 0 18rpx; word-break: break-word; }

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
.media-grid { display: flex; flex-wrap: wrap; gap: 12rpx; }
.media-image { width: calc(50% - 6rpx); height: 210rpx; border-radius: 10rpx; background: #eef4ff; }
.link-row { display: flex; align-items: center; min-height: 72rpx; border-bottom: 1rpx solid #edf1f5; }
.link-row-clickable { cursor: pointer; }
.link-row:last-child { border-bottom: none; }
.link-text { flex: 1; color: #2b73f8; font-size: 27rpx; line-height: 1.45; word-break: break-all; }
.link-arrow { color: #8fa0b5; font-size: 40rpx; margin-left: 12rpx; }

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

/* ── AI 智能评估入口卡片 ───────────────────────────────── */
.ai-eval-card {
  border: 1rpx solid rgba(43, 115, 248, 0.25);
}

.ai-eval-head {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
}

.ai-eval-title {
  margin-bottom: 0;
  color: #2b73f8;
}

.ai-eval-rating {
  font-size: 24rpx;
  color: #1f9d63;
  background: #e8f7f0;
  padding: 4rpx 16rpx;
  border-radius: 8rpx;
}

.ai-eval-loading {
  display: flex;
  flex-direction: row;
  align-items: center;
  padding: 12rpx 0;
}

.ai-spinner {
  width: 36rpx;
  height: 36rpx;
  border-radius: 50%;
  border: 4rpx solid rgba(43, 115, 248, 0.15);
  border-top-color: #2b73f8;
  animation: aiSpin 0.9s linear infinite;
  margin-right: 16rpx;
}

@keyframes aiSpin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.ai-eval-summary {
  display: flex;
  flex-direction: row;
  align-items: baseline;
}

.ai-eval-score {
  font-size: 64rpx;
  font-weight: 700;
  color: #2b73f8;
  line-height: 1;
}

.ai-eval-score-unit {
  margin-left: 8rpx;
  font-size: 24rpx;
  color: #999;
}

.ai-eval-time {
  margin-left: auto;
  font-size: 22rpx;
  color: #bbb;
}

.ai-eval-hint {
  display: block;
  font-size: 24rpx;
  color: #888;
  line-height: 1.6;
}

.ai-eval-actions {
  display: flex;
  flex-direction: row;
  margin-top: 20rpx;
}

.ai-eval-btn {
  flex: 1;
  background: #2b73f8 !important;
  color: #ffffff !important;
  border-radius: 12rpx;
  font-size: 26rpx;
  margin: 0 12rpx;
}

.ai-eval-btn--ghost {
  background: #ffffff !important;
  color: #2b73f8 !important;
  border: 1rpx solid #2b73f8;
}
</style>
