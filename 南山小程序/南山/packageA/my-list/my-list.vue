<template>
	<view class="page">
		<!-- 意向请求：提出 / 收到 -->
		<view v-if="pageType === 'intention'" class="intent-tabs">
			<view class="intent-tab" @click="switchIntentTab(0)">
				<text :class="intentTab === 0 ? 'intent-tab-text active' : 'intent-tab-text'">我提出的</text>
				<view v-if="intentTab === 0" class="intent-tab-line"></view>
			</view>
			<view class="intent-tab" @click="switchIntentTab(1)">
				<text :class="intentTab === 1 ? 'intent-tab-text active' : 'intent-tab-text'">我收到的</text>
				<view v-if="intentTab === 1" class="intent-tab-line"></view>
			</view>
		</view>

		<view v-if="list.length === 0" class="empty">
			<text class="empty-title">{{ emptyTitle }}</text>
			<text class="empty-desc">{{ emptyDesc }}</text>
		</view>

		<view v-for="item in list" :key="item._key" class="card">
			<view class="card-head">
				<text class="card-title">{{ item._title }}</text>
				<view class="badge-wrap">
					<text
						v-if="item._statusLabel"
						:class="'status-tag status-' + item._statusCls"
					>{{ item._statusLabel }}</text>
					<text :class="item._type === 'demand' ? 'badge badge-d' : 'badge badge-r'">
						{{ item._type === 'demand' ? '需求' : '成果' }}
					</text>
				</view>
			</view>
			<text v-if="item._sub" class="sub">{{ item._sub }}</text>
			<text v-if="item._statusHint" :class="'review-hint review-hint-' + item._statusCls">{{ item._statusHint }}</text>
			<text class="desc">{{ item._desc }}</text>
			<view class="card-foot">
				<button v-if="!item._gone" class="btn" size="mini" @click="onOpen(item)">查看详情</button>
				<button
					v-if="pageType === 'favorite'"
					class="btn ghost"
					size="mini"
					@click="onRemoveFavorite(item)"
				>取消收藏</button>
			</view>
		</view>
	</view>
</template>

<script>
	import { getMyDemands, toDemandCard } from '../../common/demand-api.js'
	import { getMyAchievements, toAchievementCard } from '../../common/achievement-api.js'
	import {
		getMyFavorites,
		removeFavorite,
		getMyCooperations,
		toFeType,
		getCoopStatusLabel,
		getCoopStatusCls,
		getIntentTypeLabel
	} from '../../common/interaction-api.js'

	export default {
		data() {
			return {
				pageType: 'demand',
				intentTab: 0,
				list: []
			}
		},
		computed: {
			emptyTitle() {
				if (this.pageType === 'favorite') return '暂无收藏'
				if (this.pageType === 'intention') {
					return this.intentTab === 0 ? '暂无提出的意向' : '暂无收到的意向'
				}
				if (this.pageType === 'result') return '暂无发布的成果'
				return '暂无发布的需求'
			},
			emptyDesc() {
				if (this.pageType === 'favorite') return '在对接详情页可收藏感兴趣的内容'
				if (this.pageType === 'intention') {
					return this.intentTab === 0
						? '在对接详情页点击「申请对接」后会出现在这里'
						: '当他人向你发布的需求/成果发起对接时会出现在这里'
				}
				return '可在首页发布后在此查看'
			}
		},
		onLoad(options) {
			this.pageType = options.type || 'demand'
			const titleMap = {
				demand: '我发布的需求',
				result: '我发布的成果',
				favorite: '我的收藏',
				intention: '意向请求'
			}
			uni.setNavigationBarTitle({
				title: titleMap[this.pageType] || '我的内容'
			})
			this.loadList()
		},
		onShow() {
			this.loadList()
		},
		methods: {
			switchIntentTab(index) {
				this.intentTab = index
				this.loadList()
			},
			mapIntentionRows(rows) {
				// 后端意向行内嵌 targetSummary + counterpartDisplayName，两侧均按目标内容展示
				const isSent = this.intentTab === 0
				return rows.map((item) => {
					const sum = item.targetSummary || {}
					const feType = toFeType(item.targetType)
					const intentLabel = getIntentTypeLabel(feType, item.intentType)
					return {
						id: item.targetId,
						_key: 'c-' + item.id,
						_type: feType,
						_openType: feType,
						_openId: item.targetId,
						_intentId: item.id,
						_role: isSent ? 'sent' : 'received',
						_status: item.status,
						_statusLabel: getCoopStatusLabel(item.status),
						_statusCls: getCoopStatusCls(item.status),
						_title: sum.title || '意向对接',
						_desc: sum.desc || sum.orgName || '对接意向',
						_sub: ((isSent ? '对接对象：' : '来自：') + (item.counterpartDisplayName || '对方'))
							+ (intentLabel ? ' · 意向：' + intentLabel : '')
					}
				})
			},
			async loadList() {
				if (this.pageType === 'demand') {
					try {
						const data = await getMyDemands({ page: 1, pageSize: 50 })
						this.list = (data.list || []).map((item) => {
							const card = toDemandCard(item)
							return {
								...card,
								_key: 'd-' + card.id,
								_type: 'demand',
								_title: card.title,
								_sub: card.company || '',
								_desc: card.demandDesc,
								_status: card.status,
								_statusLabel: card.statusLabel,
								_statusCls: card.statusCls
							}
						})
					} catch (e) {
						console.error('[my-list] loadMyDemands failed:', e)
						this.list = []
					}
					return
				}
				if (this.pageType === 'result') {
					try {
						const data = await getMyAchievements({ page: 1, pageSize: 50 })
						this.list = (data.list || []).map((item) => {
							const card = toAchievementCard(item)
							return {
								...card,
								_key: 'r-' + card.id,
								_type: 'result',
								_title: card.title,
								_sub: card.sourceOrgName,
								_desc: card.techIntro,
								_status: card.status,
								_statusLabel: card.statusLabel,
								_statusCls: card.statusCls,
								_statusHint: card.statusHint,
							}
						})
					} catch (e) {
						console.error('[my-list] loadMyAchievements failed:', e)
						this.list = []
					}
					return
				}
				if (this.pageType === 'intention') {
					try {
						const data = await getMyCooperations({
							role: this.intentTab === 0 ? 'initiator' : 'target',
							page: 1,
							pageSize: 50
						})
						this.list = this.mapIntentionRows(data.list || [])
					} catch (e) {
						console.error('[my-list] loadCooperations failed:', e)
						this.list = []
					}
					return
				}
				// 收藏：后端列表内嵌目标摘要（已下线目标仍返回并标注）
				try {
					const [favDemand, favResult] = await Promise.all([
						getMyFavorites('demand', { page: 1, pageSize: 50 }),
						getMyFavorites('result', { page: 1, pageSize: 50 })
					])
					const rows = []
					const push = (fav, feType) => {
						const sum = fav.targetSummary
						const deleted = !sum || sum.status === 'deleted'
						if (deleted) {
							// 目标已被删除：仍展示占位卡片，避免「有计数但列表空白」
							rows.push({
								id: fav.targetId,
								_key: feType + '-' + fav.targetId,
								_type: feType,
								_title: '已收藏内容（已删除）',
								_sub: '',
								_desc: '该内容已被发布方删除，可取消收藏移除记录',
								_gone: true
							})
							return
						}
						const offline = sum.status && sum.status !== 'published'
						rows.push({
							id: fav.targetId,
							_key: feType + '-' + fav.targetId,
							_type: feType,
							_title: offline ? sum.title + '（已下线）' : sum.title,
							_sub: sum.orgName || '',
							_desc: sum.desc || ''
						})
					}
					;(favDemand.list || []).forEach((fav) => push(fav, 'demand'))
					;(favResult.list || []).forEach((fav) => push(fav, 'result'))
					this.list = rows
				} catch (e) {
					console.error('[my-list] loadFavorites failed:', e)
					this.list = []
				}
			},
			onOpen(item) {
				const type = item._openType || item._type
				const id = item._openId || item.id
				if (!id) {
					uni.showToast({ title: '暂无可查看的详情', icon: 'none' })
					return
				}
				let url = '/packageA/dock-detail/dock-detail?type=' + type + '&id=' + id
				if (this.pageType === 'intention' && item._intentId) {
					url += '&intentId=' + encodeURIComponent(item._intentId) + '&role=' + (item._role || '')
				}
				uni.navigateTo({ url })
			},
			async onRemoveFavorite(item) {
				try {
					await removeFavorite(item._type, item.id)
					this.loadList()
					uni.showToast({ title: '已取消收藏', icon: 'none' })
				} catch (e) {
					console.error('[my-list] removeFavorite failed:', e)
					uni.showToast({ title: (e && e.message) || '操作失败', icon: 'none' })
				}
			}
		}
	}
</script>

<style>
	.page {
		min-height: 100vh;
		background: #f5f6f8;
		padding: 24rpx;
		padding-bottom: calc(24rpx + env(safe-area-inset-bottom));
		box-sizing: border-box;
	}

	.intent-tabs {
		display: flex;
		flex-direction: row;
		background: #ffffff;
		border-radius: 16rpx;
		margin-bottom: 20rpx;
		border: 1rpx solid #e8ecf2;
		overflow: hidden;
	}

	.intent-tab {
		flex: 1;
		height: 88rpx;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		position: relative;
	}

	.intent-tab-text {
		font-size: 28rpx;
		color: #666666;
	}

	.intent-tab-text.active {
		color: #2b73f8;
		font-weight: 600;
	}

	.intent-tab-line {
		position: absolute;
		left: 50%;
		bottom: 0;
		margin-left: -28rpx;
		width: 56rpx;
		height: 6rpx;
		border-radius: 6rpx;
		background: #2b73f8;
	}

	.empty {
		padding: 120rpx 40rpx;
		background: #ffffff;
		border-radius: 16rpx;
		text-align: center;
	}

	.empty-title {
		display: block;
		font-size: 30rpx;
		color: #666666;
	}

	.empty-desc {
		display: block;
		margin-top: 12rpx;
		font-size: 24rpx;
		color: #bbbbbb;
		line-height: 1.5;
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

	.badge-wrap {
		display: flex;
		flex-direction: row;
		align-items: center;
		flex-shrink: 0;
		gap: 8rpx;
	}

	.badge {
		font-size: 22rpx;
		padding: 4rpx 12rpx;
		border-radius: 8rpx;
	}

	.badge-d {
		color: #2b73f8;
		background: rgba(43, 115, 248, 0.12);
	}

	.badge-r {
		color: #0f9d58;
		background: rgba(15, 157, 88, 0.12);
	}

	.status-tag {
		font-size: 22rpx;
		padding: 4rpx 12rpx;
		border-radius: 8rpx;
	}

	.status-draft {
		color: #666666;
		background: rgba(102, 102, 102, 0.12);
	}

	.status-pending {
		color: #f5a623;
		background: rgba(245, 166, 35, 0.12);
	}

	.status-accepted {
		color: #2b73f8;
		background: rgba(43, 115, 248, 0.12);
	}

	.status-rejected {
		color: #999999;
		background: rgba(153, 153, 153, 0.12);
	}

	.status-success {
		color: #0f9d58;
		background: rgba(15, 157, 88, 0.12);
	}

	.sub {
		display: block;
		font-size: 24rpx;
		color: #2b73f8;
		margin-bottom: 8rpx;
		line-height: 1.4;
	}

	.review-hint {
		display: block;
		font-size: 24rpx;
		line-height: 1.45;
		margin-bottom: 8rpx;
	}

	.review-hint-pending { color: #d98a00; }
	.review-hint-success { color: #0f9d58; }
	.review-hint-rejected { color: #8a5d00; }
	.review-hint-draft,
	.review-hint-accepted { color: #666666; }

	.desc {
		display: block;
		font-size: 26rpx;
		color: #444444;
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
		margin: 0 0 0 16rpx;
	}

	.btn.ghost {
		background: #ffffff !important;
		color: #666666 !important;
		border: 1rpx solid #dddddd !important;
	}
</style>
