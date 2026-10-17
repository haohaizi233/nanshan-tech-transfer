<template>
  <view class="page">
    <!-- 搜索栏 -->
    <view class="search-bar">
      <view class="search-box">
        <text class="search-icon-text">🔍</text>
        <input
          class="search-input"
          type="text"
          confirm-type="search"
          :value="keyword"
          placeholder="搜索成果标题、技术简介、来源"
          placeholder-class="ph"
          @input="onKeywordInput"
          @confirm="onSearch"
        />
        <text v-if="keyword" class="clear-btn" @click="clearKeyword">✕</text>
      </view>
    </view>

    <!-- 分类筛选 -->
    <scroll-view class="category-bar" scroll-x>
      <view class="cat-item" :class="activeCategory === '' ? 'cat-active' : ''" @click="switchCategory('')">
        <text>全部</text>
      </view>
      <view
        v-for="cat in categories"
        :key="cat.code"
        class="cat-item"
        :class="activeCategory === cat.code ? 'cat-active' : ''"
        @click="switchCategory(cat.code)"
      >
        <text>{{ cat.name }}</text>
      </view>
    </scroll-view>

    <!-- 产业筛选：目录来自后台配置；没有选项或未选择时不构造任何产业语义。 -->
    <scroll-view v-if="industries.length" class="industry-bar" scroll-x>
      <view class="industry-item" :class="activeIndustryId === '' ? 'industry-active' : ''" @click="switchIndustry('')">
        <text>全部产业</text>
      </view>
      <view
        v-for="industry in industries"
        :key="industry.id"
        class="industry-item"
        :class="String(activeIndustryId) === String(industry.id) ? 'industry-active' : ''"
        @click="switchIndustry(industry.id)"
      >
        <text>{{ industry.name }}</text>
      </view>
    </scroll-view>

    <!-- 列表 -->
    <view class="list-wrap">
      <!-- 加载中（首次） -->
      <view v-if="loading && list.length === 0" class="state-box">
        <text class="state-text">加载中...</text>
      </view>

      <!-- 空状态 -->
      <view v-else-if="!loading && list.length === 0" class="state-box">
        <text class="state-text">暂无成果数据</text>
        <text class="state-sub">{{ keyword ? '试试更换关键词' : '请先发布成果' }}</text>
      </view>

      <!-- 成果列表 -->
      <view v-else>
        <view
          v-for="item in list"
          :key="item.id"
          class="card"
          @click="openDetail(item.id)"
        >
          <view class="card-summary">
            <image
              v-if="item.cover && item.cover.url"
              class="cover"
              :src="coverErrored[item.id] ? '/static/logo.png' : coverDisplayUrl(item.cover)"
              mode="aspectFill"
              lazy-load
              @error="onCoverError(item.id)"
            />
            <view class="card-content">
              <view class="card-head">
                <text class="card-title">{{ item.title }}</text>
                <text v-if="item.categoryName" class="badge">{{ item.categoryName }}</text>
              </view>
              <view v-if="item.sourceOrgName" class="meta-row">
                <text class="meta-source">{{ item.sourceOrgName }}</text>
                <view v-if="item.orgCertified" class="cert-badge cert-badge-with-icon">
                  <image class="cert-badge-icon-inline" src="/static/icons/mine/certification-badge.png" mode="aspectFit" lazy-load></image>
                  <text>认证</text>
                </view>
                <text v-if="formatMaturity(item)" class="meta-maturity">{{ formatMaturity(item) }}</text>
              </view>
              <text v-if="item.techIntro" class="tech-intro">{{ item.techIntro }}</text>
            </view>
          </view>
          <view v-if="item.applicationFields && item.applicationFields.length" class="field-tags">
            <text v-for="(field, idx) in item.applicationFields.slice(0, 3)" :key="idx" class="field-tag">{{ field }}</text>
          </view>
          <view v-if="formatPrice(item)" class="price-row">
            <text class="price-label">期望报价</text>
            <text class="price-value">{{ formatPrice(item) }}</text>
          </view>
        </view>

        <!-- 加载更多 -->
        <view v-if="loading && list.length > 0" class="load-more">
          <text>加载中...</text>
        </view>
        <view v-else-if="!hasMore && list.length > 0" class="load-more">
          <text>没有更多了</text>
        </view>
      </view>

      <!-- 错误状态 -->
      <view v-if="error" class="state-box">
        <text class="state-text">加载失败</text>
        <text class="state-sub">{{ error }}</text>
        <button class="retry-btn" size="mini" @click="loadList(true)">重试</button>
      </view>
    </view>
  </view>
</template>

<script>
import { getAchievements, getAchievementCategories, getAchievementIndustries } from '../../api/achievement.js'
import { mediaDisplayUrl } from '../../api/media-url.mjs'
import HostBridge from '../../../../host/host-bridge.js'

const MATURITY_LABELS = {
  '01_idea': '概念阶段',
  '02_lab': '实验室验证',
  '03_pilot_ready': '可进入中试',
  '04_pilot_done': '中试完成',
  '05_mass_ready': '可量产',
}

const PRICING_LABELS = {
  'negotiable': '面议',
  'license': '许可',
  'transfer': '转让',
  'cooperation': '合作',
}

export default {
  data() {
    return {
      keyword: '',
      activeCategory: '',
      activeIndustryId: '',
      categories: [],
      industries: [],
      list: [],
      page: 1,
      pageSize: 10,
      total: 0,
      hasMore: true,
      loading: false,
      error: '',
      coverErrored: {},
    }
  },
  onLoad() {
    this.loadCategories()
    this.loadIndustries()
    this.loadList(true)
  },
  onReachBottom() {
    if (this.hasMore && !this.loading) {
      this.loadList(false)
    }
  },
  onPullDownRefresh() {
    this.loadList(true)
  },
  methods: {
    async loadCategories() {
      try {
        const cats = await getAchievementCategories()
        this.categories = cats || []
      } catch (e) {
        console.error('[achievement-list] loadCategories failed:', e)
      }
    },
    async loadIndustries() {
      try {
        this.industries = (await getAchievementIndustries()) || []
      } catch (e) {
        console.error('[achievement-list] loadIndustries failed:', e)
        this.industries = []
      }
    },
    async loadList(reset) {
      if (this.loading) return
      this.loading = true
      this.error = ''
      if (reset) {
        this.page = 1
        this.hasMore = true
      }
      try {
        const data = await getAchievements({
          page: this.page,
          pageSize: this.pageSize,
          keyword: this.keyword,
          category: this.activeCategory,
          industryId: this.activeIndustryId,
        })
        const items = data.list || []
        if (reset) {
          this.list = items
        } else {
          this.list = this.list.concat(items)
        }
        this.total = data.total || 0
        this.hasMore = this.list.length < this.total
        if (this.hasMore) {
          this.page++
        }
      } catch (e) {
        console.error('[achievement-list] loadList failed:', e)
        this.error = e.message || '请求失败'
      } finally {
        this.loading = false
        if (reset) uni.stopPullDownRefresh()
      }
    },
    onKeywordInput(e) {
      this.keyword = e.detail.value
    },
    onSearch() {
      this.loadList(true)
    },
    clearKeyword() {
      this.keyword = ''
      this.loadList(true)
    },
    switchCategory(code) {
      if (this.activeCategory === code) return
      this.activeCategory = code
      this.loadList(true)
    },
    switchIndustry(id) {
      if (String(this.activeIndustryId) === String(id)) return
      this.activeIndustryId = id
      this.loadList(true)
    },
    formatMaturity(item) {
      return MATURITY_LABELS[item.maturityLevel] || item.maturityDesc || ''
    },
    coverDisplayUrl(cover) {
      // 成果封面在 WeChat MP 下需要绝对 origin + access_token 才能被 <image> 加载，
      // 与 dock-detail.vue 的 mediaSrc 走同一套 media-url 解析逻辑。
      return mediaDisplayUrl(
        { url: cover.thumbnailUrl || cover.url },
        HostBridge.getEnvironment() || {},
        HostBridge.getStorage('tt_access_token') || '',
      )
    },
    formatPrice(item) {
      if (item.pricingMode === 'negotiable') {
        return '面议'
      }
      if (!item.priceMinWan) {
        return ''
      }
      const min = item.priceMinWan
      const max = item.priceMaxWan
      if (min && max) {
        return `${min}–${max} 万`
      }
      return `${min} 万`
    },
    onCoverError(id) {
      // 封面加载失败时回退到占位图，避免列表出现碎图（R2-59）
      this.$set(this.coverErrored, id, true)
    },
    openDetail(id) {
      // 需求与成果统一走 dock-detail：该页包含详情、联系方式、对接状态与动作，
      // 不再经过冗余的“成果详情 → 成果对接”两步流程。
      HostBridge.navigate('pages/dock-detail/dock-detail', { type: 'result', id })
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
  padding: 20rpx 24rpx;
  background: #fff;
}

.search-box {
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

.category-bar {
  display: flex;
  white-space: nowrap;
  background: #fff;
  border-bottom: 1rpx solid #f0f0f0;
  padding: 0 12rpx;
}

.cat-item {
  display: inline-block;
  padding: 20rpx 24rpx;
  font-size: 28rpx;
  color: #666;
}

.cat-active {
  color: #2b73f8;
  font-weight: 600;
}

.list-wrap {
  padding: 24rpx;
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

.industry-bar {
  white-space: nowrap;
  background: #f7f9fc;
  border-bottom: 1rpx solid #edf1f5;
  padding: 12rpx 20rpx;
  box-sizing: border-box;
}

.industry-item {
  display: inline-flex;
  align-items: center;
  height: 52rpx;
  margin-right: 14rpx;
  padding: 0 20rpx;
  border-radius: 26rpx;
  background: #fff;
  border: 1rpx solid #e4eaf2;
  color: #667085;
  font-size: 24rpx;
  box-sizing: border-box;
}

.industry-active {
  background: #eaf2ff;
  border-color: #2b73f8;
  color: #2b73f8;
  font-weight: 600;
}

.card-summary {
  display: flex;
  min-width: 0;
}

.card-content {
  flex: 1;
  min-width: 0;
}

.cover {
  width: 150rpx;
  height: 150rpx;
  flex-shrink: 0;
  border-radius: 12rpx;
  background: #f0f4fb;
  margin-right: 20rpx;
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
  flex-wrap: wrap;
  gap: 8rpx;
  margin-bottom: 12rpx;
}

.meta-source {
  flex: 1;
  min-width: 0;
  font-size: 26rpx;
  color: #555;
}

.meta-maturity {
  font-size: 24rpx;
  color: #0f9d58;
  background: rgba(15, 157, 88, 0.08);
  padding: 4rpx 12rpx;
  border-radius: 8rpx;
}

.tech-intro {
	display: block;
	font-size: 26rpx;
	color: #555;
	line-height: 1.5;
	margin-bottom: 16rpx;
	/* 人工填写的摘要与详情正文使用相同的两字符首行缩进。 */
	text-indent: 2em;
	-webkit-line-clamp: 2;
	overflow: hidden;
	text-overflow: ellipsis;
	display: -webkit-box;
	-webkit-box-orient: vertical;
}

.field-tags {
  display: flex;
  flex-wrap: wrap;
  margin-bottom: 16rpx;
}

.field-tag {
  font-size: 22rpx;
  color: #666;
  background: #f5f6f8;
  padding: 4rpx 16rpx;
  border-radius: 20rpx;
  margin-right: 12rpx;
  margin-bottom: 8rpx;
}

.price-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff8f0;
  border-radius: 12rpx;
  padding: 16rpx 20rpx;
}

.price-label {
  font-size: 24rpx;
  color: #a67c52;
}

.price-value {
  font-size: 28rpx;
  color: #e67e22;
  font-weight: 600;
}

.load-more {
  text-align: center;
  padding: 24rpx;
  font-size: 26rpx;
  color: #999;
}
</style>
