<template>
	<view class="page">
		<!-- 搜索：平台库 / 机构库 -->
		<view v-if="isDbModule && !pending" class="search-bar">
			<input
				class="search-input"
				type="text"
				:value="keyword"
				:placeholder="searchPlaceholder"
				placeholder-class="search-ph"
				confirm-type="search"
				@input="onKeywordInput"
				@confirm="onSearch"
			/>
			<text class="search-btn" @click="onSearch">搜索</text>
			<text v-if="keyword" class="search-clear" @click="onClearSearch">清空</text>
		</view>

		<view v-if="loading" class="empty">
			<text class="empty__title">加载中…</text>
			<text class="empty__desc">正在从服务器读取数据</text>
		</view>

		<view v-else-if="loadError" class="empty">
			<text class="empty__title">加载失败</text>
			<text class="empty__desc">{{ loadError }}</text>
			<button class="retry-btn" size="mini" @click="loadData">重试</button>
		</view>

		<!-- 专利价值评估：待定占位 -->
		<view v-else-if="pending" class="pending-box">
			<view class="pending-card">
				<text class="pending-card__title">专利价值评估</text>
				<text class="pending-card__line">AI 初步评估 + 专家评估</text>
				<text class="pending-card__line">参考价值区间（待接入）</text>
				<text class="pending-card__tip">转让 / 许可 / 质押 / 作价入股定价参考</text>
			</view>
			<view class="empty">
				<text class="empty__title">数据待定</text>
				<text class="empty__desc">接口与评估模型确认后将在此展示结果卡片</text>
			</view>
		</view>

		<!-- 概念验证 / 中小试（数据库） -->
		<block v-else-if="isPlatform">
			<view v-for="item in list" :key="item.id" class="card">
				<view class="card__head">
					<text class="card__title">{{ item.name }}</text>
					<text class="tag">{{ item.platformType || typeLabel(item.platformTypeKey) }}</text>
				</view>
				<text class="card__sub">依托单位：{{ item.unit || '—' }}</text>
				<view class="block">
					<text class="block__label">平台功能</text>
					<text class="block__text">{{ item.functionText || '—' }}</text>
				</view>
				<view class="card__foot">
					<text class="contact">{{ item.contact || '—' }} · {{ item.phone || '—' }}</text>
					<button class="btn" size="mini" @click="onCall(item.phone)">联系</button>
				</view>
			</view>

			<view v-if="list.length === 0" class="empty">
				<text class="empty__title">暂无数据</text>
				<text class="empty__desc">{{ keyword ? '未匹配到相关平台，请更换关键词' : '数据库中暂无该类型平台' }}</text>
			</view>

			<view v-if="totalPages > 0" class="pager">
				<text
					:class="page <= 1 ? 'pager-btn pager-btn--disabled' : 'pager-btn'"
					@click="goPrev"
				>上一页</text>
				<text class="pager-info">{{ page }} / {{ totalPages }}</text>
				<text
					:class="page >= totalPages ? 'pager-btn pager-btn--disabled' : 'pager-btn'"
					@click="goNext"
				>下一页</text>
			</view>
		</block>

		<!-- 银行融资 / 投资机构：名称 + Logo + 简短介绍 -->
		<block v-else-if="isOrgModule">
			<view v-for="item in list" :key="item.id" class="org-card">
				<view class="org-card__top">
					<image
						v-if="item.logoUrl"
						class="org-logo"
						:src="item.logoUrl"
						mode="aspectFit"
						@error="onLogoError(item)"
					></image>
					<view v-else class="org-logo org-logo--fallback">
						<text class="org-logo__text">{{ logoFallback(item.name) }}</text>
					</view>
					<view class="org-card__main">
						<view class="org-card__head">
							<text class="card__title">{{ item.name }}</text>
							<text :class="moduleKey === 'bank' ? 'tag tag--blue' : 'tag tag--green'">
								{{ moduleKey === 'bank' ? (item.label || '专业服务机构') : '投资机构' }}
							</text>
						</view>
					</view>
				</view>
				<view class="block">
					<text class="block__label">机构简介</text>
					<text class="block__text">{{ item.intro || '暂无简介' }}</text>
				</view>
			</view>

			<view v-if="list.length === 0" class="empty">
				<text class="empty__title">暂无数据</text>
				<text class="empty__desc">{{ keyword ? '未匹配到相关机构，请更换关键词' : '数据库中暂无机构数据' }}</text>
			</view>

			<view v-if="totalPages > 0" class="pager">
				<text
					:class="page <= 1 ? 'pager-btn pager-btn--disabled' : 'pager-btn'"
					@click="goPrev"
				>上一页</text>
				<text class="pager-info">{{ page }} / {{ totalPages }}</text>
				<text
					:class="page >= totalPages ? 'pager-btn pager-btn--disabled' : 'pager-btn'"
					@click="goNext"
				>下一页</text>
			</view>
		</block>

		<view v-else-if="!pending && list.length === 0" class="empty">
			<text class="empty__title">暂无数据</text>
			<text class="empty__desc">数据源对接后将在此展示</text>
		</view>
	</view>
</template>

<script>
	import { getCapitalModule } from '../../constants/capital-modules.js'
	import {
		listCapitalItems,
		fetchPlatformList,
		fetchOrgList,
		getPlatformTypeLabel
	} from '../../api/capital.js'

	export default {
		data() {
			return {
				moduleKey: '',
				moduleName: '资本对接',
				moduleDesc: '',
				pending: false,
				list: [],
				loading: false,
				loadError: '',
				keyword: '',
				page: 1,
				pageSize: 10,
				total: 0,
				totalPages: 0
			}
		},
		computed: {
			isPlatform() {
				return this.moduleKey === 'poc' || this.moduleKey === 'pilot'
			},
			isOrgModule() {
				return this.moduleKey === 'bank' || this.moduleKey === 'invest'
			},
			isDbModule() {
				return this.isPlatform || this.isOrgModule
			},
			searchPlaceholder() {
				if (this.isOrgModule) return '搜索机构名称、简介'
				return '搜索平台名称、依托单位、功能、联系人'
			}
		},
		onLoad(options) {
			const key = (options && options.type) || ''
			const mod = getCapitalModule(key)
			this.moduleKey = key
			if (mod) {
				this.moduleName = mod.name
				this.moduleDesc = mod.desc
				this.pending = !!mod.pending
				uni.setNavigationBarTitle({ title: mod.name })
			}
			this.loadData()
		},
		methods: {
			typeLabel(type) {
				return getPlatformTypeLabel(type)
			},
			logoFallback(name) {
				const s = String(name || '').trim()
				return s ? s.slice(0, 1) : '机'
			},
			onLogoError(item) {
				if (!item) return
				item.logoUrl = ''
			},
			onKeywordInput(e) {
				this.keyword = e.detail.value
			},
			onSearch() {
				this.page = 1
				this.loadData()
			},
			onClearSearch() {
				this.keyword = ''
				this.page = 1
				this.loadData()
			},
			goPrev() {
				if (this.page <= 1 || this.loading) return
				this.page -= 1
				this.loadData()
			},
			goNext() {
				if (this.page >= this.totalPages || this.loading) return
				this.page += 1
				this.loadData()
			},
			async loadData() {
				this.loadError = ''
				if (this.pending) {
					this.list = []
					return
				}
				if (this.isPlatform || this.isOrgModule) {
					this.loading = true
					try {
						const res = this.isPlatform
							? await fetchPlatformList(this.moduleKey, this.keyword, this.page, this.pageSize)
							: await fetchOrgList(this.moduleKey, this.keyword, this.page, this.pageSize)
						this.list = res.list || []
						this.total = res.total || 0
						this.pageSize = res.pageSize || this.pageSize
						this.totalPages = res.totalPages || 0
						this.page = res.page || this.page
					} catch (e) {
						this.loadError = (e && e.message) || '加载失败'
						this.list = []
						this.total = 0
						this.totalPages = 0
					} finally {
						this.loading = false
					}
					return
				}
				this.list = listCapitalItems(this.moduleKey)
			},
			onCall(phone) {
				if (!phone) return
				uni.makePhoneCall({
					phoneNumber: String(phone),
					fail() {
						uni.setClipboardData({
							data: String(phone),
							success() {
								uni.showToast({ title: '已复制联系方式', icon: 'none' })
							}
						})
					}
				})
			}
		}
	}
</script>

<style scoped>
	.page {
		min-height: 100vh;
		background: #f5f6f8;
		padding: 24rpx;
		padding-bottom: calc(48rpx + env(safe-area-inset-bottom));
		box-sizing: border-box;
	}

	.search-bar {
		display: flex;
		flex-direction: row;
		align-items: center;
		background: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 12rpx 16rpx 12rpx 20rpx;
		margin-bottom: 20rpx;
	}

	.search-input {
		flex: 1;
		height: 64rpx;
		font-size: 26rpx;
		color: #222222;
	}

	.search-ph {
		color: #bbbbbb;
		font-size: 24rpx;
	}

	.search-btn {
		flex-shrink: 0;
		padding: 10rpx 18rpx;
		font-size: 26rpx;
		color: #2b73f8;
		font-weight: 600;
	}

	.search-clear {
		flex-shrink: 0;
		padding: 10rpx 8rpx;
		font-size: 24rpx;
		color: #999999;
	}

	.pager {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: center;
		padding: 16rpx 0 8rpx;
	}

	.pager-btn {
		padding: 12rpx 28rpx;
		font-size: 26rpx;
		color: #2b73f8;
		background: #ffffff;
		border-radius: 12rpx;
		border: 1rpx solid #dce6f8;
	}

	.pager-btn--disabled {
		color: #bbbbbb;
		border-color: #eeeeee;
	}

	.pager-info {
		margin: 0 24rpx;
		font-size: 26rpx;
		color: #666666;
	}

	.card,
	.org-card {
		background: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 28rpx;
		margin-bottom: 20rpx;
	}

	.org-card__top {
		display: flex;
		flex-direction: row;
		align-items: flex-start;
	}

	.org-logo {
		width: 96rpx;
		height: 96rpx;
		border-radius: 12rpx;
		background: #f3f5f8;
		border: 1rpx solid #e8ecf2;
		flex-shrink: 0;
		margin-right: 20rpx;
	}

	.org-logo--fallback {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.org-logo__text {
		font-size: 36rpx;
		font-weight: 600;
		color: #2b73f8;
	}

	.org-card__main {
		flex: 1;
		min-width: 0;
	}

	.card__head,
	.org-card__head {
		display: flex;
		flex-direction: row;
		align-items: flex-start;
		justify-content: space-between;
	}

	.card__title {
		flex: 1;
		font-size: 30rpx;
		font-weight: 600;
		color: #1a1a1a;
		line-height: 1.4;
		padding-right: 16rpx;
	}

	.card__sub {
		display: block;
		margin-top: 10rpx;
		font-size: 24rpx;
		color: #2b73f8;
	}

	.card__foot {
		margin-top: 20rpx;
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
	}

	.tag {
		flex-shrink: 0;
		padding: 6rpx 14rpx;
		border-radius: 8rpx;
		background: #f0f4fa;
		font-size: 22rpx;
		color: #4a5b78;
		max-width: 220rpx;
	}

	.tag--blue {
		background: rgba(43, 115, 248, 0.1);
		color: #2b73f8;
	}

	.tag--green {
		background: rgba(34, 153, 84, 0.1);
		color: #229954;
	}

	.block {
		margin-top: 16rpx;
		padding: 16rpx 18rpx;
		background: #f7f9fc;
		border-radius: 12rpx;
	}

	.block__label {
		display: block;
		font-size: 22rpx;
		color: #888888;
		margin-bottom: 8rpx;
	}

	.block__text {
		display: block;
		font-size: 26rpx;
		color: #555555;
		line-height: 1.55;
	}

	.contact {
		flex: 1;
		font-size: 24rpx;
		color: #666666;
		padding-right: 12rpx;
	}

	.btn {
		margin: 0;
		background: #2b73f8 !important;
		color: #ffffff !important;
	}

	.retry-btn {
		margin-top: 24rpx;
		background: #2b73f8 !important;
		color: #ffffff !important;
	}

	.pending-box {
		margin-top: 4rpx;
	}

	.pending-card {
		background: #ffffff;
		border-radius: 16rpx;
		border: 1rpx dashed #d0d7e2;
		padding: 28rpx;
		margin-bottom: 20rpx;
	}

	.pending-card__title {
		display: block;
		font-size: 30rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.pending-card__line {
		display: block;
		margin-top: 12rpx;
		font-size: 26rpx;
		color: #555555;
	}

	.pending-card__tip {
		display: block;
		margin-top: 16rpx;
		font-size: 24rpx;
		color: #999999;
	}

	.empty {
		padding: 80rpx 40rpx;
		background: #ffffff;
		border-radius: 16rpx;
		text-align: center;
	}

	.empty__title {
		display: block;
		font-size: 30rpx;
		color: #666666;
	}

	.empty__desc {
		display: block;
		margin-top: 12rpx;
		font-size: 24rpx;
		color: #bbbbbb;
		line-height: 1.5;
	}
</style>
