<template>
	<view class="page">
		<view v-if="!aiEnabled" class="coming-soon">
			<text class="coming-soon__title">功能即将开放</text>
			<text class="coming-soon__desc">智能评估正在建设中，敬请期待。</text>
		</view>
		<block v-else>
		<AiGeneratedMark class="page-mark" :notice="evalNotice" />
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

			<!-- 排队中：任务创建后由服务端后台自动执行，不展示任何假结果 -->
			<view v-if="task.status === 'queued'" class="section state-section">
				<text class="state-title">排队中</text>
				<text class="state-desc">任务已受理，AI 正在排队处理，结果生成后在此展示</text>
			</view>

			<!-- 处理中 -->
			<view v-else-if="task.status === 'running'" class="section state-section">
				<text class="state-title">评估处理中</text>
				<text class="state-desc">AI 正在对成果进行多维评估，请稍候…</text>
			</view>

			<!-- 失败/排队超时（stale）：failReason + 重新发起 -->
			<view v-else-if="task.status === 'failed' || task.status === 'stale'" class="section state-section">
				<text class="state-title">{{ failTitle }}</text>
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
						<view class="score-badges">
							<text v-if="evaluation.ratingLabel" class="rating-chip">{{ evaluation.ratingLabel }}</text>
							<text v-if="evaluation.starScore != null" class="star-chip">{{ evaluation.starScore }} / 5.0 星</text>
						</view>
						<text class="tip">AI 多维评分由人工智能生成，仅供参考</text>
					</view>

					<!-- 能力雷达图（多维评分可视化） -->
					<view v-if="dims.length >= 3" class="section">
						<view class="section-head">
							<text class="section-title">能力雷达图</text>
							<AiGeneratedMark mode="badge" />
						</view>
						<view class="radar-wrap">
							<canvas canvas-id="evalRadar" id="evalRadar" class="radar-canvas"></canvas>
						</view>
					</view>

					<!-- 分维度评分卡片（多维含权重/五分制/评语；旧数据为四维卡片） -->
					<view class="section">
						<text class="section-title">{{ dimsTitle }}</text>
						<view class="dim-grid">
							<view v-for="dim in dims" :key="dim.key" class="dim-card">
								<view class="dim-card__head">
									<text class="dim-card__label">{{ dim.label }}</text>
									<text v-if="dim.weightText" class="dim-card__weight">{{ dim.weightText }}</text>
								</view>
								<view class="dim-card__score-row">
									<text class="dim-card__score">{{ dim.score }}</text>
									<text v-if="dim.star != null" class="dim-card__star">{{ dim.star }} 星</text>
								</view>
								<view class="bar-track">
									<view class="bar-fill" :style="{ width: dim.score + '%' }"></view>
								</view>
								<text v-if="dim.comment" class="dim-card__comment">{{ dim.comment }}</text>
							</view>
						</view>
					</view>

					<view v-if="evaluation.conclusion" class="section">
						<view class="section-head">
							<text class="section-title">简要结论</text>
							<AiGeneratedMark mode="badge" />
						</view>
						<text class="conclusion">{{ evaluation.conclusion }}</text>
					</view>

					<view v-if="evaluation.highlights && evaluation.highlights.length" class="section">
						<text class="section-title">亮点优势</text>
						<view v-for="(item, index) in evaluation.highlights" :key="index" class="highlight">
							<text class="highlight__dot">{{ index + 1 }}</text>
							<text class="highlight__text">{{ item }}</text>
						</view>
					</view>

					<!-- AI 评价报告分节 -->
					<view v-if="reportSections.length" class="section">
						<view class="section-head">
							<text class="section-title">AI 评价报告</text>
							<AiGeneratedMark mode="badge" />
						</view>
						<view v-for="(sec, sIndex) in reportSections" :key="sIndex" class="report-sec">
							<text class="report-sec__heading">{{ sec.heading }}</text>
							<text class="report-sec__content">{{ sec.content }}</text>
						</view>
					</view>
				</block>
			</block>

			<!-- 历史评估记录 -->
		<view v-if="history.length" class="section">
			<view class="section-head">
				<text class="section-title">历史评估记录</text>
				<text class="history-count">共 {{ historyTotal }} 次</text>
			</view>
			<view v-for="item in history" :key="item.evaluationId" class="history-item" @click="openHistoryTask(item)">
				<view class="history-item__score-wrap">
					<text class="history-item__score">{{ item.totalScore }}</text>
					<text class="history-item__unit">分</text>
				</view>
				<view class="history-item__info">
					<text v-if="item.ratingLabel" class="history-item__rating">{{ item.ratingLabel }}</text>
					<text class="history-item__time">{{ item.createdAt }}</text>
				</view>
			</view>
		</view>

		<view v-if="dockId" class="actions">
			<button v-if="task.status === 'succeeded'" class="btn btn--ghost" :disabled="retrying" @click="onRetry">
				{{ retrying ? '提交中…' : '重新评估' }}
			</button>
				<button class="btn" @click="goDock">查看成果对接详情</button>
			</view>
		</block>
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
	import {
		acknowledgeEval,
		beginEval,
		loadActiveEval,
		saveEvalTask
	} from '../../api/ai-eval-wal.mjs'
	import { AI_EVAL_NOTICE } from '../../api/ai-disclosure.mjs'
	import AiGeneratedMark from '../../components/ai-generated-mark.vue'
	import HostBridge from '../../../../host/host-bridge.js'
	import { AI_FEATURE_ENABLED } from '../../../../config/feature-flags.js'
	import { safeBackWithToast } from '../../utils/nav.mjs'
	import { createPageStateMixin } from '../../api/page-state-cache.mjs'

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
		failed: '失败',
		stale: '排队超时'
	}

	export default {
		components: {
			AiGeneratedMark
		},
		mixins: [createPageStateMixin({
			route: 'pages/ai-eval-detail/ai-eval-detail',
			groups: [{ name: 'task', dataClass: 'detail', fields: ['task'] }],
		})],
		data() {
			return {
				aiEnabled: AI_FEATURE_ENABLED,
				evalNotice: AI_EVAL_NOTICE,
				taskId: null,
				achievementId: null,
				task: null,
				history: [],
				historyTotal: 0,
				stageIndex: 0,
				elapsedSeconds: 0,
				stageTimer: null,
				loading: false,
				loadError: '',
				retrying: false,
				timer: null,
				pollStartedAt: 0
			}
		},
		computed: {
			stageText() {
				const stages = {
					queued: ['任务已进入评估队列', '正在等待 AI 算力调度', '排队即将完成'],
					running: ['AI 正在分析成果', '正在生成评价报告', '正在计算综合评分']
				}
				const list = (this.task && stages[this.task.status]) || stages.running
				return list[this.stageIndex % list.length] + '…'
			},
			statusText() {
				return STATUS_TEXT[this.task.status] || this.task.status
			},
			failTitle() {
				return this.task && this.task.status === 'stale' ? '排队超时' : '评估失败'
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
				if (this.multiDim) {
					// 多维数据：六维 + 权重 + 五分制 + 维度评语
					return this.evaluation.dimensions.map((d) => {
						const value = Math.max(0, Math.min(100, Number(d.score) || 0))
						return {
							key: d.key,
							label: d.label,
							score: Math.round(value),
							value,
							star: d.starScore != null ? d.starScore : null,
							weightText: d.weight != null ? '权重 ' + Math.round(d.weight * 100) + '%' : '',
							comment: d.comment || ''
						}
					})
				}
				// 旧数据：013 四维真实分
				const scores = this.evaluation.scores || {}
				return SCORE_DIMENSIONS.map((d) => {
					const value = Math.max(0, Math.min(100, Number(scores[d.key]) || 0))
					return {
						key: d.key,
						label: d.label,
						score: Math.round(value),
						value,
						star: null,
						weightText: '',
						comment: ''
					}
				})
			},
			// 是否为 enhance 后的多维评价数据
			multiDim() {
				return !!(this.evaluation && Array.isArray(this.evaluation.dimensions) && this.evaluation.dimensions.length)
			},
			dimsTitle() {
				return this.multiDim ? '多维评分' : '四维评分'
			},
			reportSections() {
				const report = (this.evaluation && this.evaluation.report) || []
				return report.filter((sec) => sec && sec.heading && sec.content)
			},
			// 失败/成功但结果缺失时可重新发起（需知道成果 id）
			canRetry() {
				if (!this.task || !this.achievementId) return false
				if (this.task.status === 'failed' || this.task.status === 'stale') return true
				return this.task.status === 'succeeded' && !this.evaluation
			},
			dockId() {
				return this.achievementId || (this.evaluation && this.evaluation.achievementId) || null
			}
		},
		watch: {
			// 轮询/重试拿到结果后重绘雷达图
			evaluation(val) {
				if (val) this.scheduleRadarDraw()
			}
		},
		onLoad(options) {
			if (!this.aiEnabled) {
				uni.setNavigationBarTitle({ title: '南山科转通' })
				return
			}
			const taskId = parseInt(options.taskId, 10)
			this.achievementId = parseInt(options.achievementId, 10) || null
		if (!taskId) {
			safeBackWithToast('缺少评估任务参数', 1200)
			return
		}
			this.taskId = taskId
			// WAL 同步：详情页持有权威 taskId，补全本地未确认的提交记录
			const pendingEval = loadActiveEval(uni)
			if (pendingEval && pendingEval.achievementId === this.achievementId) {
				saveEvalTask(this.achievementId, taskId, uni)
			}
			if (this.shouldRevalidatePageState('task')) this.fetchTask()
			else if (this.task && !isTerminalStatus(this.task.status)) this.startPolling()
			// 页面缓存恢复的任务也可能已含结果
			this.scheduleRadarDraw()
		},
		onShow() {
			if (!this.aiEnabled) return
			// 页面回前台：任务未终态且轮询已停（如轮询出错）时恢复
			if (this.taskId && this.task && !isTerminalStatus(this.task.status) && !this.timer) {
				if (this.shouldRevalidatePageState('task')) this.fetchTask()
				else this.startPolling()
			}
			this.scheduleRadarDraw()
		},
		onHide() {
			this.stopPolling()
		},
		onUnload() {
			this.stopPolling()
		},
		methods: {
			syncProgressTicker() {
				if (this.task && (this.task.status === 'queued' || this.task.status === 'running')) {
					if (!this.stageTimer) {
						this.progressAnchor = Date.now()
						this.stageTimer = setInterval(() => {
							this.stageIndex++
							this.elapsedSeconds = Math.floor((Date.now() - this.progressAnchor) / 1000)
						}, 1000)
					}
				} else if (this.stageTimer) {
					clearInterval(this.stageTimer)
					this.stageTimer = null
				}
			},
			async fetchHistory() {
				try {
					const { getEvaluationHistory } = await import('../../api/ai.js')
					const result = await getEvaluationHistory(this.achievementId)
					this.history = result.list || []
					this.historyTotal = result.total || 0
				} catch (e) {}
			},
			openHistoryTask(item) {
				if (item.taskId && item.taskId !== this.taskId) {
					this.taskId = item.taskId
					this.fetchTask()
				}
			},
			// 结果展示后绘制能力雷达图（H5 / 小程序通用 canvas 旧 API）
			scheduleRadarDraw() {
				this.$nextTick(() => {
					setTimeout(() => this.drawRadar(), 50)
				})
			},
			drawRadar() {
				const dims = this.dims
				if (!this.aiEnabled || dims.length < 3) return
				uni.createSelectorQuery()
					.select('#evalRadar')
					.boundingClientRect((rect) => {
						if (!rect || !rect.width || !rect.height) return
						const ctx = uni.createCanvasContext('evalRadar', this)
						const w = rect.width
						const h = rect.height
						const cx = w / 2
						const cy = h / 2
						const R = Math.min(w, h) / 2 - 28
						const n = dims.length
						const angleAt = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n
						const ratioOf = (d) => Math.max(0, Math.min(1, d.value / 100))
						const pointAt = (i, ratio) => [
							cx + R * ratio * Math.cos(angleAt(i)),
							cy + R * ratio * Math.sin(angleAt(i))
						]
						// 网格：4 圈等比多边形
						const levels = [0.25, 0.5, 0.75, 1]
						ctx.setLineWidth(1)
						ctx.setStrokeStyle('#e3e9f2')
						levels.forEach((level) => {
							ctx.beginPath()
							for (let i = 0; i < n; i++) {
								const p = pointAt(i, level)
								if (i === 0) ctx.moveTo(p[0], p[1])
								else ctx.lineTo(p[0], p[1])
							}
							ctx.closePath()
							ctx.stroke()
						})
						// 轴线
						for (let i = 0; i < n; i++) {
							const p = pointAt(i, 1)
							ctx.beginPath()
							ctx.moveTo(cx, cy)
							ctx.lineTo(p[0], p[1])
							ctx.stroke()
						}
						// 评分多边形
						ctx.beginPath()
						dims.forEach((d, i) => {
							const p = pointAt(i, ratioOf(d))
							if (i === 0) ctx.moveTo(p[0], p[1])
							else ctx.lineTo(p[0], p[1])
						})
						ctx.closePath()
						ctx.setFillStyle('rgba(43, 115, 248, 0.22)')
						ctx.fill()
						ctx.setStrokeStyle('#2b73f8')
						ctx.setLineWidth(2)
						ctx.stroke()
						// 顶点
						ctx.setFillStyle('#2b73f8')
						dims.forEach((d, i) => {
							const p = pointAt(i, ratioOf(d))
							ctx.beginPath()
							ctx.arc(p[0], p[1], 2.5, 0, 2 * Math.PI)
							ctx.fill()
						})
						// 维度标签
						ctx.setFillStyle('#666666')
						ctx.setFontSize(11)
						ctx.setTextAlign('center')
						ctx.setTextBaseline('middle')
						dims.forEach((d, i) => {
							const x = cx + (R + 18) * Math.cos(angleAt(i))
							const y = cy + (R + 18) * Math.sin(angleAt(i))
							ctx.fillText(d.label, x, y)
						})
						ctx.draw()
					})
					.exec()
			},
			async fetchTask() {
				if (!this.aiEnabled) return
				this.loading = !this.task
				this.loadError = ''
				try {
					const task = await getEvaluationTask(this.taskId)
					this.task = task
					this.markPageStateFresh('task')
					if (!isTerminalStatus(task.status)) {
						this.startPolling()
					}
				} catch (e) {
					console.error('[ai-eval-detail] getEvaluationTask failed:', e)
				if (!this.task) this.loadError = (e && e.message) || '网络异常，请稍后重试'
				else uni.showToast({ title: '网络异常，暂显示已缓存结果', icon: 'none' })
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
							this.markPageStateFresh('task')
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
				if (!this.aiEnabled || !this.achievementId || this.retrying) return
				this.retrying = true
				try {
					this.stopPolling()
					const task = await createEvaluationTask(this.achievementId)
					this.taskId = task.taskId
					this.task = task
					this.markPageStateFresh('task')
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

	.coming-soon {
		min-height: 70vh;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 48rpx 24rpx;
		box-sizing: border-box;
	}

	.coming-soon__title {
		font-size: 36rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.coming-soon__desc {
		margin-top: 16rpx;
		font-size: 26rpx;
		color: #888888;
		line-height: 1.5;
		text-align: center;
	}

	.page-mark {
		margin-bottom: 20rpx;
	}

	.section {
		background: #ffffff;
		border-radius: 20rpx;
		border: 1rpx solid #e8ecf2;
		padding: 32rpx;
		margin-bottom: 28rpx;
		box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.04);
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

	.section-head {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 20rpx;
	}

	.section-head .section-title {
		margin-bottom: 0;
	}

	.score-badges {
		display: flex;
		flex-direction: row;
		justify-content: center;
		margin-top: 16rpx;
	}

	.rating-chip {
		font-size: 24rpx;
		font-weight: 600;
		color: #1f9d63;
		background: #e8f7f0;
		border-radius: 8rpx;
		padding: 4rpx 16rpx;
		margin-right: 12rpx;
	}

	.star-chip {
		font-size: 24rpx;
		color: #c47b1a;
		background: #fff4e5;
		border-radius: 8rpx;
		padding: 4rpx 16rpx;
	}

	.radar-wrap {
		display: flex;
		flex-direction: row;
		justify-content: center;
	}

	.radar-canvas {
		width: 100%;
		height: 520rpx;
	}

	.dim-grid {
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
		justify-content: space-between;
	}

	.dim-card {
		width: calc(50% - 10rpx);
		box-sizing: border-box;
		background: #f8fafc;
		border: 1rpx solid #e8ecf2;
		border-radius: 12rpx;
		padding: 20rpx;
		margin-bottom: 16rpx;
	}

	.dim-card__head {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 8rpx;
	}

	.dim-card__label {
		font-size: 26rpx;
		color: #555555;
	}

	.dim-card__weight {
		font-size: 20rpx;
		color: #999999;
	}

	.dim-card__score-row {
		display: flex;
		flex-direction: row;
		align-items: baseline;
		margin-bottom: 10rpx;
	}

	.dim-card__score {
		font-size: 40rpx;
		font-weight: 700;
		color: #2b73f8;
		line-height: 1.1;
	}

	.dim-card__star {
		margin-left: 10rpx;
		font-size: 20rpx;
		color: #c47b1a;
	}

	.dim-card__comment {
		display: block;
		margin-top: 12rpx;
		font-size: 22rpx;
		color: #888888;
		line-height: 1.5;
	}

	.report-sec {
		margin-bottom: 24rpx;
	}

	.report-sec:last-child {
		margin-bottom: 0;
	}

	.report-sec__heading {
		display: block;
		font-size: 26rpx;
		font-weight: 600;
		color: #1a1a1a;
		margin-bottom: 10rpx;
	}

	.report-sec__content {
		display: block;
		font-size: 26rpx;
		color: #444444;
		line-height: 1.7;
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
