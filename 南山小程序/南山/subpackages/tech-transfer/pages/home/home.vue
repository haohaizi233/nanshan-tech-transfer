<template>
	<view class="page">
		<!-- 1. 顶部 Banner -->
		<!-- CDN建议：原图约3.1MB，已压缩入库；若需更高清可改为网络地址，例如 https://your-cdn.com/banner.jpg -->
		<view class="banner">
			<image
				class="banner-img"
				src="/static/banner-placeholder.jpg"
				mode="aspectFill"
			></image>
		</view>

		<!-- 2. 搜索框：左侧进入搜索，右侧扫码（码规则/接口待客户提供） -->
		<view class="search-wrap">
			<view class="search-box">
				<view class="search-main" @click="goSearchPage">
					<image class="search-icon" src="/static/icons/search.png" mode="aspectFit"></image>
					<text class="search-placeholder-text">搜索公司、成果标题、技术关键词</text>
				</view>
				<image
					class="search-scan"
					src="/static/icons/scan.png"
					mode="aspectFit"
					@click.stop="onScanCode"
				></image>
			</view>
		</view>

		<!-- 3. 快捷入口 -->
		<view class="action-row">
			<view class="action-card" @click="onPostDemand">
				<image class="action-icon" src="/static/icons/mine/demand.png" mode="aspectFit"></image>
				<text class="action-label">我要发需求</text>
			</view>
			<view class="action-card" @click="onPostResult">
				<image class="action-icon" src="/static/icons/mine/result.png" mode="aspectFit"></image>
				<text class="action-label">我要发成果</text>
			</view>
		</view>

		<!-- 4. 分类 Tab -->
		<view class="tab-bar">
			<view
				v-for="(item, index) in tabs"
				:key="item.key"
				class="tab-item"
				@click="switchTab(index)"
			>
				<text :class="activeTab === index ? 'tab-text tab-text-active' : 'tab-text'">{{ item.name }}</text>
				<view v-if="activeTab === index" class="tab-line"></view>
			</view>
		</view>

		<!-- 5. 列表区 -->
		<view class="list-wrap">
			<!-- 空状态 -->
			<view v-if="showEmpty" class="empty-box">
				<text class="empty-title">{{ emptyTitle }}</text>
				<text class="empty-desc">{{ emptyDesc }}</text>
			</view>

			<!-- 需求卡片 -->
			<block v-if="currentTabKey === 'demand'">
				<view
					v-for="item in demandList"
					:key="item.id"
					class="card"
					@click="openDetail('demand', item.id)"
				>
					<view class="card-head">
						<text class="card-title">{{ item.title }}</text>
						<text
							:class="item.favorited ? 'star-btn star-on' : 'star-btn'"
							@click.stop="onToggleFavorite('demand', item)"
						>{{ item.favorited ? '★' : '☆' }}</text>
					</view>
					<view v-if="item.company" class="card-sub-row">
						<text class="card-sub">{{ item.company }}</text>
						<text v-if="item.orgCertified" class="cert-badge">认证</text>
					</view>
					<view v-if="item.location || item.budget" class="meta-row">
						<view v-if="item.location" class="meta-item">
							<text class="meta-label">地点</text>
							<text class="meta-value">{{ item.location }}</text>
						</view>
						<view v-if="item.budget" class="meta-item">
							<text class="meta-label">预算</text>
							<text class="meta-value meta-value-em">{{ item.budget }}</text>
						</view>
					</view>
					<view v-if="item.demandDesc" class="info-block">
						<text class="info-label">需求说明</text>
						<text class="info-text">{{ item.demandDesc }}</text>
					</view>
					<view v-if="item.industryLine" class="info-block">
						<text class="info-label">行业 / 合作方式</text>
						<text class="info-text info-text-muted">{{ item.industryLine }}</text>
					</view>
					<view v-if="item.canDock" class="card-foot">
						<button class="dock-btn" size="mini" @click.stop="openDetail('demand', item.id)">我要对接</button>
					</view>
				</view>
			</block>

			<!-- 成果卡片（高校成果） -->
				<block v-if="currentTabKey === 'result'">
					<view
						v-for="item in resultList"
						:key="item.id"
						class="card"
						@click="openDetail('result', item.id)"
					>
						<view class="card-head">
							<text class="card-title">{{ item.title }}</text>
							<text
								:class="item.favorited ? 'star-btn star-on' : 'star-btn'"
								@click.stop="onToggleFavorite('result', item)"
							>{{ item.favorited ? '★' : '☆' }}</text>
						</view>
						<view v-if="item.source" class="meta-row">
							<view class="meta-item meta-item-full">
								<text class="meta-label">来源</text>
								<view class="meta-value-row">
									<text class="meta-value">{{ item.source }}</text>
									<text v-if="item.orgCertified" class="cert-badge">认证</text>
								</view>
							</view>
						</view>
						<view v-if="item.techIntro" class="info-block">
							<text class="info-label">技术简介</text>
							<text class="info-text">{{ item.techIntro }}</text>
						</view>
						<view class="price-row">
							<text class="price-label">期望报价</text>
							<text class="price-value">{{ item.price }}</text>
						</view>
						<view v-if="item.canDock" class="card-foot">
							<button class="dock-btn" size="mini" @click.stop="openDetail('result', item.id)">我要对接</button>
						</view>
					</view>
					<view v-if="resultList.length > 0" class="view-all-link" @click="goAchievementList">
						<text class="view-all-text">查看全部成果</text>
					</view>
				</block>

			<!-- 资本对接 -->
			<block v-if="currentTabKey === 'capital'">
				<view
					v-for="group in capitalGroups"
					:key="group.source"
					class="capital-group"
				>
					<view class="capital-group__head">
						<text class="capital-group__label">{{ group.label }}</text>
					</view>
					<view class="capital-grid">
						<view
							v-for="mod in group.modules"
							:key="mod.key"
							class="capital-item"
							@click="openCapital(mod)"
						>
							<view class="capital-item__icon">
								<text class="capital-item__icon-text">{{ mod.iconText }}</text>
							</view>
							<view class="capital-item__body">
								<view class="capital-item__title-row">
									<text class="capital-item__name">{{ mod.name }}</text>
									<text v-if="mod.pending" class="capital-item__badge">待定</text>
								</view>
								<text class="capital-item__desc">{{ mod.desc }}</text>
							</view>
						</view>
					</view>
				</view>
			</block>
		</view>

		<!-- 底部导航（分包业务壳统一 tab：首页 / AI匹配 / 我的） -->
		<AppTabbar active="home" />
	</view>
</template>

<script>
	import HostBridge from '../../../../host/host-bridge.js'
	import AppTabbar from '../../components/app-tabbar.vue'
	import { ensureLoginForDock, getUserProfile } from '../../api/user.js'
	import { getCapitalGroups } from '../../constants/capital-modules.js'
	import { getAchievements } from '../../api/achievement.js'
	import { toAchievementPreviewCard } from '../../api/achievement-dock-card.mjs'
	import { getDemands, toDemandCard } from '../../api/demand.js'
	import { addFavorite, removeFavorite, getFavoriteIdSet } from '../../api/interaction.js'
	import { retryRequest } from '../../api/request-retry.js'
	import { getScannedHttpUrl } from '../../utils/scanned-url.mjs'

	export default {
		components: {
			AppTabbar,
		},
		data() {
			return {
				activeTab: 0,
				tabs: [
					{ key: 'demand', name: '需求' },
					{ key: 'result', name: '成果' },
					{ key: 'search', name: '检索' },
					{ key: 'capital', name: '资本对接' }
				],
				demandList: [],
				resultList: [],
				capitalGroups: getCapitalGroups()
			}
		},
		computed: {
			currentTabName() {
				const tab = this.tabs[this.activeTab]
				return tab ? tab.name : ''
			},
			currentTabKey() {
				const tab = this.tabs[this.activeTab]
				return tab ? tab.key : ''
			},
			showEmpty() {
				if (this.currentTabKey === 'capital') return false
				if (this.currentTabKey === 'demand') {
					return this.demandList.length === 0
				}
				if (this.currentTabKey === 'result') {
					return this.resultList.length === 0
				}
				return true
			},
			emptyTitle() {
				if (this.currentTabKey === 'search') {
					return '检索功能开发中'
				}
				if (this.currentTabKey === 'capital') {
					return '暂无资本对接数据'
				}
				return '暂无' + this.currentTabName + '数据'
			},
			emptyDesc() {
				if (this.currentTabKey === 'search') {
					return '该功能将单独提供，敬请期待'
				}
				if (this.currentTabKey === 'capital') {
					return '功能开发中，敬请期待'
				}
				return '数据接口对接后将在此展示'
			}
		},
		onLoad() {
			this.applyPersonaTab()
		},
		onShow() {
			this.refreshList()
		},
		methods: {
			/** 画像=推荐信号（非门禁）：勾选「寻找技术成果」默认展示成果 Tab，其余默认需求 Tab */
			applyPersonaTab() {
				try {
					const profile = getUserProfile()
					const caps = (profile && profile.businessCapabilities) || []
					if (caps.indexOf('seek_technology') >= 0) {
						this.activeTab = 1
					}
				} catch (e) {
					// 画像仅影响默认 Tab，读取异常时保持默认
				}
			},
			async refreshList() {
				// 收藏状态（后端 API，失败时列表仍正常展示，只是不带收藏标记）
				let favDemandIds = new Set()
				let favResultIds = new Set()
				try {
					const sets = await Promise.all([getFavoriteIdSet('demand'), getFavoriteIdSet('result')])
					favDemandIds = sets[0]
					favResultIds = sets[1]
				} catch (e) {
					console.error('[index] loadFavorites failed:', e)
				}

				// 需求列表（真实 API）
				try {
					const data = await retryRequest(() => getDemands({ page: 1, pageSize: 10 }))
					this.demandList = (data.list || []).map((item) => {
						const card = toDemandCard(item)
						return {
							...card,
							industryLine: [card.industry, card.cooperationType].filter(Boolean).join(' · '),
							favorited: favDemandIds.has(String(card.id)),
							canDock: !card.isMine
						}
					})
				} catch (e) {
					console.error('[index] loadDemands failed:', e)
					this.demandList = []
				}

				// 成果列表（真实 API）
				try {
					const data = await retryRequest(() => getAchievements({ page: 1, pageSize: 10 }))
					this.resultList = (data.list || []).map((item) =>
						toAchievementPreviewCard(item, favResultIds.has(String(item.id)))
					)
				} catch (e) {
					console.error('[index] loadAchievements failed:', e)
					this.resultList = []
				}
			},
			switchTab(index) {
				const tab = this.tabs[index]
				// 「检索」：专利检索（需求/成果搜索仍走顶部搜索框 → search.vue）
				if (tab && tab.key === 'search') {
					HostBridge.navigate('pages/patent-list/patent-list')
					return
				}
				this.activeTab = index
			},
			openCapital(mod) {
				if (!mod || !mod.key) return
				HostBridge.navigate('pages/capital-list/capital-list', { type: mod.key })
			},
			/** 顶部搜索框：本小程序内需求/成果搜索 */
			goSearchPage() {
				HostBridge.navigate('pages/search/search')
			},
			/** 扫码：直接展示识别到的网址或文本 */
			onScanCode() {
				uni.scanCode({
					onlyFromCamera: false,
					scanType: ['qrCode', 'barCode'],
					success(res) {
						const result = String((res && res.result) || '').trim()
						const url = getScannedHttpUrl(result)
						if (url) {
							// #ifdef H5
							window.location.assign(url)
							return
							// #endif
							// #ifndef H5
							uni.navigateTo({ url: `/subpackages/tech-transfer/pages/web-view/web-view?url=${encodeURIComponent(url)}` })
							return
							// #endif
						}
						uni.showModal({
							title: '识别结果',
							content: result || '未识别到内容',
							showCancel: false,
							confirmText: '知道了'
						})
					},
					fail(err) {
						const msg = (err && err.errMsg) || ''
						if (msg.indexOf('cancel') >= 0) return
						uni.showToast({
							title: '扫码失败',
							icon: 'none'
						})
					}
				})
			},
			onPostDemand() {
				HostBridge.navigate('pages/post-demand/post-demand')
			},
			onPostResult() {
				HostBridge.navigate('pages/post-result/post-result')
			},
			async onToggleFavorite(type, item) {
				if (!ensureLoginForDock()) return
				// 乐观更新，失败回滚
				const next = !item.favorited
				item.favorited = next
				try {
					if (next) {
						await addFavorite(type, item.id)
					} else {
						await removeFavorite(type, item.id)
					}
					uni.showToast({ title: next ? '已收藏' : '已取消收藏', icon: 'none' })
				} catch (e) {
					item.favorited = !next
					uni.showToast({ title: (e && e.message) || '操作失败', icon: 'none' })
				}
			},
			openDetail(type, id) {
				if (!ensureLoginForDock()) return
				if (type === 'result') {
					HostBridge.navigate('pages/dock-detail/dock-detail', { type: 'result', id })
					return
				}
				HostBridge.navigate('pages/dock-detail/dock-detail', { type, id })
			},
			goAchievementList() {
				HostBridge.navigate('pages/achievement-list/achievement-list')
			}
		}
	}
</script>

<style>
	.page {
		min-height: 100vh;
		background-color: #f5f6f8;
		padding-bottom: calc(40rpx + env(safe-area-inset-bottom));
	}

	/* Banner 加高 */
	.banner {
		width: 100%;
		height: 420rpx;
		overflow: hidden;
		background-color: #1e408c;
		line-height: 0;
	}

	.banner-img {
		width: 100%;
		height: 100%;
		display: block;
	}

	/* 搜索框放大 */
	.search-wrap {
		padding: 0 24rpx;
		margin-top: -40rpx;
		position: relative;
		z-index: 10;
	}

	.search-box {
		height: 88rpx;
		background-color: #ffffff;
		border-radius: 44rpx;
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 0 28rpx 0 32rpx;
		box-shadow: 0 6rpx 20rpx rgba(0, 0, 0, 0.08);
	}

	.search-main {
		flex: 1;
		min-width: 0;
		height: 100%;
		display: flex;
		flex-direction: row;
		align-items: center;
	}

	.search-icon {
		width: 36rpx;
		height: 36rpx;
		margin-right: 16rpx;
		flex-shrink: 0;
	}

	.search-input {
		flex: 1;
		height: 88rpx;
		font-size: 32rpx;
		color: #333333;
	}

	.search-placeholder {
		color: #b0b0b0;
		font-size: 32rpx;
	}

	.search-placeholder-text {
		flex: 1;
		font-size: 30rpx;
		color: #b0b0b0;
	}

	.search-scan {
		width: 36rpx;
		height: 36rpx;
		margin-left: 16rpx;
		flex-shrink: 0;
	}

	.search-clear {
		font-size: 26rpx;
		color: #2b73f8;
		margin-left: 12rpx;
		flex-shrink: 0;
	}

	.action-row {
		display: flex;
		flex-direction: row;
		padding: 24rpx;
	}

	.action-card {
		flex: 1;
		height: 100rpx;
		background-color: #ffffff;
		border-radius: 16rpx;
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 0 20rpx;
		box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
		margin-right: 20rpx;
	}

	.action-card:last-child {
		margin-right: 0;
	}

	.action-icon {
		width: 80rpx;
		height: 80rpx;
		margin-right: 12rpx;
		flex-shrink: 0;
	}

	.action-label {
		flex: 1;
		font-size: 32rpx;
		color: #333333;
		font-weight: 500;
	}

	.tab-bar {
		display: flex;
		flex-direction: row;
		background-color: #ffffff;
		border-bottom: 1rpx solid #f0f0f0;
	}

	.tab-item {
		flex: 1;
		height: 88rpx;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		position: relative;
	}

	.tab-text {
		font-size: 28rpx;
		color: #666666;
	}

	.tab-text-active {
		color: #2b73f8;
		font-weight: 600;
	}

	.tab-line {
		position: absolute;
		left: 50%;
		bottom: 0;
		margin-left: -24rpx;
		width: 48rpx;
		height: 6rpx;
		border-radius: 6rpx;
		background-color: #2b73f8;
	}

	.list-wrap {
		padding: 24rpx;
	}

	.empty-box {
		background-color: #ffffff;
		border-radius: 16rpx;
		padding: 120rpx 40rpx;
		display: flex;
		flex-direction: column;
		align-items: center;
	}

	.empty-title {
		font-size: 30rpx;
		color: #666666;
	}

	.empty-desc {
		margin-top: 16rpx;
		font-size: 24rpx;
		color: #bbbbbb;
	}

	/* 通用卡片：方框区分每条记录 */
	.card {
		background-color: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 28rpx;
		margin-bottom: 24rpx;
		box-shadow: 0 4rpx 16rpx rgba(20, 40, 80, 0.04);
	}

	.card-head {
		display: flex;
		flex-direction: row;
		align-items: flex-start;
		justify-content: space-between;
		margin-bottom: 20rpx;
	}

	.card-title {
		flex: 1;
		font-size: 32rpx;
		color: #1a1a1a;
		font-weight: 600;
		line-height: 1.4;
		padding-right: 16rpx;
	}

	.card-sub {
		display: block;
		font-size: 26rpx;
		color: #666666;
		margin: -8rpx 0 20rpx;
	}

	.card-sub-row {
		display: flex;
		flex-direction: row;
		align-items: center;
		margin: -8rpx 0 20rpx;
	}

	.card-sub-row .card-sub {
		margin: 0;
	}

	.meta-value-row {
		display: flex;
		flex-direction: row;
		align-items: center;
	}

	.star-btn {
		flex-shrink: 0;
		font-size: 48rpx;
		color: #cccccc;
		line-height: 1;
		padding: 4rpx 8rpx;
		margin-top: -4rpx;
	}

	.star-on {
		color: #f5a623;
	}

	.meta-row {
		display: flex;
		flex-direction: row;
		background-color: #f7f9fc;
		border-radius: 12rpx;
		padding: 16rpx 20rpx;
		margin-bottom: 20rpx;
	}

	.meta-item {
		flex: 1;
		display: flex;
		flex-direction: column;
	}

	.meta-item-full {
		flex: 1;
	}

	.meta-label {
		font-size: 30rpx;
		color: #333333;
		font-weight: 600;
		margin-bottom: 8rpx;
	}

	.meta-value {
		font-size: 26rpx;
		color: #555555;
		font-weight: 400;
	}

	.meta-value-em {
		color: #2b73f8;
		font-weight: 500;
	}

	.info-block {
		margin-bottom: 16rpx;
	}

	.info-label {
		display: block;
		font-size: 30rpx;
		color: #222222;
		font-weight: 600;
		margin-bottom: 10rpx;
	}

	.info-text {
		display: block;
		font-size: 26rpx;
		color: #555555;
		line-height: 1.6;
	}

	.info-text-muted {
		color: #444444;
	}

	.price-row {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		background-color: #fff8f0;
		border-radius: 12rpx;
		padding: 16rpx 20rpx;
		margin-bottom: 8rpx;
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

	.card-foot {
		margin-top: 12rpx;
		display: flex;
		justify-content: flex-end;
	}

	.dock-btn {
		background-color: #2b73f8 !important;
		color: #ffffff !important;
		font-size: 26rpx !important;
		border-radius: 8rpx !important;
		margin: 0;
		padding: 0 28rpx;
		line-height: 60rpx;
	}

	.view-all-link {
		display: flex;
		justify-content: center;
		padding: 24rpx 0;
	}

	.view-all-text {
		font-size: 28rpx;
		color: #2b73f8;
		font-weight: 500;
	}

	.capital-group {
		margin-bottom: 28rpx;
	}

	.capital-group__head {
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 0 8rpx 14rpx;
	}

	.capital-group__label {
		font-size: 30rpx;
		font-weight: 600;
		color: #333333;
	}

	.capital-grid {
		display: flex;
		flex-direction: column;
	}

	.capital-item {
		display: flex;
		flex-direction: row;
		align-items: flex-start;
		background: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 28rpx;
		margin-bottom: 16rpx;
	}

	.capital-item__icon {
		width: 80rpx;
		height: 80rpx;
		border-radius: 16rpx;
		background: rgba(43, 115, 248, 0.1);
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		margin-right: 20rpx;
	}

	.capital-item__icon-text {
		font-size: 32rpx;
		font-weight: 600;
		color: #2b73f8;
	}

	.capital-item__body {
		flex: 1;
		min-width: 0;
	}

	.capital-item__title-row {
		display: flex;
		flex-direction: row;
		align-items: center;
	}

	.capital-item__name {
		font-size: 34rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.capital-item__badge {
		margin-left: 12rpx;
		padding: 2rpx 12rpx;
		border-radius: 8rpx;
		background: #fff4e5;
		font-size: 22rpx;
		color: #c47b1a;
	}

	.capital-item__desc {
		display: block;
		margin-top: 10rpx;
		font-size: 28rpx;
		color: #666666;
		line-height: 1.45;
	}

	.capital-item__hint {
		display: block;
		margin-top: 10rpx;
		font-size: 26rpx;
		color: #aaaaaa;
		line-height: 1.4;
	}
</style>
