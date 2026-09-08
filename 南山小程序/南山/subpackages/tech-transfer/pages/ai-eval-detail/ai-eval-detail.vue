<template>
	<view class="page">
		<!-- 初始加载 -->
		<view v-if="loading" class="state-section">
			<text class="state-title">加载中…</text>
		</view>

		<!-- 加载失败 -->
		<view v-else-if="loadError" class="state-section">
			<text class="state-title">评估任务加载失败</text>
			<text class="state-desc">{{ loadError }}</text>
			<button class="primary-btn" size="mini" @click="fetchTask">重新加载</button>
		</view>

		<block v-else-if="task">
			<!-- 任务头 -->
			<view class="section">
				<text class="title">{{ achievementTitle }}</text>
				<view class="task-meta">
					<text class="task-id">评估任务 #{{ task.taskId }}</text>
					<text :class="'task-status task-status--' + task.status">{{ statusText }}</text>
				</view>
				<text v-if="task.createdAt" class="created-at">发起时间：{{ task.createdAt }}</text>
			</view>

			<!-- 排队中：worker 未接入前任务保持 queued，不展示任何假结果 -->
			<view v-if="task.status === 'queued'" class="section state-section">
				<text class="state-title">排队中</text>
				<text class="state-desc">AI 服务接入中，任务将在排队后自动执行，结果生成后在此展示</text>
			</view>

			<!-- 处理中 -->
			<view v-else-if="task.status === 'running'" class="section state-section">
				<text class="state-title">评估处理中</text>
				<text class="state-desc">AI 正在对成果进行四维评估，请稍候…</text>
			</view>

			<!-- 失败：failReason + 重新发起 -->
			<view v-else-if="task.status === 'failed'" class="section state-section">
				<text class="state-title">评估失败</text>
				<text class="fail-reason">{{ task.failReason || '未知原因，请稍后重试' }}</text>
				<button v-if="canRetry" class="primary-btn" size="mini" :disabled="retrying" @click="onRetry">
					{{ retrying ? '提交中…' : '重新发起评估' }}
				</button>
				<text v-else class="state-desc">可回到「我的成果」中对成果重新发起评估</text>
			</view>

			<!-- 完成：四维评分 / 总分 / 结论 / 亮点 -->
			<block v-else>
				<view v-if="!evaluation" class="section state-section">
					<text class="state-title">结果生成中</text>
					<text class="state-desc">任务已完成，评估结果暂未生成，可稍后重新查看或重新发起</text>
					<button v-if="canRetry" class="primary-btn" size="mini" :disabled="retrying" @click="onRetry">
						{{ retrying ? '提交中…' : '重新发起评估' }}
					</button>
				</view>
				<block v-else>
					<view class="section score-section">
						<view class="total-wrap">
							<text class="total-label">综合评分</text>
							<text class="total-num">{{ evaluation.totalScore }}</text>
							<text class="total-unit">/ 100</text>
						</view>
						<text class="tip">四维评分由 AI 评估任务生成</text>
					</view>

					<view class="section">
						<text class="section-title">四维评分</text>
						<view v-for="dim in dims" :key="dim.key" class="dim-item">
							<view class="dim-top">
								<text class="dim-label">{{ dim.label }}</text>
								<text class="dim-score">{{ dim.score }}</text>
							</view>
							<view class="bar-track">
								<view class="bar-fill" :style="{ width: dim.score + '%' }"></view>
							</view>
						</view>
					</view>

					<view v-if="evaluation.conclusion" class="section">
						<text class="section-title">简要结论</text>
						<text class="conclusion">{{ evaluation.conclusion }}</text>
					</view>

					<view v-if="evaluation.highlights && evaluation.highlights.length" class="section">
						<text class="section-title">亮点优势</text>
						<view v-for="(item, index) in evaluation.highlights" :key="index" class="highlight">
							<text class="highlight__dot">{{ index + 1 }}</text>
							<text class="highlight__text">{{ item }}</text>
						</view>
					</view>
				</block>
			</block>

			<view v-if="dockId" class="actions">
				<button class="btn" @click="goDock">查看成果对接详情</button>
			</view>
		</block>
	</view>
</template>

<script>
	import {
		getEvaluationTask,
		createEvaluationTask,
		isTerminalStatus,
		POLL_INTERVAL_MS,
		POLL_MAX_MS
	} from '../../api/ai.js'
	import HostBridge from '../../../../host/host-bridge.js'

	const SCORE_DIMENSIONS = [
		{ key: 'techFeature', label: '技术特点' },
		{ key: 'applyScope', label: '应用范围' },
		{ key: 'maturity', label: '成熟度' },
		{ key: 'cooperation', label: '合作可行性' }
	]

	const STATUS_TEXT = {
		queued: '排队中',
		running: '评估中',
		succeeded: '已完成',
		failed: '失败'
	}

	export default {
		data() {
			return {
				taskId: null,
				achievementId: null,
				task: null,
				loading: false,
				loadError: '',
				retrying: false,
				timer: null,
				pollStartedAt: 0
			}
		},
		computed: {
			statusText() {
				return STATUS_TEXT[this.task.status] || this.task.status
			},
			evaluation() {
				return (this.task && this.task.evaluation) || null
			},
			achievementTitle() {
				if (this.evaluation && this.evaluation.achievementTitle) {
					return this.evaluation.achievementTitle
				}
				return '成果 AI 评估'
			},
			dims() {
				if (!this.evaluation) return []
				const scores = this.evaluation.scores || {}
				return SCORE_DIMENSIONS.map((d) => ({
					key: d.key,
					label: d.label,
					score: Math.round(Number(scores[d.key]) || 0)
				}))
			},
			// 失败/成功但结果缺失时可重新发起（需知道成果 id）
			canRetry() {
				if (!this.task || !this.achievementId) return false
				if (this.task.status === 'failed') return true
				return this.task.status === 'succeeded' && !this.evaluation
			},
			dockId() {
				return this.achievementId || (this.evaluation && this.evaluation.achievementId) || null
			}
		},
		onLoad(options) {
			const taskId = parseInt(options.taskId, 10)
			this.achievementId = parseInt(options.achievementId, 10) || null
			if (!taskId) {
				uni.showToast({ title: '缺少评估任务参数', icon: 'none' })
				setTimeout(() => uni.navigateBack(), 1200)
				return
			}
			this.taskId = taskId
			this.fetchTask()
		},
		onShow() {
			// 页面回前台：任务未终态且轮询已停（如轮询出错）时恢复
			if (this.taskId && this.task && !isTerminalStatus(this.task.status) && !this.timer) {
				this.fetchTask()
			}
		},
		onHide() {
			this.stopPolling()
		},
		onUnload() {
			this.stopPolling()
		},
		methods: {
			async fetchTask() {
				this.loading = !this.task
				this.loadError = ''
				try {
					const task = await getEvaluationTask(this.taskId)
					this.task = task
					if (!isTerminalStatus(task.status)) {
						this.startPolling()
					}
				} catch (e) {
					console.error('[ai-eval-detail] getEvaluationTask failed:', e)
					this.loadError = (e && e.message) || '网络异常，请稍后重试'
				} finally {
					this.loading = false
				}
			},
			startPolling() {
				this.stopPolling()
				this.pollStartedAt = Date.now()
				const taskId = this.taskId
				this.timer = setInterval(async () => {
					try {
						const task = await getEvaluationTask(taskId)
						if (task && task.taskId === taskId) {
							this.task = task
						}
						if (!this.task || isTerminalStatus(this.task.status) || Date.now() - this.pollStartedAt > POLL_MAX_MS) {
							this.stopPolling()
						}
					} catch (e) {
						// 轮询失败（网络抖动等）：停止本轮轮询，保留最后已知状态
						this.stopPolling()
					}
				}, POLL_INTERVAL_MS)
			},
			stopPolling() {
				if (this.timer) {
					clearInterval(this.timer)
					this.timer = null
				}
			},
			async onRetry() {
				if (!this.achievementId || this.retrying) return
				this.retrying = true
				try {
					this.stopPolling()
					const task = await createEvaluationTask(this.achievementId)
					this.taskId = task.taskId
					this.task = task
					if (!isTerminalStatus(task.status)) {
						this.startPolling()
					}
					uni.showToast({ title: '已重新发起评估', icon: 'none' })
				} catch (e) {
					console.error('[ai-eval-detail] retry failed:', e)
					uni.showToast({ title: (e && e.message) || '重新发起失败', icon: 'none' })
				} finally {
					this.retrying = false
				}
			},
			goDock() {
				const id = this.dockId
				if (!id) {
					uni.showToast({ title: '暂无可查看的成果', icon: 'none' })
					return
				}
				HostBridge.navigate('pages/dock-detail/dock-detail', { type: 'result', id })
			}
		}
	}
</script>

<style>
	.page {
		min-height: 100vh;
		background: #f5f6f8;
		padding: 24rpx;
		padding-bottom: calc(60rpx + env(safe-area-inset-bottom));
		box-sizing: border-box;
	}

	.section {
		background: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 28rpx;
		margin-bottom: 20rpx;
	}

	.title {
		display: block;
		font-size: 34rpx;
		font-weight: 600;
		color: #1a1a1a;
		line-height: 1.4;
		margin-bottom: 12rpx;
	}

	.task-meta {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
	}

	.task-id {
		font-size: 24rpx;
		color: #888888;
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

	.created-at {
		display: block;
		margin-top: 10rpx;
		font-size: 22rpx;
		color: #bbbbbb;
	}

	.state-section {
		text-align: center;
		padding: 60rpx 40rpx;
		display: flex;
		flex-direction: column;
		align-items: center;
	}

	.state-title {
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.state-desc {
		margin-top: 14rpx;
		font-size: 24rpx;
		color: #888888;
		line-height: 1.6;
	}

	.fail-reason {
		margin-top: 14rpx;
		font-size: 26rpx;
		color: #d9534f;
		line-height: 1.6;
	}

	.score-section {
		text-align: center;
		padding: 36rpx 28rpx;
	}

	.total-wrap {
		display: flex;
		flex-direction: row;
		align-items: baseline;
		justify-content: center;
	}

	.total-label {
		font-size: 28rpx;
		color: #666666;
		margin-right: 16rpx;
	}

	.total-num {
		font-size: 72rpx;
		font-weight: 700;
		color: #2b73f8;
		line-height: 1;
	}

	.total-unit {
		margin-left: 8rpx;
		font-size: 26rpx;
		color: #999999;
	}

	.tip {
		display: block;
		margin-top: 16rpx;
		font-size: 22rpx;
		color: #bbbbbb;
	}

	.section-title {
		display: block;
		font-size: 30rpx;
		font-weight: 600;
		color: #1a1a1a;
		margin-bottom: 20rpx;
	}

	.dim-item {
		margin-bottom: 22rpx;
	}

	.dim-item:last-child {
		margin-bottom: 0;
	}

	.dim-top {
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		margin-bottom: 10rpx;
	}

	.dim-label {
		font-size: 26rpx;
		color: #555555;
	}

	.dim-score {
		font-size: 26rpx;
		font-weight: 600;
		color: #2b73f8;
	}

	.bar-track {
		height: 12rpx;
		background: #eef2f7;
		border-radius: 12rpx;
		overflow: hidden;
	}

	.bar-fill {
		height: 100%;
		background: #2b73f8;
		border-radius: 12rpx;
	}

	.conclusion {
		display: block;
		font-size: 28rpx;
		color: #333333;
		line-height: 1.6;
	}

	.highlight {
		display: flex;
		flex-direction: row;
		align-items: flex-start;
		margin-bottom: 16rpx;
	}

	.highlight:last-child {
		margin-bottom: 0;
	}

	.highlight__dot {
		width: 36rpx;
		height: 36rpx;
		line-height: 36rpx;
		text-align: center;
		border-radius: 18rpx;
		background: rgba(43, 115, 248, 0.12);
		color: #2b73f8;
		font-size: 22rpx;
		font-weight: 600;
		flex-shrink: 0;
		margin-right: 14rpx;
		margin-top: 2rpx;
	}

	.highlight__text {
		flex: 1;
		font-size: 26rpx;
		color: #444444;
		line-height: 1.5;
	}

	.primary-btn {
		margin-top: 28rpx;
		background: #2b73f8 !important;
		color: #ffffff !important;
		font-size: 26rpx !important;
		border-radius: 8rpx !important;
	}

	.actions {
		margin-top: 8rpx;
	}

	.btn {
		background: #2b73f8 !important;
		color: #ffffff !important;
		border-radius: 12rpx;
		font-size: 30rpx;
		font-weight: 600;
	}
</style>
