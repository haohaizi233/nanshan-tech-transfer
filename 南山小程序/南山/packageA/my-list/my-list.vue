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
						v-if="(pageType === 'intention' || pageType === 'demand') && item._statusLabel"
						:class="'status-tag status-' + item._statusCls"
					>{{ item._statusLabel }}</text>
					<text :class="item._type === 'demand' ? 'badge badge-d' : 'badge badge-r'">
						{{ item._type === 'demand' ? '需求' : '成果' }}
					</text>
				</view>
			</view>
			<text v-if="item._sub" class="sub">{{ item._sub }}</text>
			<text class="desc">{{ item._desc }}</text>
			<view class="card-foot">
				<button class="btn" size="mini" @click="onOpen(item)">查看详情</button>
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
	import { getMyResults, getResultById } from '../../common/mock-data.js'
	import { getMyDemands, getDemandDetail, toDemandCard } from '../../common/demand-api.js'
	import {
		getFavorites,
		toggleFavorite,
		getSentIntentions,
		getReceivedIntentions,
		getIntentionStatusLabel,
		getUserProfile
	} from '../../common/user.js'

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
						? '在对接详情页点击「确认对接」后会出现在这里'
						: '当他人对接你发布的需求/成果（或演示数据对应手机号）时会出现在这里'
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
				return rows.map((item) => {
					let title = ''
					let desc = ''
					let openType = item.type
					let openId = item.id
					let badgeType = item.type

					if (this.intentTab === 0) {
						// 我提出的：展示对方那条（我点击对接的需求/成果）
						// 成果详情仍走 Mock（Phase B 后续迁移）；需求用意向创建时快照的 title/desc
						if (item.type === 'result') {
							const detail = getResultById(item.id)
							title = detail ? detail.title : (item.title || '意向对接')
							desc = detail ? detail.techIntro : (item.desc || '')
						} else {
							title = item.title || '意向对接'
							desc = item.desc || ''
						}
					} else {
						// 我收到的：展示发起方自己的内容（意向创建时已快照 fromSide*）
						if (item.fromSideTitle || item.fromSideId) {
							title = item.fromSideTitle || '对方对接内容'
							desc = item.fromSideDesc || ''
							openType = item.fromSideType || (item.fromIdentity === 'supply' ? 'result' : 'demand')
							openId = item.fromSideId || ''
							badgeType = openType
						} else {
							// 兼容旧数据：无快照时仅展示占位文案
							title = (item.fromNickname || '用户') + ' 的对接意向'
							desc = '对方暂未发布可展示的需求/成果，可通过联系方式沟通'
							openType = item.type
							openId = item.id
							badgeType = item.fromIdentity === 'supply' ? 'result' : 'demand'
						}
					}

					let sub = ''
					if (this.intentTab === 0) {
						sub = '对接对象：' + (item.toName || item.toPhone || '对方')
					} else {
						sub = '来自：' + (item.fromNickname || '用户') +
							(item.fromCompany ? ' · ' + item.fromCompany : '') +
							'（' + (item.fromPhone || '') + '）'
					}
					const status = item.status || 'pending'
					return {
						id: openId || item.id,
						_key: 'i-' + (item.intentId || (item.type + '-' + item.id + '-' + item.fromPhone)),
						_type: badgeType === 'result' ? 'result' : 'demand',
						_openType: openType,
						_openId: openId,
						_intentId: item.intentId || '',
						_role: this.intentTab === 0 ? 'sent' : 'received',
						_status: status,
						_statusLabel: getIntentionStatusLabel(status),
						_statusCls: status,
						_title: title,
						_desc: desc || '对接意向',
						_sub: sub
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
					const profile = getUserProfile()
					const phone = profile && profile.phone ? profile.phone : ''
					this.list = getMyResults(phone).map((item) => ({
						...item,
						_key: 'r-' + item.id,
						_type: 'result',
						_title: item.title,
						_desc: item.techIntro
					}))
					return
				}
				if (this.pageType === 'intention') {
					const profile = getUserProfile()
					const phone = profile && profile.phone ? profile.phone : ''
					const rows = this.intentTab === 0
						? getSentIntentions(phone)
						: getReceivedIntentions(phone)
					this.list = this.mapIntentionRows(rows)
					return
				}
				// 收藏：成果走 Mock；需求并行拉取详情（失效收藏自动跳过）
				const favorites = getFavorites()
				const rows = []
				await Promise.all(favorites.map(async (fav) => {
					if (fav.type === 'result') {
						const detail = getResultById(fav.id)
						if (!detail) return
						rows.push({
							...detail,
							_key: fav.type + '-' + fav.id,
							_type: fav.type,
							_title: detail.title,
							_desc: detail.techIntro
						})
						return
					}
					try {
						const data = await getDemandDetail(fav.id)
						const card = toDemandCard(data)
						rows.push({
							...card,
							_key: fav.type + '-' + fav.id,
							_type: fav.type,
							_title: card.title,
							_sub: card.company || '',
							_desc: card.demandDesc
						})
					} catch (e) {
						// 需求已下线/不可见，跳过
					}
				}))
				this.list = rows
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
			onRemoveFavorite(item) {
				toggleFavorite(item._type, item.id)
				this.loadList()
				uni.showToast({ title: '已取消收藏', icon: 'none' })
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
