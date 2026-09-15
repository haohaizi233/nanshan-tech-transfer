<template>
  <view class="page">
    <view class="search-bar">
      <view class="search-box">
        <text class="search-icon-text">🔍</text>
        <input
          class="search-input"
          type="text"
          confirm-type="search"
          :value="keyword"
          :placeholder="mode === 'assignee' ? '输入申请人名称' : '输入公开号、名称或关键词'"
          placeholder-class="ph"
          @input="onKeywordInput"
          @confirm="onSearch"
        />
        <text v-if="keyword" class="clear-btn" @click="clearKeyword">✕</text>
      </view>
      <text class="search-action" @click="onSearch">搜索</text>
    </view>

    <view class="mode-bar">
      <view class="mode-item" :class="mode === 'keyword' ? 'mode-active' : ''" @click="switchMode('keyword')">
        <text>综合检索</text>
      </view>
      <view class="mode-item" :class="mode === 'assignee' ? 'mode-active' : ''" @click="switchMode('assignee')">
        <text>按申请人</text>
      </view>
    </view>

    <view v-if="history.length" class="history-box">
      <text class="history-title">搜索记录</text>
      <view class="history-tags">
        <text
          v-for="item in history"
          :key="`${item.mode}-${item.keyword}`"
          class="history-tag"
          @click="onHistoryTap(item)"
        >{{ item.keyword }}</text>
      </view>
    </view>

    <view class="list-wrap">
      <view v-if="!searched" class="state-box">
        <text class="state-text">输入关键词检索专利</text>
        <text class="state-sub">可按名称/公开号综合检索，或按申请人精确查找</text>
      </view>

      <view v-else-if="loading && list.length === 0" class="state-box">
        <text class="state-text">检索中...</text>
      </view>

      <view v-else-if="error && list.length === 0" class="state-box">
        <text class="state-text">检索暂不可用</text>
        <text class="state-sub">{{ error }}</text>
        <button class="retry-btn" size="mini" @click="loadList(true)">重试</button>
      </view>

      <view v-else-if="!loading && list.length === 0" class="state-box">
        <text class="state-text">未找到相关专利</text>
        <text class="state-sub">试试更换关键词，或改用「按申请人」</text>
      </view>

      <view v-else>
        <text class="result-count">共 {{ total }} 件</text>
        <view
          v-for="item in list"
          :key="item.publicationNo"
          class="card"
          @click="openDetail(item)"
        >
          <view class="card-head">
            <text class="card-title">{{ item.title || item.publicationNo }}</text>
            <text class="badge">{{ typeLabel(item.patentType) }}</text>
          </view>
          <view class="meta-row">
            <text class="meta-no">{{ item.publicationNo }}</text>
            <text v-if="item.applyDate" class="meta-date">申请 {{ item.applyDate }}</text>
          </view>
          <text v-if="item.applicant" class="meta-source">{{ item.applicant }}</text>
          <text v-if="item.snippet" class="tech-intro">{{ item.snippet }}</text>
        </view>

        <view v-if="loading && list.length > 0" class="load-more">
          <text>加载中...</text>
        </view>
        <view v-else-if="!hasMore && list.length > 0" class="load-more">
          <text>没有更多了</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import {
  getPatentSearchHistory,
  getPatentTypeLabel,
  savePatentSearchHistory,
  searchPatents,
} from '../../api/patent.js'
import HostBridge from '../../../../host/host-bridge.js'

export default {
  data() {
    return {
      keyword: '',
      mode: 'keyword',
      list: [],
      page: 1,
      pageSize: 10,
      total: 0,
      hasMore: true,
      loading: false,
      searched: false,
      error: '',
      history: [],
    }
  },
  onLoad() {
    this.loadHistory()
  },
  onReachBottom() {
    if (this.searched && this.hasMore && !this.loading) {
      this.loadList(false)
    }
  },
  onPullDownRefresh() {
    if (!this.searched) {
      uni.stopPullDownRefresh()
      return
    }
    this.loadList(true)
  },
  methods: {
    typeLabel(type) {
      return getPatentTypeLabel(type)
    },
    onKeywordInput(e) {
      this.keyword = (e.detail && e.detail.value) || ''
    },
    clearKeyword() {
      this.keyword = ''
    },
    switchMode(mode) {
      if (this.mode === mode) return
      this.mode = mode
      this.loadHistory()
      if (this.searched && this.keyword.trim()) {
        this.loadList(true)
      }
    },
    onSearch() {
      const kw = this.keyword.trim()
      if (!kw) {
        uni.showToast({ title: '请输入检索词', icon: 'none' })
        return
      }
      this.saveHistory(kw)
      this.loadList(true)
    },
    async loadHistory() {
      try {
        const data = await getPatentSearchHistory(this.mode)
        this.history = (data && data.list) || []
      } catch (e) {
        this.history = []
      }
    },
    saveHistory(keyword) {
      savePatentSearchHistory(keyword, this.mode)
        .then(() => this.loadHistory())
        .catch(() => {})
    },
    onHistoryTap(item) {
      if (!item || !item.keyword) return
      this.mode = item.mode === 'assignee' ? 'assignee' : 'keyword'
      this.keyword = item.keyword
      this.onSearch()
    },
    async loadList(reset) {
      const kw = this.keyword.trim()
      if (!kw) return
      if (this.loading) return
      this.loading = true
      this.error = ''
      this.searched = true
      if (reset) {
        this.page = 1
        this.hasMore = true
        this.list = []
      }
      try {
        const params = { page: this.page, pageSize: this.pageSize }
        if (this.mode === 'assignee') params.assignee = kw
        else params.keyword = kw
        const data = await searchPatents(params)
        const rows = data.list || []
        this.total = data.total || 0
        this.list = reset ? rows : this.list.concat(rows)
        const totalPages = data.totalPages || 0
        this.hasMore = this.page < totalPages && rows.length > 0
        if (this.hasMore) this.page += 1
      } catch (e) {
        this.error = (e && e.message) || '检索失败'
        if (reset) this.list = []
      } finally {
        this.loading = false
        uni.stopPullDownRefresh()
      }
    },
    openDetail(item) {
      HostBridge.navigate('pages/patent-detail/patent-detail', {
        no: item.publicationNo,
        title: item.title || '',
        applicant: item.applicant || '',
        inventor: item.inventor || '',
        applyDate: item.applyDate || '',
        publicationDate: item.publicationDate || '',
        grantDate: item.grantDate || '',
        patentType: item.patentType || '',
        language: item.language || '',
        hasPdf: item.hasPdf ? '1' : '0',
      })
    },
  },
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f5f6f8;
}

.search-bar {
  display: flex;
  align-items: center;
  padding: 20rpx 24rpx;
  background: #fff;
  gap: 16rpx;
}

.search-box {
  flex: 1;
  display: flex;
  align-items: center;
  height: 72rpx;
  background: #f0f2f5;
  border-radius: 36rpx;
  padding: 0 24rpx;
}

.search-icon-text {
  font-size: 28rpx;
  margin-right: 12rpx;
}

.search-input {
  flex: 1;
  height: 72rpx;
  font-size: 28rpx;
  color: #222;
}

.ph {
  color: #999;
  font-size: 26rpx;
}

.clear-btn {
  font-size: 28rpx;
  color: #999;
  padding: 8rpx;
}

.search-action {
  font-size: 28rpx;
  color: #2b73f8;
  padding: 8rpx 4rpx;
}

.mode-bar {
  display: flex;
  background: #fff;
  border-bottom: 1rpx solid #f0f0f0;
  padding: 0 12rpx;
}

.mode-item {
  padding: 20rpx 28rpx;
  font-size: 28rpx;
  color: #666;
}

.mode-active {
  color: #2b73f8;
  font-weight: 600;
}

.list-wrap {
  padding: 24rpx;
}

.history-box {
  padding: 18rpx 24rpx 0;
  background: #fff;
  border-bottom: 1rpx solid #f0f0f0;
}

.history-title {
  display: block;
  margin-bottom: 12rpx;
  color: #697386;
  font-size: 24rpx;
  line-height: 32rpx;
}

.history-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
  max-height: 92rpx;
  overflow: hidden;
  padding-bottom: 18rpx;
}

.history-tag {
  max-width: 100%;
  overflow: hidden;
  padding: 8rpx 20rpx;
  border-radius: 24rpx;
  background: #f1f5fb;
  color: #4b5b73;
  font-size: 24rpx;
  line-height: 32rpx;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-count {
  display: block;
  font-size: 24rpx;
  color: #999;
  margin-bottom: 16rpx;
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

.card {
  background: #fff;
  border-radius: 16rpx;
  border: 1rpx solid #e8ecf2;
  padding: 28rpx;
  margin-bottom: 24rpx;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16rpx;
}

.card-title {
  flex: 1;
  font-size: 32rpx;
  font-weight: 600;
  color: #1a1a1a;
  line-height: 1.4;
  padding-right: 16rpx;
}

.badge {
  flex-shrink: 0;
  font-size: 22rpx;
  color: #2b73f8;
  background: rgba(43, 115, 248, 0.1);
  padding: 4rpx 12rpx;
  border-radius: 8rpx;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8rpx;
}

.meta-no,
.meta-date {
  font-size: 24rpx;
  color: #888;
}

.meta-source {
  display: block;
  font-size: 26rpx;
  color: #555;
  margin-bottom: 12rpx;
}

.tech-intro {
  display: block;
  font-size: 26rpx;
  color: #555;
  line-height: 1.5;
}

.load-more {
  text-align: center;
  padding: 24rpx;
  font-size: 26rpx;
  color: #999;
}
</style>
