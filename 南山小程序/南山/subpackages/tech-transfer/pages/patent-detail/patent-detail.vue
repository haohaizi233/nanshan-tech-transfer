<template>
  <view class="page">
    <view v-if="error && !detail" class="state-box">
      <text class="state-text">暂无法查看该专利</text>
      <text class="state-sub">{{ error }}</text>
      <button class="retry-btn" size="mini" @click="loadDetail">重试</button>
    </view>

    <block v-else-if="detail">
      <view class="section">
        <text class="main-title">{{ detail.title || detail.publicationNo }}</text>
        <view class="meta-list">
          <view class="meta-row">
            <text class="meta-label">公开号</text>
            <text class="meta-value">{{ detail.publicationNo }}</text>
          </view>
          <view v-if="detail.patentType" class="meta-row">
            <text class="meta-label">专利类型</text>
            <text class="meta-value">{{ typeLabel(detail.patentType) }}</text>
          </view>
          <view v-if="detail.applicant" class="meta-row">
            <text class="meta-label">申请人</text>
            <text class="meta-value">{{ detail.applicant }}</text>
          </view>
          <view v-if="detail.inventor" class="meta-row">
            <text class="meta-label">发明人</text>
            <text class="meta-value">{{ detail.inventor }}</text>
          </view>
          <view v-if="detail.applyDate" class="meta-row">
            <text class="meta-label">申请日</text>
            <text class="meta-value">{{ detail.applyDate }}</text>
          </view>
          <view v-if="detail.publicationDate" class="meta-row">
            <text class="meta-label">公开日</text>
            <text class="meta-value">{{ detail.publicationDate }}</text>
          </view>
          <view v-if="detail.grantDate" class="meta-row">
            <text class="meta-label">授权日</text>
            <text class="meta-value">{{ detail.grantDate }}</text>
          </view>
        </view>
        <button v-if="detail.hasPdf" class="pdf-btn" size="mini" @click="onOpenPdf">查看说明书 PDF</button>
      </view>

      <view v-if="loading" class="section">
        <text class="state-text">正在解析摘要与权利要求</text>
        <text class="state-sub">正在拼命加载中</text>
      </view>
      <view v-else-if="error" class="section">
        <text class="state-text">摘要暂不可用</text>
        <text class="state-sub">{{ error }}</text>
        <button class="retry-btn" size="mini" @click="loadDetail">重试</button>
      </view>

      <view v-if="activeSection === 'abstract' && detail.abstract" class="section reader-section">
        <text class="section-title">摘要</text>
        <block v-if="detail.abstractBlocks && detail.abstractBlocks.length">
          <block
            v-for="(block, index) in detail.abstractBlocks"
            :key="`abstract-${index}`"
          >
            <rich-text
              v-if="block.html"
              :nodes="block.html"
              :class="block.type === 'formula' ? 'body-formula' : 'body-paragraph'"
            />
            <text
              v-else
              :class="block.type === 'formula' ? 'body-formula' : (block.type === 'code' ? 'body-code' : 'body-paragraph')"
            >{{ block.text }}</text>
          </block>
        </block>
        <text v-else class="body-text">{{ detail.abstract }}</text>
      </view>

      <view v-if="activeSection === 'claims' && detail.claims" class="section reader-section">
        <text class="section-title">权利要求</text>
        <block v-if="detail.claimsBlocks && detail.claimsBlocks.length">
          <block
            v-for="(block, index) in detail.claimsBlocks"
            :key="`claims-${index}`"
          >
            <rich-text
              v-if="block.html"
              :nodes="block.html"
              :class="block.type === 'formula' ? 'body-formula' : 'body-paragraph'"
            />
            <text
              v-else
              :class="block.type === 'formula' ? 'body-formula' : (block.type === 'code' ? 'body-code' : 'body-paragraph')"
            >{{ block.text }}</text>
          </block>
        </block>
        <text v-else class="body-text">{{ detail.claims }}</text>
      </view>

      <view v-if="activeSection === 'description' && detail.description" class="section reader-section">
        <text class="section-title">说明书</text>
        <block v-if="detail.descriptionBlocks && detail.descriptionBlocks.length">
          <block
            v-for="(block, index) in detail.descriptionBlocks"
            :key="`description-${index}`"
          >
            <rich-text
              v-if="block.html"
              :nodes="block.html"
              :class="block.type === 'formula' ? 'body-formula' : 'body-paragraph'"
            />
            <text
              v-else
              :class="block.type === 'formula' ? 'body-formula' : (block.type === 'code' ? 'body-code' : 'body-paragraph')"
            >{{ block.text }}</text>
          </block>
        </block>
        <text v-else class="body-text">{{ detail.description }}</text>
      </view>
    </block>
    <view v-if="detail" class="reader-nav">
      <view
        v-for="item in navigationItems"
        :key="item.key"
        class="reader-nav-item"
        @click="onNavigateSection(item.key)"
      >
        <image
          :class="['reader-nav-icon', { 'reader-nav-icon-active': activeSection === item.key }]"
          :src="activeSection === item.key ? item.activeIcon : item.icon"
          mode="aspectFit"
        />
        <text :class="['reader-nav-label', { 'reader-nav-label-active': activeSection === item.key }]">
          {{ item.label }}
        </text>
      </view>
    </view>
    <pdf-preview-overlay
      :visible="pdfVisible"
      :publication-no="publicationNo"
      @close="pdfVisible = false"
    />
  </view>
</template>

<script>
import { getPatentDetail, getPatentTypeLabel, isPatentLoginRequired } from '../../api/patent.js'
import PdfPreviewOverlay from '../../components/pdf-preview-overlay.vue'
import HostBridge from '../../../../host/host-bridge.js'
import { createPageStateMixin } from '../../api/page-state-cache.mjs'
import { buildPatentDetailSeed, mergePatentDetail } from '../../utils/patent-detail-state.mjs'
import {
  PATENT_DETAIL_NAV_ITEMS,
  getPatentDetailNavigationTarget,
} from '../../utils/patent-detail-navigation.mjs'

export default {
  mixins: [createPageStateMixin({
    route: 'pages/patent-detail/patent-detail',
    groups: [{ name: 'detail', dataClass: 'detail', fields: ['publicationNo', 'detail', 'activeSection'] }],
  })],
  components: { PdfPreviewOverlay },
  data() {
    return {
      publicationNo: '',
      detail: null,
      loading: false,
      pdfVisible: false,
      error: '',
      activeSection: 'abstract',
      navigationItems: PATENT_DETAIL_NAV_ITEMS,
    }
  },
  onBackPress() {
    if (this.pdfVisible) {
      this.pdfVisible = false
      return true
    }
    return false
  },
  onLoad(options) {
    const q = options || {}
    const seed = buildPatentDetailSeed(q)
    this.publicationNo = seed.publicationNo
    if (!this.publicationNo) {
      this.detail = null
      this.error = '缺少专利公开号'
      return
    }
    if (!this.hasRestoredPageState('detail')) this.detail = seed
    if (this.shouldRevalidatePageState('detail')) this.loadDetail()
  },
  onShow() {
    if (this.shouldRevalidatePageState('detail')) this.loadDetail()
  },
  methods: {
    typeLabel(type) {
      return getPatentTypeLabel(type)
    },
    async loadDetail() {
      if (!this.publicationNo) {
        this.error = '缺少专利公开号'
        return
      }
      this.loading = true
      this.error = ''
      try {
        const remote = await getPatentDetail(this.publicationNo, (this.detail && this.detail.language) || '')
        this.detail = mergePatentDetail(this.detail || {}, remote)
        uni.setNavigationBarTitle({ title: this.detail.publicationNo || '专利详情' })
        this.markPageStateFresh('detail')
      } catch (e) {
        if (isPatentLoginRequired(e)) {
          this.error = '专利详情需要登录，请先登录或注册后查看。'
          uni.showModal({
            title: '登录后查看专利',
            content: this.error,
            confirmText: '去登录',
            success: (result) => {
              if (result.confirm) HostBridge.navigate('pages/mine/mine')
            },
          })
        } else {
          this.error = (e && e.message) || '加载失败'
        }
      } finally {
        this.loading = false
      }
    },
    onOpenPdf() {
      if (!this.publicationNo) {
        uni.showToast({ title: '缺少专利公开号', icon: 'none' })
        return
      }
      this.pdfVisible = true
    },
    onNavigateSection(section) {
      const target = getPatentDetailNavigationTarget(section)
      if (!this.detail || !this.detail[target.section]) {
        uni.showToast({ title: '暂无相关内容', icon: 'none' })
        return
      }
      this.activeSection = target.section
    },
  },
}
</script>

<style scoped>
	@import '../../../../styles/common.css';

.page {
  min-height: 100vh;
  background: #f5f6f8;
  padding: 24rpx;
  padding-bottom: calc(196rpx + env(safe-area-inset-bottom));
  box-sizing: border-box;
}

.state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 120rpx 40rpx;
  background: #fff;
  border-radius: 16rpx;
}

.state-text {
  font-size: 30rpx;
  color: #666;
}

.state-sub {
  font-size: 24rpx;
  color: #bbb;
  margin-top: 12rpx;
  text-align: center;
}

.retry-btn {
  margin-top: 24rpx;
  background: #2b73f8 !important;
  color: #fff !important;
}

.main-title {
  display: block;
  font-size: 34rpx;
  font-weight: 600;
  color: #1a1a1a;
  line-height: 1.4;
  margin-bottom: 24rpx;
}

.meta-list {
  background: #f7f9fc;
  border-radius: 12rpx;
  padding: 8rpx 20rpx;
}

.meta-row {
  display: flex;
  flex-direction: row;
  padding: 18rpx 0;
}

.meta-label {
  width: 140rpx;
  flex-shrink: 0;
  font-size: 26rpx;
  color: #888;
}

.meta-value {
  flex: 1;
  font-size: 26rpx;
  color: #222;
  line-height: 1.5;
}

.pdf-btn {
  margin-top: 24rpx;
  background: #2b73f8 !important;
  color: #fff !important;
}

.section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.section-title {
  display: block;
  font-size: 30rpx;
  font-weight: 600;
  color: #1a1a1a;
  margin-bottom: 16rpx;
}

.toggle {
  font-size: 24rpx;
  color: #2b73f8;
  margin-bottom: 16rpx;
}

.body-text {
  display: block;
  font-size: 26rpx;
  color: #444;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.body-paragraph {
  display: block;
  font-size: 26rpx;
  color: #444;
  line-height: 1.8;
  text-indent: 2em;
  margin-bottom: 14rpx;
  word-break: break-word;
}

.body-formula {
  display: block;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 25rpx;
  color: #1f2937;
  line-height: 1.8;
  text-align: center;
  text-indent: 0;
  padding: 16rpx 12rpx;
  margin: 12rpx 0 20rpx;
  background: #f7f9fc;
  border-radius: 8rpx;
  word-break: break-all;
}

.body-code {
  display: block;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 24rpx;
  color: #1f2937;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
  text-indent: 0;
  padding: 16rpx;
  margin: 12rpx 0 20rpx;
  background: #f1f5f9;
  border-radius: 8rpx;
}

.reader-nav {
  position: fixed;
  left: var(--window-left, 0px);
  right: var(--window-right, 0px);
  bottom: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-around;
  min-height: 132rpx;
  padding: 10rpx 24rpx calc(10rpx + env(safe-area-inset-bottom));
  box-sizing: border-box;
  background: rgba(255, 255, 255, 0.96);
  border-top: 1rpx solid #edf0f5;
  border-radius: 24rpx 24rpx 0 0;
  box-shadow: 0 -4rpx 24rpx rgba(34, 51, 84, 0.1);
}

.reader-nav-item {
  display: flex;
  flex: 1;
  min-width: 0;
  height: 104rpx;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.reader-nav-icon {
  width: 52rpx;
  height: 52rpx;
}

.reader-nav-icon-active {
  width: 120rpx;
  height: 58rpx;
}

.reader-nav-label {
  display: block;
  min-height: 30rpx;
  margin-top: 4rpx;
  color: #697386;
  font-size: 24rpx;
  line-height: 30rpx;
  text-align: center;
}

.reader-nav-label-active {
  color: #1769f5;
  font-weight: 600;
}
</style>
