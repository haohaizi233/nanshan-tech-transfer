<template>
	<view class="page">
		<view class="header">
			<text class="header__title">AI 需求匹配</text>
			<text class="header__desc">选择我的需求发起 AI 匹配，为您推荐合适的技术成果</text>
		</view>

		<view v-if="loading" class="empty-box">
			<text class="empty-title">加载中…</text>
		</view>

		<view v-else-if="demands.length === 0" class="empty-box">
			<text class="empty-title">暂无进行中的需求</text>
			<text class="empty-desc">发布需求并通过审核后，即可在这里发起 AI 匹配</text>
			<button class="primary-btn" size="mini" @click="goPostDemand">去发布需求</button>
		</view>

		<block v-else>
			<view v-for="d in demands" :key="d.id" class="card">
				<view class="card__head">
					<text class="card__title">{{ d.title }}</text>
					<text class="tag">{{ d.statusLabel }}</text>
				</view>
				<text class="card__desc">{{ d.demandDesc || '（无需求说明）' }}</text>
				<view class="card__foot">
					<button class="primary-btn" size="mini" :disabled="d._taskLoading" @click="onCreateTask(d)">
						{{ d._taskLoading ? '提交中…' : '发起 AI 匹配' }}
					</button>
				</view>

				<view v-if="d._task" class="task-box">
					<view class="task-box__head">
						<text class="task-label">匹配任务 #{{ d._task.taskId }}</text>
						<text :class="'task-status task-status--' + d._task.status">{{ statusText(d._task.status) }}</text>
					</view>

					<view v-if="d._task.status === 'queued'" class="task-hint">
						<text>任务已排队 · AI 服务接入中，结果生成后将在此展示</text>
					</view>
					<view v-else-if="d._task.status === 'running'" class="task-hint">
						<text>AI 正在匹配，请稍候…</text>
					</view>
					<view v-else-if="d._task.status === 'failed'" class="task-hint task-hint--fail">
						<text>匹配失败：{{ d._task.failReason || '未知原因，请稍后重试' }}</text>
					</view>
					<block v-else-if="d._task.status === 'succeeded'">
						<view v-if="!d._task.results || d._task.results.length === 0" class="task-hint">
							<text>本轮未匹配到合适成果，可完善需求说明后重新发起</text>
						</view>
						<view
							v-for="(r, i) in d._task.results"
							:key="i"
							class="match-item"
							@click="openResult(r)"
						>
							<view class="match-item__head">
								<text class="match-item__title">{{ r.achievementTitle }}</text>
								<text class="match-item__score">{{ r.score }} 分</text>
							</view>
							<text v-if="r.orgName" class="match-item__org">{{ r.orgName }}</text>
							<view v-if="r.matchReasons && r.matchReasons.length" class="match-item__reasons">
								<text v-for="(reason, j) in r.matchReasons" :key="j" class="reason-chip">{{ reason }}</text>
							</view>
						</view>
					</block>
				</view>
			</view>
		</block>

		<!-- 底部导航（分包业务壳统一 tab：首页 / AI匹配 / 我的） -->
		<AppTabbar active="ai" />
	</view>
</template>

<script>
	import AppTabbar from '../../components/app-tabbar.vue'
	import { getMyDemands, toDemandCard } from '../../api/demand.js'
	import {
		createMatchTask,
		getMatchTask,
		isTerminalStatus,
		POLL_INTERVAL_MS,
		POLL_MAX_MS
	} from '../../api/ai.js'
	import HostBridge from '../../../../host/host-bridge.js'

	/** 可发起匹配的需求状态（draft/待审/驳回等不可见成果，不参与匹配） */
	const ACTIVE_STATUSES = ['published', 'matched']

	const STATUS_TEXT = {
		queued: '排队中',
		running: '匹配中',
		succeeded: '已完成',
		failed: '失败'
	}

	export default {
		components: {
			AppTabbar,
		},
		data() {
			return {
				loading: false,
				demands: []
			}
		},
		onShow() {
			this.loadDemands()
		},
		onHide() {
			this.stopAllPolling()
		},
		onUnload() {
			this.stopAllPolling()
		},
		methods: {
			async loadDemands() {
				this.loading = true
				try {
					const data = await getMyDemands({ page: 1, pageSize: 50 })
					const rows = (data.list || [])
						.map(toDemandCard)
						.filter((d) => ACTIVE_STATUSES.indexOf(d.status) >= 0)
					rows.forEach((d) => {
						d._task = null
						d._taskLoading = false
						d._timer = null
					})
					this.stopAllPolling()
					this.demands = rows
				} catch (e) {
					console.error('[ai-match] loadDemands failed:', e)
					this.stopAllPolling()
					this.demands = []
					uni.showToast({ title: (e && e.message) || '需求加载失败', icon: 'none' })
				} finally {
					this.loading = false
				}
			},
			goPostDemand() {
				HostBridge.navigate('pages/post-demand/post-demand')
			},
			statusText(status) {
				return STATUS_TEXT[status] || status
			},
			openResult(r) {
				HostBridge.navigate('pages/achievement-detail/achievement-detail', { id: r.achievementId })
			},
			async onCreateTask(d) {
				if (d._taskLoading) return
				d._taskLoading = true
				try {
					const task = await createMatchTask(d.id)
					d._task = task
					if (!isTerminalStatus(task.status)) {
						this.startPolling(d)
					}
				} catch (e) {
					console.error('[ai-match] createMatchTask failed:', e)
					uni.showToast({ title: (e && e.message) || '发起失败', icon: 'none' })
				} finally {
					d._taskLoading = false
				}
			},
			startPolling(d) {
				this.stopPolling(d)
				const startedAt = Date.now()
				const taskId = d._task.taskId
				d._timer = setInterval(async () => {
					try {
						const task = await getMatchTask(taskId)
						if (task && task.taskId === taskId) {
							d._task = task
						}
						if (!d._task || isTerminalStatus(d._task.status) || Date.now() - startedAt > POLL_MAX_MS) {
							this.stopPolling(d)
						}
					} catch (e) {
						// 轮询失败（网络抖动等）：停止本轮轮询，保留最后已知状态
						this.stopPolling(d)
					}
				}, POLL_INTERVAL_MS)
			},
			stopPolling(d) {
				if (d._timer) {
					clearInterval(d._timer)
					d._timer = null
				}
			},
			stopAllPolling() {
				this.demands.forEach((d) => this.stopPolling(d))
			}
		}
	}
</script>

<style>
	.page {
		min-height: 100vh;
		background-color: #f5f6f8;
		padding: 24rpx;
		padding-bottom: calc(60rpx + env(safe-area-inset-bottom));
		box-sizing: border-box;
	}

	.header {
		padding: 16rpx 8rpx 24rpx;
	}

	.header__title {
		display: block;
		font-size: 38rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.header__desc {
		display: block;
		margin-top: 10rpx;
		font-size: 26rpx;
		color: #888888;
	}

	.card {
		background-color: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 28rpx;
		margin-bottom: 24rpx;
	}

	.card__head {
		display: flex;
		flex-direction: row;
		align-items: flex-start;
		margin-bottom: 16rpx;
	}

	.card__title {
		flex: 1;
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
		line-height: 1.4;
		padding-right: 16rpx;
	}

	.tag {
		flex-shrink: 0;
		font-size: 22rpx;
		color: #2b73f8;
		background: rgba(43, 115, 248, 0.1);
		border-radius: 8rpx;
		padding: 4rpx 12rpx;
	}

	.card__desc {
		display: block;
		font-size: 26rpx;
		color: #555555;
		line-height: 1.6;
	}

	.card__foot {
		margin-top: 20rpx;
		display: flex;
		justify-content: flex-end;
	}

	.primary-btn {
		background-color: #2b73f8 !important;
		color: #ffffff !important;
		font-size: 26rpx !important;
		border-radius: 8rpx !important;
		margin: 0;
		padding: 0 28rpx;
		line-height: 60rpx;
	}

	.task-box {
		margin-top: 24rpx;
		background-color: #f7f9fc;
		border-radius: 12rpx;
		padding: 24rpx;
	}

	.task-box__head {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 16rpx;
	}

	.task-label {
		font-size: 26rpx;
		font-weight: 600;
		color: #333333;
	}

	.task-status {
		font-size: 22rpx;
		border-radius: 8rpx;
		padding: 4rpx 12rpx;
	}

	.task-status--queued {
		color: #c47b1a;
		background: #fff4e5;
	}

	.task-status--running {
		color: #2b73f8;
		background: rgba(43, 115, 248, 0.1);
	}

	.task-status--succeeded {
		color: #1f9d63;
		background: #e8f7f0;
	}

	.task-status--failed {
		color: #d9534f;
		background: #fdecec;
	}

	.task-hint {
		font-size: 24rpx;
		color: #888888;
		line-height: 1.6;
	}

	.task-hint--fail {
		color: #d9534f;
	}

	.match-item {
		background-color: #ffffff;
		border: 1rpx solid #e8ecf2;
		border-radius: 12rpx;
		padding: 20rpx;
		margin-top: 16rpx;
	}

	.match-item__head {
		display: flex;
		flex-direction: row;
		align-items: flex-start;
		justify-content: space-between;
	}

	.match-item__title {
		flex: 1;
		font-size: 28rpx;
		font-weight: 600;
		color: #1a1a1a;
		line-height: 1.4;
		padding-right: 12rpx;
	}

	.match-item__score {
		flex-shrink: 0;
		font-size: 26rpx;
		font-weight: 600;
		color: #2b73f8;
	}

	.match-item__org {
		display: block;
		margin-top: 8rpx;
		font-size: 24rpx;
		color: #666666;
	}

	.match-item__reasons {
		margin-top: 12rpx;
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
	}

	.reason-chip {
		font-size: 22rpx;
		color: #555555;
		background: #f0f4fa;
		border-radius: 8rpx;
		padding: 4rpx 12rpx;
		margin: 0 8rpx 8rpx 0;
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
		margin-bottom: 28rpx;
	}
</style>
