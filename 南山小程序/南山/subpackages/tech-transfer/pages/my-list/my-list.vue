<template>
	<view class="page">
		<!-- 我的需求 / 成果：按发布状态筛选，草稿仅在“全部”保留。 -->
		<scroll-view v-if="isPublicationList" class="publication-tabs" :scroll-x="true" :show-scrollbar="false">
			<view class="publication-tabs-inner">
				<view
					v-for="tab in publicationTabs"
					:key="tab.value"
					:class="publicationTab === tab.value ? 'publication-tab active' : 'publication-tab'"
					@click="selectPublicationTab(tab.value)"
				>{{ tab.label }}</view>
			</view>
		</scroll-view>

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

		<view v-if="needLogin" class="empty">
			<text class="empty-title">请登录后查看</text>
			<text class="empty-desc">该内容仅对登录用户可见</text>
			<button class="btn" size="mini" @click="goLogin">去登录</button>
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
					v-if="pageType === 'result' && aiEnabled"
					class="btn ghost"
					size="mini"
					:disabled="item._evalLoading"
					@click="onStartEval(item)"
				>{{ item._evalLoading ? '提交中…' : 'AI 评估' }}</button>
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
	import { getMyDemands, toDemandCard } from '../../api/demand.js'
	import { getMyAchievements, toAchievementCard } from '../../api/achievement.js'
	import { createEvaluationTask } from '../../api/ai.js'
	import HostBridge from '../../../../host/host-bridge.js'
	import { AI_FEATURE_ENABLED } from '../../../../config/feature-flags.js'
	import { createPageStateMixin, getPageStateScope, invalidatePageStateKeys } from '../../api/page-state-cache.mjs'
	import {
		getMyFavorites,
		removeFavorite,
		getMyCooperations,
		toFeType,
		getCooperationDisplayLabel,
		getCooperationDisplayCls,
		getIntentTypeLabel,
		getAssistedHint
	} from '../../api/interaction.js'

	export default {
		mixins: [createPageStateMixin({
			route: 'pages/my-list/my-list',
			groups: [{ name: 'list', dataClass: 'list', fields: ['pageType', 'publicationTab', 'intentTab', 'intentAutoSwitched', 'needLogin', 'list', 'listContext'] }],
		})],
		data() {
			return {
			aiEnabled: AI_FEATURE_ENABLED,
			pageType: 'demand',
			publicationTab: 'published',
			intentTab: 0,
			intentAutoSwitched: false,
			needLogin: false,
			list: [],
			listContext: '',
			}
		},
		computed: {
			isPublicationList() {
				return this.pageType === 'demand' || this.pageType === 'result'
			},
			publicationTabs() {
				const common = [
					{ value: 'all', label: '全部' },
					{ value: 'pending_review', label: '待审核' },
					{ value: 'rejected', label: '已驳回' },
					{ value: 'published', label: '已发布' }
				]
				if (this.pageType === 'result') {
					return common.concat([{ value: 'offline', label: '已下架' }])
				}
				return common.concat([
					{ value: 'matched', label: '已对接' },
					{ value: 'cancelled', label: '已取消' },
					{ value: 'offline', label: '已下架' }
				])
			},
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
			// 深链入口（分享链接）直达时，若无任何会话令牌则拦截为登录提示，避免渲染空壳/接口 401 闪烁
			if (!HostBridge.getStorage('tt_access_token')) {
				this.needLogin = true
				this.list = []
				this.clearPageState('list')
				uni.setNavigationBarTitle({ title: '请登录' })
				return
			}
			if (this.pageType === 'demand' || this.pageType === 'result') {
				this.publicationTab = 'published'
			}
			const titleMap = {
				demand: '我发布的需求',
				result: '我发布的成果',
				favorite: '我的收藏',
				intention: '意向请求'
			}
			uni.setNavigationBarTitle({
				title: titleMap[this.pageType] || '我的内容'
			})
		},
		onShow() {
			// 缓存过期时刷新列表数据
			if (this.shouldRevalidatePageState('list')) {
				this.refreshList()
			}
			if (this.needLogin) return
			return this.loadList()
		},
		async onPullDownRefresh() {
			try {
				if (!this.needLogin) await this.loadList()
			} finally {
				uni.stopPullDownRefresh()
			}
		},
		methods: {
			currentListContext() {
				return JSON.stringify([this.pageType, this.publicationTab, this.intentTab])
			},
			goLogin() {
				HostBridge.navigate('pages/mine/mine')
			},
			selectPublicationTab(tab) {
				if (this.publicationTab === tab) return
				this.publicationTab = tab
				this.loadList()
			},
			async loadPublicationList(fetchList, mapRow) {
				const status = this.publicationTab === 'all' ? '' : this.publicationTab
				if (status === 'offline') {
					const [offline, closed] = await Promise.all([
						fetchList({ page: 1, pageSize: 50, status: 'offline' }),
						fetchList({ page: 1, pageSize: 50, status: 'closed' })
					])
					return [...(offline.list || []), ...(closed.list || [])].map(mapRow)
				}
				const data = await fetchList({ page: 1, pageSize: 50, status })
				return (data.list || []).map(mapRow)
			},
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
					const handlingMode = item.handlingMode || 'direct'
					const assistStatus = item.assistStatus || null
					const statusLabel = getCooperationDisplayLabel(item.status, handlingMode, assistStatus)
					const statusCls = getCooperationDisplayCls(item.status, handlingMode, assistStatus)
					const statusHint = handlingMode === 'assisted'
						? getAssistedHint(item.status, assistStatus)
						: ''
					return {
						id: item.targetId,
						_key: 'c-' + item.id,
						_type: feType,
						_openType: feType,
						_openId: item.targetId,
						_intentId: item.id,
						_role: isSent ? 'sent' : 'received',
						_status: item.status,
						_statusLabel: statusLabel,
						_statusCls: statusCls,
						_statusHint: statusHint,
						_title: sum.title || '意向对接',
						_desc: sum.desc || sum.orgName || '对接意向',
						_sub: ((isSent ? '对接对象：' : '来自：') + (item.counterpartDisplayName || '对方'))
							+ (intentLabel ? ' · 意向：' + intentLabel : '')
					}
				})
			},
			async loadList() {
				const requestId = (this._listRequestId || 0) + 1
				this._listRequestId = requestId
				const context = this.currentListContext()
				const scope = getPageStateScope()
				const isCurrent = () => this._listRequestId === requestId
					&& this.currentListContext() === context && getPageStateScope() === scope
				const applyRows = rows => {
					if (!isCurrent()) return
					this.list = rows
					this.listContext = context
					this.markPageStateFresh('list')
				}
				if (this.listContext !== context) this.list = []
			if (this.pageType === 'demand') {
					try {
						const rows = await this.loadPublicationList(getMyDemands, (item) => {
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
								_statusCls: card.statusCls,
								_statusHint: card.statusHint
							}
						})
						applyRows(rows)
					} catch (e) {
						console.error('[my-list] loadMyDemands failed:', e)
					}
					return
				}
			if (this.pageType === 'result') {
					try {
						const rows = await this.loadPublicationList(getMyAchievements, (item) => {
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
								_evalLoading: false
							}
						})
						applyRows(rows)
					} catch (e) {
						console.error('[my-list] loadMyAchievements failed:', e)
					}
					return
				}
				if (this.pageType === 'intention') {
					try {
						const role = this.intentTab === 0 ? 'initiator' : 'target'
						const data = await getMyCooperations({ role, page: 1, pageSize: 50 })
						if (!isCurrent()) return
						this.list = this.mapIntentionRows(data.list || [])
						// 默认 tab（我提出的）为空但对侧有数据时自动切换一次，
						// 避免 mine 角标有计数、点进来却看到空列表误以为接口未接通
						if (!this.list.length && !this.intentAutoSwitched) {
							this.intentAutoSwitched = true
							const otherRole = role === 'initiator' ? 'target' : 'initiator'
							const other = await getMyCooperations({ role: otherRole, page: 1, pageSize: 50 })
							if (!isCurrent()) return
							if ((other.total || 0) > 0) {
								this.intentTab = otherRole === 'initiator' ? 0 : 1
								this.list = this.mapIntentionRows(other.list || [])
							}
						}
						this.listContext = this.currentListContext()
						this.markPageStateFresh('list')
					} catch (e) {
						console.error('[my-list] loadCooperations failed:', e)
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
						const offline = ['offline', 'closed', 'cancelled'].includes(sum.status)
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
					applyRows(rows)
				} catch (e) {
					console.error('[my-list] loadFavorites failed:', e)
				}
			},
			onOpen(item) {
				const type = item._openType || item._type
				const id = item._openId || item.id
				if (!id) {
					uni.showToast({ title: '暂无可查看的详情', icon: 'none' })
					return
				}
				const params = { type, id }
				if (this.pageType === 'intention' && item._intentId) {
					params.intentId = item._intentId
					params.role = item._role || ''
				}
				HostBridge.navigate('pages/dock-detail/dock-detail', params)
			},
			async onStartEval(item) {
				if (!this.aiEnabled || item._evalLoading) return
				item._evalLoading = true
				try {
					// 去重命中时返回既有未终态任务，直接跳转查看
					const task = await createEvaluationTask(item.id)
					HostBridge.navigate('pages/ai-eval-detail/ai-eval-detail', {
						taskId: task.taskId,
						achievementId: item.id
					})
				} catch (e) {
					console.error('[my-list] createEvaluationTask failed:', e)
					uni.showToast({ title: (e && e.message) || '评估发起失败', icon: 'none' })
				} finally {
					item._evalLoading = false
				}
			},
			async onRemoveFavorite(item) {
				try {
					await removeFavorite(item._type, item.id)
					invalidatePageStateKeys(['pages/mine/mine:dashboard', 'pages/my-list/my-list:list'])
					await this.loadList()
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

	.publication-tabs {
		width: calc(100% + 48rpx);
		white-space: nowrap;
		margin: 0 0 20rpx -24rpx;
		box-sizing: border-box;
	}

	.publication-tabs-inner {
		display: inline-block;
		min-width: 100%;
		padding: 4rpx 24rpx;
		box-sizing: border-box;
	}

	.publication-tab {
		display: inline-block;
		vertical-align: middle;
		margin-right: 16rpx;
		padding: 12rpx 22rpx;
		border-radius: 28rpx;
		background: #ffffff;
		border: 1rpx solid #dfe5ee;
		color: #637083;
		font-size: 26rpx;
		line-height: 1.3;
	}

	.publication-tab:last-child {
		margin-right: 0;
	}

	.publication-tab.active {
		background: #2f6df6;
		border-color: #2f6df6;
		color: #ffffff;
		font-weight: 600;
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
