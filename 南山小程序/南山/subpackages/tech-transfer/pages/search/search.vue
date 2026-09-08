<template>
	<view class="page">
		<!-- 顶部搜索栏 -->
		<view class="search-bar">
			<view class="search-box">
				<image class="search-icon" src="/static/icons/search.png" mode="aspectFit"></image>
				<input
					class="search-input"
					type="text"
					confirm-type="search"
					:value="keyword"
					:placeholder="searchType === 0 ? '搜索公司名称、需求说明' : '搜索成果标题、技术简介、来源'"
					placeholder-class="ph"
					@input="onInput"
					@confirm="onConfirmSearch"
				/>
			</view>
			<text class="link action" @click="onConfirmSearch">搜索</text>
		</view>

		<!-- 栏目：搜索需求 / 搜索成果 -->
		<view class="tabs">
			<view class="tab-item" @click="switchType(0)">
				<text :class="searchType === 0 ? 'tab-text active' : 'tab-text'">搜索需求</text>
				<view v-if="searchType === 0" class="tab-line"></view>
			</view>
			<view class="tab-item" @click="switchType(1)">
				<text :class="searchType === 1 ? 'tab-text active' : 'tab-text'">搜索成果</text>
				<view v-if="searchType === 1" class="tab-line"></view>
			</view>
		</view>

		<view class="block">
			<!-- 当前栏目历史 -->
			<view class="history-box">
				<view class="row-between">
					<text class="block-title">{{ searchType === 0 ? '需求' : '成果' }}历史搜索</text>
					<text v-if="currentHistory.length" class="muted" @click="onClearHistory">清空</text>
				</view>
				<view v-if="currentHistory.length" class="tags">
					<text
						v-for="(item, index) in currentHistory"
						:key="index"
						class="tag-item"
						@click="onHistoryTap(item)"
					>{{ item }}</text>
				</view>
				<view v-else class="history-empty">
					<text class="muted">暂无{{ searchType === 0 ? '需求' : '成果' }}搜索记录</text>
				</view>
			</view>

			<!-- 列表：无关键词展示全部，有关键词展示匹配结果 -->
			<text class="result-count">
				{{ listTip }}
			</text>

			<view v-if="currentList.length === 0" class="empty card">
				<text class="empty-title">暂无{{ searchType === 0 ? '需求' : '成果' }}数据</text>
				<text class="muted">{{ keyword.trim() ? '试试更换关键词' : '请先发布相关信息' }}</text>
			</view>

			<!-- 需求列表 -->
			<block v-if="searchType === 0">
				<view v-for="item in demandList" :key="'d-' + item.id" class="card" @click="openDetail('demand', item.id)">
					<view class="card-head">
						<text class="card-title">{{ item.title }}</text>
						<text class="badge badge-d">需求</text>
					</view>
					<text class="meta">{{ item.metaLine }}</text>
					<text class="desc">{{ item.demandDesc }}</text>
					<view v-if="item.canDock" class="card-foot">
						<button class="btn" size="mini" @click.stop="openDetail('demand', item.id)">我要对接</button>
					</view>
				</view>
			</block>

			<!-- 成果列表 -->
			<block v-else>
				<view v-for="item in resultList" :key="'r-' + item.id" class="card" @click="openDetail('result', item.id)">
					<view class="card-head">
						<text class="card-title">{{ item.title }}</text>
						<text class="badge badge-r">高校成果</text>
					</view>
					<text class="meta">{{ item.source }}</text>
					<text class="desc">{{ item.techIntro }}</text>
					<view v-if="item.canDock" class="card-foot">
						<button class="btn" size="mini" @click.stop="openDetail('result', item.id)">我要对接</button>
					</view>
				</view>
			</block>
		</view>
	</view>
</template>

<script>
	import {
		getDemandSearchHistory,
		getResultSearchHistory,
		addDemandSearchHistory,
		addResultSearchHistory,
		clearDemandSearchHistory,
		clearResultSearchHistory
	} from '../../api/search.js'
	import { ensureLoginForDock } from '../../api/user.js'
	import HostBridge from '../../../../host/host-bridge.js'
	import { searchAchievements } from '../../api/achievement.js'
	import { getDemands, toDemandCard } from '../../api/demand.js'

	export default {
		data() {
			return {
				keyword: '',
				searchType: 0,
				demandHistory: [],
				resultHistory: [],
				demandList: [],
				resultList: []
			}
		},
		computed: {
			currentHistory() {
				return this.searchType === 0 ? this.demandHistory : this.resultHistory
			},
			currentList() {
				return this.searchType === 0 ? this.demandList : this.resultList
			},
			listTip() {
				const kw = (this.keyword || '').trim()
				const name = this.searchType === 0 ? '需求' : '成果'
				const count = this.currentList.length
				if (!kw) {
					return '全部' + name + '（' + count + ' 条）'
				}
				return '“' + kw + '” ' + name + '共 ' + count + ' 条'
			}
		},
		onLoad() {
			this.loadHistory()
			this.loadDemands('')
			this.loadResults('')
		},
		onShow() {
			this.loadHistory()
			if (this.searchType === 0) {
				this.loadDemands(this.keyword)
			} else {
				this.loadResults(this.keyword)
			}
		},
		methods: {
			loadHistory() {
				this.demandHistory = getDemandSearchHistory() || []
				this.resultHistory = getResultSearchHistory() || []
			},
			switchType(type) {
				this.searchType = type
				this.keyword = ''
				if (type === 0) {
					this.loadDemands('')
				} else {
					this.loadResults('')
				}
			},
			async loadDemands(keyword) {
				try {
					const data = await getDemands({ keyword: keyword || '', page: 1, pageSize: 50 })
					this.demandList = (data.list || []).map((item) => {
						const card = toDemandCard(item)
						return {
							...card,
							metaLine: [card.company, card.location, card.budget].filter(Boolean).join(' ｜ '),
							canDock: !card.isMine
						}
					})
				} catch (e) {
					console.error('[search] loadDemands failed:', e)
					this.demandList = []
				}
			},
			async loadResults(keyword) {
				try {
					const data = await searchAchievements({ keyword: keyword || '', page: 1, pageSize: 50 })
					this.resultList = (data.list || []).map((item) => ({
						id: String(item.id),
						title: item.title,
						source: item.sourceOrgName || '',
						techIntro: item.techIntro || '',
						canDock: true
					}))
				} catch (e) {
					console.error('[search] loadResults failed:', e)
					this.resultList = []
				}
			},
			onInput(e) {
				this.keyword = e.detail.value
				if (this.searchType === 0) {
					this.loadDemands(this.keyword)
				}
			},
			onConfirmSearch() {
				const kw = (this.keyword || '').trim()
				if (!kw) {
					uni.showToast({ title: '请输入搜索关键词', icon: 'none' })
					return
				}
				this.keyword = kw
				if (this.searchType === 0) {
					this.loadDemands(kw)
				} else {
					this.loadResults(kw)
				}
				this.saveHistory(kw)
			},
			saveHistory(kw) {
				if (this.searchType === 0) {
					this.demandHistory = addDemandSearchHistory(kw)
				} else {
					this.resultHistory = addResultSearchHistory(kw)
				}
			},
			onHistoryTap(item) {
				this.keyword = item
				if (this.searchType === 0) {
					this.loadDemands(item)
				} else {
					this.loadResults(item)
				}
				this.saveHistory(item)
			},
			onClearHistory() {
				const name = this.searchType === 0 ? '需求' : '成果'
				uni.showModal({
					title: '提示',
					content: '确定清空全部' + name + '搜索历史吗？',
					success: (res) => {
						if (!res.confirm) return
						if (this.searchType === 0) {
							this.demandHistory = clearDemandSearchHistory()
						} else {
							this.resultHistory = clearResultSearchHistory()
						}
					}
				})
			},
			openDetail(type, id) {
				if (!ensureLoginForDock()) return
				if (type === 'result') {
					HostBridge.navigate('pages/achievement-detail/achievement-detail', { id })
					return
				}
				HostBridge.navigate('pages/dock-detail/dock-detail', { type, id })
			}
		}
	}
</script>

<style>
	.page {
		min-height: 100vh;
		background: #f5f6f8;
		padding-bottom: calc(24rpx + env(safe-area-inset-bottom));
		box-sizing: border-box;
	}

	.search-bar {
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 20rpx 24rpx;
		background: #ffffff;
	}

	.search-box {
		flex: 1;
		height: 72rpx;
		background: #f0f2f5;
		border-radius: 36rpx;
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 0 24rpx;
	}

	.search-icon {
		width: 32rpx;
		height: 32rpx;
		margin-right: 12rpx;
	}

	.search-input {
		flex: 1;
		height: 72rpx;
		font-size: 28rpx;
		color: #222222;
	}

	.ph {
		color: #999999;
		font-size: 26rpx;
	}

	.link {
		color: #2b73f8;
		font-size: 28rpx;
	}

	.action {
		margin-left: 20rpx;
		font-weight: 600;
	}

	.tabs {
		display: flex;
		flex-direction: row;
		background: #ffffff;
		border-bottom: 1rpx solid #f0f0f0;
	}

	.tab-item {
		flex: 1;
		height: 84rpx;
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

	.tab-text.active {
		color: #2b73f8;
		font-weight: 600;
	}

	.tab-line {
		position: absolute;
		bottom: 0;
		width: 64rpx;
		height: 6rpx;
		border-radius: 6rpx;
		background: #2b73f8;
	}

	.block {
		padding: 24rpx;
	}

	.history-box {
		background: #ffffff;
		border-radius: 16rpx;
		padding: 24rpx;
		margin-bottom: 20rpx;
		border: 1rpx solid #e8ecf2;
	}

	.row-between {
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 16rpx;
	}

	.block-title {
		font-size: 28rpx;
		font-weight: 600;
		color: #222222;
	}

	.muted {
		font-size: 26rpx;
		color: #999999;
	}

	.tags {
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
	}

	.tag-item {
		background: #f5f6f8;
		border-radius: 28rpx;
		padding: 10rpx 22rpx;
		margin: 0 12rpx 12rpx 0;
		font-size: 26rpx;
		color: #333333;
	}

	.history-empty {
		padding: 8rpx 0 4rpx;
	}

	.empty {
		padding: 60rpx 20rpx;
		text-align: center;
	}

	.empty-title {
		display: block;
		font-size: 30rpx;
		color: #666666;
		margin-bottom: 12rpx;
	}

	.result-count {
		display: block;
		font-size: 26rpx;
		color: #666666;
		margin-bottom: 16rpx;
	}

	.card {
		background: #ffffff;
		border-radius: 16rpx;
		padding: 28rpx;
		margin-bottom: 20rpx;
		border: 1rpx solid #e8ecf2;
	}

	.card-head {
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: flex-start;
		margin-bottom: 12rpx;
	}

	.card-title {
		flex: 1;
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
		padding-right: 16rpx;
	}

	.badge {
		font-size: 22rpx;
		padding: 4rpx 12rpx;
		border-radius: 8rpx;
	}

	.badge-d {
		color: #2b73f8;
		background: rgba(43, 115, 248, 0.1);
	}

	.badge-r {
		color: #0f9d58;
		background: rgba(15, 157, 88, 0.1);
	}

	.meta {
		display: block;
		font-size: 26rpx;
		color: #555555;
		margin-bottom: 12rpx;
	}

	.desc {
		display: block;
		font-size: 26rpx;
		color: #333333;
		line-height: 1.5;
	}

	.card-foot {
		margin-top: 16rpx;
		display: flex;
		justify-content: flex-end;
	}

	.btn {
		background: #2b73f8 !important;
		color: #ffffff !important;
		margin: 0;
	}
</style>
