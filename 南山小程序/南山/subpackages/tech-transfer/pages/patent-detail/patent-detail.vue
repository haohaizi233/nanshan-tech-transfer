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
        <button v-if="detail.hasPdf" class="pdf-btn" size="mini" :loading="pdfLoading" @click="onOpenPdf">查看说明书 PDF</button>
      </view>

      <view v-if="loading" class="section">
        <text class="state-text">正在加载摘要与权利要求...</text>
      </view>
      <view v-else-if="error" class="section">
        <text class="state-text">摘要暂不可用</text>
        <text class="state-sub">{{ error }}</text>
        <button class="retry-btn" size="mini" @click="loadDetail">重试</button>
      </view>

      <view v-if="detail.abstract" class="section">
        <text class="section-title">摘要</text>
        <text class="body-text">{{ detail.abstract }}</text>
      </view>

      <view v-if="detail.claims" class="section">
        <text class="section-title">权利要求</text>
        <text class="body-text">{{ detail.claims }}</text>
      </view>

      <view v-if="detail.description" class="section">
        <view class="section-head" @click="showDescription = !showDescription">
          <text class="section-title">说明书</text>
          <text class="toggle">{{ showDescription ? '收起' : '展开' }}</text>
        </view>
        <text v-if="showDescription" class="body-text">{{ detail.description }}</text>
      </view>
    </block>
  </view>
</template>

<script>
import { getPatentDetail, getPatentTypeLabel, openPatentPdf } from '../../api/patent.js'

export default {
  data() {
    return {
      publicationNo: '',
      detail: null,
      loading: false,
      pdfLoading: false,
      error: '',
      showDescription: false,
    }
  },
  onLoad(options) {
    const q = options || {}
    this.publicationNo = decodeURIComponent(q.no || '')
    if (!this.publicationNo) {
      this.detail = null
      this.error = '缺少专利公开号'
      return
    }
    this.detail = {
      publicationNo: this.publicationNo,
      title: q.title || '',
      applicant: q.applicant || '',
      inventor: q.inventor || '',
      applyDate: q.applyDate || '',
      publicationDate: q.publicationDate || '',
      grantDate: q.grantDate || '',
      patentType: q.patentType || '',
      hasPdf: q.hasPdf !== '0',
      abstract: '',
      claims: '',
      description: '',
    }
    this.loadDetail()
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
        const remote = await getPatentDetail(this.publicationNo)
        this.detail = {
          ...this.detail,
          ...remote,
          applicant: remote.applicant || (this.detail && this.detail.applicant) || '',
          inventor: remote.inventor || (this.detail && this.detail.inventor) || '',
          applyDate: remote.applyDate || (this.detail && this.detail.applyDate) || '',
          publicationDate: remote.publicationDate || (this.detail && this.detail.publicationDate) || '',
          grantDate: remote.grantDate || (this.detail && this.detail.grantDate) || '',
        }
        uni.setNavigationBarTitle({ title: this.detail.publicationNo || '专利详情' })
      } catch (e) {
        this.error = (e && e.message) || '加载失败'
      } finally {
        this.loading = false
      }
    },
    async onOpenPdf() {
      if (this.pdfLoading) return
      this.pdfLoading = true
      try {
        await openPatentPdf(this.publicationNo)
      } catch (e) {
        uni.showToast({ title: (e && e.message) || '无法打开说明书', icon: 'none' })
      } finally {
        this.pdfLoading = false
      }
    },
  },
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f5f6f8;
  padding: 24rpx;
  padding-bottom: calc(60rpx + env(safe-area-inset-bottom));
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

.section {
  background: #ffffff;
  border-radius: 16rpx;
  border: 1rpx solid #e8ecf2;
  padding: 28rpx;
  margin-bottom: 24rpx;
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
</style>
