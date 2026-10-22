<template>
	<view class="page aie-page">
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

			<!-- 状态区块：queued → running → failed/succeeded 平滑过渡（aie-state） -->
			<transition name="aie-state" mode="out-in">
			<!-- 排队中：任务创建后由服务端后台自动执行，不展示任何假结果 -->
			<view v-if="task.status === 'queued'" key="queued" class="section state-section">
				<view class="aie-stage-dots">
					<view class="aie-dot"></view><view class="aie-dot"></view><view class="aie-dot"></view>
				</view>
				<text class="state-title">排队中</text>
				<text class="state-desc">任务已受理，AI 正在排队处理，结果生成后在此展示</text>
				<view class="aie-progress-shimmer"></view>
			</view>

			<!-- 处理中 -->
			<view v-else-if="task.status === 'running'" key="running" class="section state-section">
				<view class="aie-stage-dots">
					<view class="aie-dot"></view><view class="aie-dot"></view><view class="aie-dot"></view>
				</view>
				<text class="state-title">评估处理中</text>
				<view class="state-desc">
					<!-- 阶段文案换挡：淡出旧文案 / 淡入新文案（aie-stage） -->
					<transition name="aie-stage" mode="out-in">
						<text :key="stageText" class="stage-line">{{ stageText }}</text>
					</transition>
				</view>
				<text v-if="elapsedSeconds > 0" class="elapsed">已耗时 {{ elapsedSeconds }} 秒</text>
				<view class="aie-progress-shimmer"></view>
			</view>

			<!-- 失败/排队超时（stale）：failReason + 重新发起 -->
			<view v-else-if="task.status === 'failed' || task.status === 'stale'" key="failed" class="section state-section">
				<text class="state-title">{{ failTitle }}</text>
				<text class="fail-reason">{{ task.failReason || '未知原因，请稍后重试' }}</text>
				<button v-if="canRetry" class="primary-btn" size="mini" :disabled="retrying" @click="onRetry">
					<view v-if="retrying" class="aie-mini-spin"></view>
					<text>{{ retrying ? '提交中…' : '重新发起评估' }}</text>
				</button>
				<text v-else class="state-desc">可回到「我的成果」中对成果重新发起评估</text>
			</view>

			<!-- 完成：四维评分 / 总分 / 结论 / 亮点 -->
			<view v-else key="done">
				<view v-if="!evaluation" class="section state-section">
					<text class="state-title">结果生成中</text>
					<text class="state-desc">任务已完成，评估结果暂未生成，可稍后重新查看或重新发起</text>
					<button v-if="canRetry" class="primary-btn" size="mini" :disabled="retrying" @click="onRetry">
						<view v-if="retrying" class="aie-mini-spin"></view>
						<text>{{ retrying ? '提交中…' : '重新发起评估' }}</text>
					</button>
				</view>
				<block v-else>
					<view class="section score-section">
						<view class="total-wrap">
							<text class="total-label">综合评分</text>
							<view class="total-main">
								<text class="total-num" :class="{ 'total-num--pop': numPopped }">{{ totalDisplay }}</text>
								<text class="total-unit">/ 100</text>
							</view>
						</view>
						<view class="score-badges">
							<text v-if="evaluation.ratingLabel" class="rating-chip" :class="resultAnim ? 'aie-badge-pop' : ''">{{ evaluation.ratingLabel }}</text>
							<text v-if="evaluation.starScore != null" class="star-chip" :class="resultAnim ? 'aie-badge-pop' : ''">{{ evaluation.starScore }} / 5.0 星</text>
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
							<view v-for="(dim, i) in dims" :key="dim.key" class="dim-card"
								:class="['dim-card--' + scoreLevel(dim.value), resultAnim ? 'aie-card-in' : '']"
								:style="resultAnim ? { animationDelay: (i * 80) + 'ms' } : null">
								<view class="dim-card__head">
									<view class="dim-card__left">
										<text class="dim-card__label">{{ dim.label }}</text>
										<text v-if="dim.weightText" class="dim-card__weight">{{ dim.weightText }}</text>
									</view>
									<view class="dim-card__right">
										<text class="dim-card__score">{{ dimDisplays[i] != null ? dimDisplays[i] : dim.score }}</text>
										<text class="dim-card__score-unit">分</text>
										<text v-if="dim.star != null" class="dim-card__star">{{ dim.star }} 星</text>
									</view>
								</view>
								<view class="bar-track">
									<view class="bar-fill" :style="{ transform: 'scaleX(' + (barsRevealed ? dim.value / 100 : 0) + ')' }"></view>
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
						<text class="conclusion aie-fade-up">{{ evaluation.conclusion }}</text>
						</view>

					<view v-if="evaluation.highlights && evaluation.highlights.length" class="section">
						<text class="section-title">亮点优势</text>
						<view v-for="(item, index) in evaluation.highlights" :key="index" class="highlight"
							:class="resultAnim ? 'aie-card-in' : ''"
							:style="resultAnim ? { animationDelay: (200 + index * 60) + 'ms' } : null">
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
							<text class="report-sec__heading aie-fade-up">{{ sec.heading }}</text>
							<text class="report-sec__content aie-fade-up">{{ sec.content }}</text>
						</view>
						</view>
						</block>
						</view>
						</transition>

						<!-- 流式打字机：SSE 增量实时渲染 LLM 报告原文（done 后换结构化结果） -->
			<view v-if="showStreamPreview" class="section stream-section">
				<view class="section-head">
					<text class="section-title">AI 评价报告</text>
					<AiGeneratedMark mode="badge" />
				</view>
				<view v-for="(sec, sIndex) in streamPreview.sections" :key="'stream-' + sIndex" class="report-sec">
					<text v-if="sec.heading" class="report-sec__heading aie-fade-up">{{ sec.heading }}</text>
					<!-- 增量块渲染：固定边界切块，新块自带一次性 aie-word-in 渐现，旧块不重排不闪烁 -->
					<view class="report-sec__content">
						<text v-for="(chunk, ci) in streamChunks(sec.content)" :key="'c-' + ci" class="aie-word-in">{{ chunk }}</text>
						<text v-if="sIndex === streamPreview.sections.length - 1" class="aie-caret">▍</text>
					</view>
				</view>
				<view v-if="!streamPreview.sections.length && streamPreview.conclusion" class="report-sec__content">
					<text v-for="(chunk, ci) in streamChunks(streamPreview.conclusion)" :key="'cc-' + ci" class="aie-word-in">{{ chunk }}</text>
					<text class="aie-caret">▍</text>
				</view>
				<view v-if="!streamPreview.sections.length && !streamPreview.conclusion" class="report-sec__content">
					<text class="aie-word-in">AI 正在撰写评价报告…</text><text class="aie-caret">▍</text>
				</view>
			</view>

			<!-- 历史评估记录 -->
		<view v-if="history.length" class="section">
			<view class="section-head">
				<text class="section-title">历史评估记录</text>
				<text class="history-count">共 {{ historyTotal }} 次</text>
			</view>
			<view v-for="(item, index) in history" :key="item.evaluationId" class="history-item aie-card-in"
			:style="{ animationDelay: (index * 60) + 'ms' }" @click="openHistoryTask(item)">
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
				<view v-if="retrying" class="aie-mini-spin aie-mini-spin--blue"></view>
				<text>{{ retrying ? '提交中…' : '重新评估' }}</text>
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
	import { openEvalTaskStream, extractStreamData, extractStreamSections } from '../../api/ai-eval-stream.mjs'
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

	// prefers-reduced-motion 用户偏好：为 true 时动画一律降级为静态终态
	// （H5 生效；小程序端无 window，恒为 false，由 CSS 兜底）
	function prefersReducedMotion() {
		try {
			return typeof window !== 'undefined' && typeof window.matchMedia === 'function' &&
				window.matchMedia('(prefers-reduced-motion: reduce)').matches
		} catch (e) {
			return false
		}
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
				progressAnchor: 0,
				stageTimer: null,
				loading: false,
				loadError: '',
				retrying: false,
				timer: null,
				pollStartedAt: 0,
				// SSE 流式打字机（H5）：无 fetch 能力时保持 false，走轮询
				streaming: false,
				streamText: '',
				streamStage: '',
				streamHandle: null,
				// 结果入场动画：数字滚动 / 条形展开 / 卡片 stagger / 徽章 pop
				totalDisplay: 0,
				dimDisplays: [],
				barsRevealed: false,
				numPopped: false,
				resultAnim: false
			}
		},
		computed: {
			stageText() {
				// 优先后端实时阶段回传（evaluator 每个关键阶段写入
				// ai_task.progress_stage，随轮询返回）；后端无值时
				// （旧任务/刚创建）退回本地模拟轮播兜底。
				const current = this.task || {}
				// SSE stage 事件实时性最好，优先于轮询到的 progressStage
				const realStage = this.streamStage || current.progressStage || current.progress_stage
				if (realStage && (current.status === 'running' || current.status === 'queued')) {
					return realStage
				}
				const stages = {
					queued: ['任务已进入评估队列', '正在等待 AI 算力调度', '排队即将完成'],
					running: ['正在读取成果数据', 'AI正在分析技术内容', '正在生成评价报告', '正在计算综合评分', '正在保存评估结果']
				}
				const list = (this.task && stages[this.task.status]) || stages.running
				return list[this.stageIndex % list.length] + '…'
			},
			statusText() {
				return STATUS_TEXT[this.task.status] || this.task.status
			},
			// 流式原文（半截 JSON）容错解析出的可渲染分节
			streamPreview() {
				return extractStreamData(this.streamText)
			},
			// running/queued 且 SSE 流在推送时展示打字机
			showStreamPreview() {
				return !!(this.streaming && this.task &&
					(this.task.status === 'running' || this.task.status === 'queued'))
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
			// 结果到达（流式 done / 轮询 / 缓存恢复）统一编排入场动画；
			// 同内容重复赋值（轮询回灌 / onShow 缓存恢复）按签名去重，不重播
			evaluation(val) {
				if (!val) return
				const sig = JSON.stringify(val)
				if (sig === this._lastEvalSig) return
				this._lastEvalSig = sig
				const animate = !this._skipEntrance
				this._skipEntrance = false
				this.presentResult(animate)
			},
			// 任务状态/进度刷新时同步进度计时器（真实阶段随轮询更新）
			task() {
				this.syncProgressTicker()
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
			else if (this.task && !isTerminalStatus(this.task.status)) this.startRealtime()
			// 缓存恢复的已有结果直接静态呈现，不重播入场动画
			if (this.task && this.task.evaluation) this._skipEntrance = true
			// 页面缓存恢复的任务也可能已含结果
			this.scheduleRadarDraw(false)
		},
		onShow() {
			if (!this.aiEnabled) return
			// 页面回前台：任务未终态且轮询已停（如轮询出错）时恢复
			if (this.taskId && this.task && !isTerminalStatus(this.task.status) && !this.timer && !this.streamHandle) {
				if (this.shouldRevalidatePageState('task')) this.fetchTask()
				else this.startRealtime()
			}
			// 回前台只恢复雷达图终态，不重播生长动画
			this.scheduleRadarDraw(false)
		},
		onHide() {
			this.stopPolling()
			this.stopStream()
			this.stopRadarAnimation()
		},
		onUnload() {
			this.stopPolling()
			this.stopStream()
			this.stopRadarAnimation()
		},
		methods: {
			// 评分分档（维度卡片/进度条配色）：优秀 / 良好 / 一般 / 偏弱
			scoreLevel(value) {
				const n = Number(value) || 0
				if (n >= 85) return 'excellent'
				if (n >= 70) return 'good'
				if (n >= 60) return 'fair'
				return 'weak'
			},
			dimLabel(key) {
				const map = {
					innovation: '创新性', techMaturity: '技术成熟度', marketProspect: '市场前景',
					teamStrength: '团队实力', cooperation: '合作可行性', riskAssessment: '风险评估'
				}
				return map[key] || key
			},
			syncProgressTicker() {
				if (this.task && (this.task.status === 'queued' || this.task.status === 'running')) {
					if (!this.stageTimer) {
						this.progressAnchor = Date.now()
						this.stageTimer = setInterval(() => {
							this.elapsedSeconds = Math.floor((Date.now() - this.progressAnchor) / 1000)
							// 兜底模拟文案每 3 秒推进一档；后端实时阶段到位后 stageIndex 不再参与展示
							this.stageIndex = Math.floor(this.elapsedSeconds / 3)
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
					this.stopStream()
					this.taskId = item.taskId
					this.fetchTask()
				}
			},
			// ---------- 结果入场动画编排（count-up / 条形 / 卡片 / 雷达 / 徽章） ----------
			// 数字滚动（easeOutExpo，rAF）：field 指向 data 里的显示字段（如 totalDisplay）
			countUp(field, from, to, duration = 900, decimals = 0) {
				this._countRafs = this._countRafs || {}
				const key = 'f_' + field
				if (this._countRafs[key]) cancelAnimationFrame(this._countRafs[key])
				const finish = () => {
					this[field] = decimals ? Number(to).toFixed(decimals) : to
				}
				// 减少动画偏好 / 无 rAF 环境（旧小程序）：直接落终值
				if (prefersReducedMotion() || typeof requestAnimationFrame !== 'function') {
					finish()
					return
				}
				const nowMs = () => (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now()
				const start = nowMs()
				const tick = () => {
					const t = Math.min(1, (nowMs() - start) / duration)
					const eased = 1 - Math.pow(2, -10 * t)              // easeOutExpo
					const v = from + (to - from) * (t === 1 ? 1 : eased)
					this[field] = decimals ? v.toFixed(decimals) : Math.round(v)
					if (t < 1) this._countRafs[key] = requestAnimationFrame(tick)
					else finish()
				}
				this._countRafs[key] = requestAnimationFrame(tick)
			},
			// 维度分数滚动：写 dimDisplays[index]，模板里回退显示 dim.score
			countUpDim(index, to, duration = 900) {
				this._countRafs = this._countRafs || {}
				const key = 'dim_' + index
				if (this._countRafs[key]) cancelAnimationFrame(this._countRafs[key])
				if (prefersReducedMotion() || typeof requestAnimationFrame !== 'function') {
					this.dimDisplays[index] = to
					return
				}
				const nowMs = () => (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now()
				const start = nowMs()
				const tick = () => {
					const t = Math.min(1, (nowMs() - start) / duration)
					const eased = 1 - Math.pow(2, -10 * t)
					this.dimDisplays[index] = Math.round(to * (t === 1 ? 1 : eased))
					if (t < 1) this._countRafs[key] = requestAnimationFrame(tick)
					else this.dimDisplays[index] = to
				}
				this._countRafs[key] = requestAnimationFrame(tick)
			},
			// 结果入场时间线（流式 done / 轮询拿到结果后统一编排）：
			// count-up（0ms）→ 条形展开（120ms）→ 卡片 stagger（CSS delay）→ 雷达生长（250ms）→ 数字/徽章 pop（900ms）
			presentResult(animated) {
				const ev = this.evaluation
				if (!ev) return
				const play = !!animated && !prefersReducedMotion()
				const total = Number(ev.totalScore) || 0
				const dimScores = this.dims.map((d) => d.score)
				// 清掉上一轮入场残留定时器，防止旧时间线污染新结果
				;['_entranceT1', '_entranceT2', '_entranceT3'].forEach((k) => {
					if (this[k]) {
						clearTimeout(this[k])
						this[k] = null
					}
				})
				this.barsRevealed = false
				this.resultAnim = false
				this.numPopped = false
				if (!play) {
					// 静态终态：缓存恢复 / prefers-reduced-motion，不重播
					this.totalDisplay = total
					this.dimDisplays = dimScores.slice()
					this.barsRevealed = true
					this.scheduleRadarDraw(false)
					return
				}
				this.totalDisplay = 0
				this.dimDisplays = dimScores.map(() => 0)
				this.resultAnim = true
				this.$nextTick(() => {
					this.countUp('totalDisplay', 0, total, 1000)
					dimScores.forEach((score, i) => this.countUpDim(i, score, 900))
					this._entranceT1 = setTimeout(() => { this.barsRevealed = true }, 120)
					this._entranceT2 = setTimeout(() => { this.scheduleRadarDraw(true) }, 250)
					this._entranceT3 = setTimeout(() => { this.numPopped = true }, 900)
				})
			},
			// 流式增量块渲染：固定边界切块（约 12 字/块），旧块 key 不变不重排不闪烁，
			// 新块自带一次性 aie-word-in 渐现（content_delta 高频回调里零 JS 动画，动画全走 CSS）
			streamChunks(text) {
				const t = String(text || '')
				if (!t) return []
				const chunks = []
				for (let i = 0; i < t.length; i += 12) chunks.push(t.slice(i, i + 12))
				return chunks
			},
			// 结果展示后绘制能力雷达图（H5 / 小程序通用 canvas 旧 API）
			scheduleRadarDraw(animated = false) {
				this.$nextTick(() => {
					setTimeout(() => this.drawRadar(animated), 50)
				})
			},
			stopRadarAnimation() {
				if (this._radarTimer) {
					clearInterval(this._radarTimer)
					this._radarTimer = null
				}
			},
			// animated=true：评分多边形从中心向外生长（30 帧 / 800ms，easeOutCubic）；
			// false：直接终态（页面缓存恢复 / prefers-reduced-motion）
			drawRadar(animated = false) {
				const dims = this.dims
				if (!this.aiEnabled || dims.length < 3) return
				if (prefersReducedMotion()) animated = false
				uni.createSelectorQuery()
					.select('#evalRadar')
					.boundingClientRect((rect) => {
						if (!rect || !rect.width || !rect.height) return
						const ctx = uni.createCanvasContext('evalRadar', this)
						const w = rect.width
						const h = rect.height
						const cx = w / 2
						const cy = h / 2
						const R = Math.min(w, h) / 2 - 46
						const n = dims.length
						const angleAt = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n
						const ratioOf = (d) => Math.max(0, Math.min(1, d.value / 100))
						const pointAt = (i, ratio) => [
							cx + R * ratio * Math.cos(angleAt(i)),
							cy + R * ratio * Math.sin(angleAt(i))
						]
						// 静态层：网格 4 圈等比多边形 + 轴线（canvas 无分层，每帧都要画）
						const drawGrid = () => {
							ctx.setLineWidth(1)
							ctx.setStrokeStyle('#e4ebf6')
							;[0.25, 0.5, 0.75, 1].forEach((level) => {
								ctx.beginPath()
								for (let i = 0; i < n; i++) {
									const p = pointAt(i, level)
									if (i === 0) ctx.moveTo(p[0], p[1])
									else ctx.lineTo(p[0], p[1])
								}
								ctx.closePath()
								ctx.stroke()
							})
							ctx.setStrokeStyle('#e8eef8')
							for (let i = 0; i < n; i++) {
								const p = pointAt(i, 1)
								ctx.beginPath()
								ctx.moveTo(cx, cy)
								ctx.lineTo(p[0], p[1])
								ctx.stroke()
							}
						}
						// 数据层：按进度 k ∈ [0,1] 从中心向外扩展，填充透明度同步渐入
						const drawData = (k) => {
							const pts = dims.map((d, i) => pointAt(i, ratioOf(d) * k))   // 从中心向外生长
							const tracePolygon = () => {
								ctx.beginPath()
								pts.forEach((p, i) => {
									if (i === 0) ctx.moveTo(p[0], p[1])
									else ctx.lineTo(p[0], p[1])
								})
								ctx.closePath()
							}
							ctx.setLineJoin('round')
							// 外发光（低透明度粗描边）→ 半透明填充 → 主描边
							tracePolygon()
							ctx.setStrokeStyle('rgba(43, 115, 248, ' + (0.16 * k).toFixed(3) + ')')
							ctx.setLineWidth(10)
							ctx.stroke()
							ctx.setFillStyle('rgba(43, 115, 248, ' + (0.2 * k).toFixed(3) + ')')
							ctx.fill()
							ctx.setStrokeStyle('#2b73f8')
							ctx.setLineWidth(2)
							ctx.stroke()
							if (k > 0.55) {
								// 顶点圆点（白底蓝环）后段出现
								ctx.setStrokeStyle('#2b73f8')
								ctx.setLineWidth(2)
								pts.forEach((p) => {
									ctx.beginPath()
									ctx.arc(p[0], p[1], 4, 0, 2 * Math.PI)
									ctx.setFillStyle('#ffffff')
									ctx.fill()
									ctx.stroke()
								})
							}
							if (k > 0.75) {
								// 维度标签 + 分值最后出现（canvas 无 alpha 动画，用出现时机模拟）
								ctx.setTextAlign('center')
								ctx.setTextBaseline('middle')
								dims.forEach((d, i) => {
									const x = cx + (R + 22) * Math.cos(angleAt(i))
									const y = cy + (R + 22) * Math.sin(angleAt(i))
									ctx.setFillStyle('#5b6b84')
									ctx.setFontSize(11)
									ctx.fillText(d.label, x, y - 7)
									ctx.setFillStyle('#2b73f8')
									ctx.setFontSize(10)
									ctx.fillText(String(d.score), x, y + 8)
								})
							}
							ctx.draw()
						}
						this.stopRadarAnimation()
						if (!animated) {
							drawGrid()
							drawData(1)
							return
						}
						// 生长动画：30 帧 / 800ms（小程序端逐帧 draw 开销可控），easeOutCubic
						const FRAMES = 30
						const DUR = 800
						let f = 0
						drawGrid()
						drawData(0)
						this._radarTimer = setInterval(() => {
							f += 1
							drawGrid()
							drawData(1 - Math.pow(1 - f / FRAMES, 3))
							if (f >= FRAMES) this.stopRadarAnimation()
						}, DUR / FRAMES)
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
						this.startRealtime()
					}
				} catch (e) {
					console.error('[ai-eval-detail] getEvaluationTask failed:', e)
				if (!this.task) this.loadError = (e && e.message) || '网络异常，请稍后重试'
				else uni.showToast({ title: '网络异常，暂显示已缓存结果', icon: 'none' })
				} finally {
					this.loading = false
				}
			},
			// SSE 流式打字机优先（H5 fetch + ReadableStream）；无能力/失败降级轮询
			startRealtime() {
				if (!this.aiEnabled || !this.taskId) return
				this.stopStream()
				this.streamText = ''
				this.streamStage = ''
				const taskId = this.taskId
				const self = this
				const handle = openEvalTaskStream(taskId, {
					onSnapshot(text) {
						if (self.taskId !== taskId) return
						self.streamText = text || ''
					},
					onContentDelta(delta) {
						if (self.taskId !== taskId) return
						self.streamText += (delta || '')
					},
					onStage(text) {
						if (self.taskId !== taskId) return
						self.streamStage = text || ''
					},
					onDone(payload) {
						if (self.taskId !== taskId) return
						self.stopStream()
						self.applyStreamDone(payload)
					},
					onTimeout() {
						if (self.taskId !== taskId) return
						self.handleStreamFallback()
					},
					onError() {
						if (self.taskId !== taskId) return
						self.handleStreamFallback()
					},
					onFallback() {
						if (self.taskId !== taskId) return
						self.handleStreamFallback()
					}
				})
				if (!handle) {
					// 非 H5 / 无 fetch：降级为既有轮询，契约不变
					this.startPolling()
					return
				}
				this.streamHandle = handle
				this.streaming = true
			},
			// 流中断/超时/异常：转轮询兜底（轮询契约不变）
			handleStreamFallback() {
				this.stopStream()
				if (this.taskId && (!this.task || !isTerminalStatus(this.task.status))) {
					this.startPolling()
				}
			},
			// done 事件：换结构化结果（评分卡片 + 雷达图）
			applyStreamDone(payload) {
				const result = payload && payload.result
				if (result && result.taskId === this.taskId) {
					this.task = result
					this.markPageStateFresh('task')
					this.stopPolling()
					return
				}
				// done 但缺结果（异常收尾）：拉一次任务兜底
				this.fetchTask()
			},
			stopStream() {
				if (this.streamHandle) {
					try {
						this.streamHandle.close()
					} catch (e) {}
					this.streamHandle = null
				}
				this.streaming = false
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
						this.startRealtime()
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
/* ==========================================================================
   AI 评估结果页（ai-eval-detail）· 视觉重构
   - 样式统一收敛在 .aie-page 作用域下，避免 .section/.btn 等通用类名
     在 H5 打包下与其它页面互相污染
   - 色板：主色 #2b73f8 / 深墨 #16233f / 正文 #4a5568 / 弱文 #98a4b8
   - 动效统一 aie- 前缀（本页 style 无 scoped，keyframes 必须防全局冲突）
   ========================================================================== */

/* ---------- 1. 页面容器：顶部淡蓝渐晕 + 柔和底色 ---------- */
.page.aie-page {
	min-height: 100vh;
	box-sizing: border-box;
	padding: 24rpx;
	padding-bottom: calc(60rpx + env(safe-area-inset-bottom));
	background-color: #f2f6fd;
	background-image: linear-gradient(180deg, #e4edff 0%, rgba(228, 237, 255, 0) 460rpx);
}

.aie-page .page-mark {
	margin-bottom: 20rpx;
}

/* ---------- 2. 功能未开放兜底 ---------- */
.aie-page .coming-soon {
	min-height: 70vh;
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	padding: 48rpx 24rpx;
	box-sizing: border-box;
}

.aie-page .coming-soon__title {
	font-size: 36rpx;
	font-weight: 700;
	color: #16233f;
	letter-spacing: 1rpx;
}

.aie-page .coming-soon__desc {
	margin-top: 16rpx;
	font-size: 26rpx;
	color: #98a4b8;
	line-height: 1.6;
	text-align: center;
}

/* ---------- 3. 通用卡片与区块标题 ---------- */
.aie-page .section {
	background: #ffffff;
	border: 1rpx solid rgba(226, 234, 247, 0.9);
	border-radius: 24rpx;
	padding: 32rpx;
	margin-bottom: 24rpx;
	box-shadow: 0 10rpx 30rpx rgba(22, 60, 140, 0.06);
	box-sizing: border-box;
}

/* 区块标题：左侧主色竖条 + 深墨加粗 */
.aie-page .section-title {
	display: block;
	font-size: 30rpx;
	font-weight: 700;
	color: #16233f;
	line-height: 1.35;
	padding-left: 18rpx;
	border-left: 6rpx solid #2b73f8;
	margin-bottom: 24rpx;
	letter-spacing: 1rpx;
}

.aie-page .section-head {
	display: flex;
	flex-direction: row;
	align-items: center;
	justify-content: space-between;
	margin-bottom: 24rpx;
}

.aie-page .section-head .section-title {
	margin-bottom: 0;
}

/* ---------- 4. 任务头 ---------- */
.aie-page .title {
	display: block;
	font-size: 38rpx;
	font-weight: 700;
	color: #16233f;
	line-height: 1.5;
	letter-spacing: 1rpx;
	margin-bottom: 20rpx;
}

.aie-page .task-meta {
	display: flex;
	flex-direction: row;
	align-items: center;
	justify-content: space-between;
}

.aie-page .task-id {
	font-size: 22rpx;
	color: #8593a8;
	background: #f1f5fc;
	border-radius: 999rpx;
	padding: 6rpx 20rpx;
}

.aie-page .task-status {
	font-size: 22rpx;
	font-weight: 600;
	border-radius: 999rpx;
	padding: 6rpx 22rpx;
	transition: background-color 300ms ease, color 300ms ease;
}

.aie-page .task-status--queued {
	color: #c47b1a;
	background: rgba(245, 158, 11, 0.14);
}

.aie-page .task-status--running {
	color: #2b73f8;
	background: rgba(43, 115, 248, 0.12);
}

.aie-page .task-status--succeeded {
	color: #0f9d63;
	background: rgba(22, 179, 120, 0.14);
	animation: aieBadgePop 360ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

.aie-page .task-status--failed {
	color: #d9534f;
	background: rgba(239, 95, 76, 0.13);
}

.aie-page .task-status--stale {
	color: #8a63d2;
	background: rgba(138, 99, 210, 0.13);
}

.aie-page .created-at {
	display: block;
	margin-top: 16rpx;
	font-size: 22rpx;
	color: #a4afc0;
}

/* ---------- 5. 加载 / 失败 / 排队 / 处理中 ---------- */
.aie-page .state-section {
	text-align: center;
	padding: 64rpx 40rpx;
	display: flex;
	flex-direction: column;
	align-items: center;
}

.aie-page .state-title {
	font-size: 32rpx;
	font-weight: 700;
	color: #16233f;
}

.aie-page .state-desc {
	margin-top: 16rpx;
	font-size: 25rpx;
	color: #8593a8;
	line-height: 1.7;
}

.aie-page .elapsed {
	margin-top: 10rpx;
	font-size: 22rpx;
	color: #a4afc0;
	line-height: 1.5;
	font-variant-numeric: tabular-nums;
}

.aie-page .fail-reason {
	margin-top: 16rpx;
	font-size: 26rpx;
	color: #d9534f;
	line-height: 1.7;
	padding: 18rpx 26rpx;
	background: rgba(239, 95, 76, 0.07);
	border-radius: 14rpx;
}

/* ---------- 6. 综合评分 hero：主色渐变卡 + 玻璃徽章 + 装饰光斑 ---------- */
.aie-page .score-section {
	position: relative;
	overflow: hidden;
	padding: 56rpx 32rpx 48rpx;
	border: none;
	border-radius: 28rpx;
	background: linear-gradient(135deg, #2b73f8 0%, #3f83ff 52%, #5aa0ff 100%);
	box-shadow: 0 18rpx 44rpx rgba(43, 115, 248, 0.28);
	text-align: center;
}

/* 装饰光斑（玻璃质感） */
.aie-page .score-section::before,
.aie-page .score-section::after {
	content: '';
	position: absolute;
	border-radius: 50%;
	background: rgba(255, 255, 255, 0.12);
	pointer-events: none;
}

.aie-page .score-section::before {
	width: 320rpx;
	height: 320rpx;
	top: -140rpx;
	right: -90rpx;
}

.aie-page .score-section::after {
	width: 220rpx;
	height: 220rpx;
	bottom: -110rpx;
	left: -60rpx;
	background: rgba(255, 255, 255, 0.08);
}

.aie-page .total-wrap {
	position: relative;
	display: flex;
	flex-direction: column;
	align-items: center;
}

.aie-page .total-label {
	font-size: 26rpx;
	color: rgba(255, 255, 255, 0.86);
	letter-spacing: 8rpx;
	margin-bottom: 12rpx;
}

.aie-page .total-main {
	display: flex;
	flex-direction: row;
	align-items: baseline;
	justify-content: center;
}

.aie-page .total-num {
	font-size: 116rpx;
	font-weight: 800;
	color: #ffffff;
	line-height: 1.05;
	display: inline-block;
	font-variant-numeric: tabular-nums;
	text-shadow: 0 8rpx 24rpx rgba(15, 60, 150, 0.28);
}

.aie-page .total-unit {
	margin-left: 12rpx;
	font-size: 28rpx;
	color: rgba(255, 255, 255, 0.75);
}

.aie-page .score-badges {
	position: relative;
	display: flex;
	flex-direction: row;
	justify-content: center;
	margin-top: 28rpx;
}

/* 玻璃徽章 */
.aie-page .rating-chip,
.aie-page .star-chip {
	font-size: 24rpx;
	font-weight: 600;
	color: #ffffff;
	background: rgba(255, 255, 255, 0.2);
	border: 1rpx solid rgba(255, 255, 255, 0.42);
	border-radius: 999rpx;
	padding: 8rpx 26rpx;
	/* 毛玻璃：H5 生效，小程序端自动降级为半透明底色 */
	backdrop-filter: blur(12rpx);
	-webkit-backdrop-filter: blur(12rpx);
}

.aie-page .rating-chip {
	margin-right: 16rpx;
}

.aie-page .tip {
	position: relative;
	display: block;
	margin-top: 26rpx;
	font-size: 22rpx;
	color: rgba(255, 255, 255, 0.72);
}

/* ---------- 7. 能力雷达图：柔光底板 + 适度留白 ---------- */
.aie-page .radar-wrap {
	display: flex;
	flex-direction: row;
	justify-content: center;
	border-radius: 20rpx;
	background: radial-gradient(circle at 50% 42%, rgba(43, 115, 248, 0.08) 0%, rgba(43, 115, 248, 0) 72%);
}

.aie-page .radar-canvas {
	width: 100%;
	height: 600rpx;
}

/* ---------- 8. 维度评分卡片：全宽行卡 + 分档配色 + 渐变进度条 ---------- */
.aie-page .dim-grid {
	display: flex;
	flex-direction: column;
}

.aie-page .dim-card {
	width: 100%;
	box-sizing: border-box;
	background: linear-gradient(180deg, #fbfdff 0%, #f4f8fe 100%);
	border: 1rpx solid #e6eefb;
	border-radius: 20rpx;
	padding: 26rpx 28rpx;
	margin-bottom: 20rpx;
}

.aie-page .dim-card:last-child {
	margin-bottom: 0;
}

.aie-page .dim-card__head {
	display: flex;
	flex-direction: row;
	align-items: center;
	justify-content: space-between;
	margin-bottom: 18rpx;
}

.aie-page .dim-card__left {
	display: flex;
	flex-direction: row;
	align-items: center;
	min-width: 0;
}

.aie-page .dim-card__label {
	font-size: 28rpx;
	font-weight: 600;
	color: #22314f;
}

.aie-page .dim-card__weight {
	margin-left: 12rpx;
	font-size: 20rpx;
	color: #8593a8;
	background: rgba(133, 147, 168, 0.12);
	border-radius: 8rpx;
	padding: 4rpx 12rpx;
}

.aie-page .dim-card__right {
	display: flex;
	flex-direction: row;
	align-items: baseline;
	flex-shrink: 0;
}

.aie-page .dim-card__score {
	font-size: 46rpx;
	font-weight: 800;
	line-height: 1.1;
	font-variant-numeric: tabular-nums;
}

.aie-page .dim-card__score-unit {
	margin-left: 6rpx;
	font-size: 20rpx;
	color: #98a4b8;
}

.aie-page .dim-card__star {
	margin-left: 14rpx;
	font-size: 20rpx;
	font-weight: 600;
	color: #c47b1a;
	background: rgba(245, 158, 11, 0.12);
	border-radius: 8rpx;
	padding: 4rpx 12rpx;
}

/* 分档配色：优秀 / 良好 / 一般 / 偏弱 */
.aie-page .dim-card--excellent .dim-card__score { color: #16b378; }
.aie-page .dim-card--good .dim-card__score { color: #2b73f8; }
.aie-page .dim-card--fair .dim-card__score { color: #f59e0b; }
.aie-page .dim-card--weak .dim-card__score { color: #ef5f4c; }

.aie-page .dim-card__comment {
	display: block;
	margin-top: 18rpx;
	padding-top: 18rpx;
	border-top: 1rpx dashed rgba(133, 147, 168, 0.28);
	font-size: 24rpx;
	color: #66748c;
	line-height: 1.75;
	text-align: justify;
}

/* 进度条：胶囊轨道 + 分档渐变填充 */
.aie-page .bar-track {
	height: 14rpx;
	background: rgba(43, 115, 248, 0.08);
	border-radius: 999rpx;
	overflow: hidden;
}

.aie-page .bar-fill {
	height: 100%;
	border-radius: 999rpx;
	/* 入场填充：scaleX 从 0 过渡到目标比例（GPU 合成，不动 width） */
	transform: scaleX(0);
	transform-origin: left center;
	transition: transform 800ms cubic-bezier(0.22, 1, 0.36, 1);
}

.aie-page .dim-card--excellent .bar-fill { background: linear-gradient(90deg, #34d399, #16b378); }
.aie-page .dim-card--good .bar-fill { background: linear-gradient(90deg, #5b9bff, #2b73f8); }
.aie-page .dim-card--fair .bar-fill { background: linear-gradient(90deg, #fbbf24, #f59e0b); }
.aie-page .dim-card--weak .bar-fill { background: linear-gradient(90deg, #f8837a, #ef5f4c); }

/* ---------- 9. 简要结论：引用卡（首行缩进 + 左侧主色引条） ---------- */
.aie-page .conclusion {
	display: block;
	font-size: 28rpx;
	color: #2c3e5e;
	line-height: 1.9;
	text-indent: 2em;
	text-align: justify;
	padding: 26rpx 28rpx;
	background: linear-gradient(90deg, rgba(43, 115, 248, 0.08), rgba(43, 115, 248, 0.02));
	border-left: 6rpx solid #2b73f8;
	border-radius: 0 16rpx 16rpx 0;
}

/* ---------- 10. 亮点优势：序号渐变徽标 + 淡蓝条目卡 ---------- */
.aie-page .highlight {
	display: flex;
	flex-direction: row;
	align-items: flex-start;
	margin-bottom: 16rpx;
	padding: 20rpx 22rpx;
	background: linear-gradient(90deg, rgba(43, 115, 248, 0.06), rgba(43, 115, 248, 0.015));
	border-radius: 16rpx;
}

.aie-page .highlight:last-child {
	margin-bottom: 0;
}

.aie-page .highlight__dot {
	width: 40rpx;
	height: 40rpx;
	line-height: 40rpx;
	text-align: center;
	border-radius: 50%;
	background: linear-gradient(135deg, #2b73f8, #5aa0ff);
	box-shadow: 0 6rpx 14rpx rgba(43, 115, 248, 0.28);
	color: #ffffff;
	font-size: 22rpx;
	font-weight: 700;
	flex-shrink: 0;
	margin-right: 16rpx;
	margin-top: 2rpx;
}

.aie-page .highlight__text {
	flex: 1;
	font-size: 26rpx;
	color: #3d4c66;
	line-height: 1.7;
	text-align: justify;
}

/* ---------- 11. AI 评价报告：章节式排版（标题 / 正文分层） ---------- */
.aie-page .report-sec {
	margin-bottom: 32rpx;
}

.aie-page .report-sec:last-child {
	margin-bottom: 0;
}

.aie-page .report-sec__heading {
	display: block;
	font-size: 28rpx;
	font-weight: 700;
	color: #16233f;
	line-height: 1.45;
	margin-bottom: 14rpx;
	padding-left: 18rpx;
	border-left: 6rpx solid #2b73f8;
	letter-spacing: 1rpx;
}

.aie-page .report-sec__content {
	display: block;
	font-size: 27rpx;
	color: #4a5568;
	line-height: 1.95;
	letter-spacing: 0.8rpx;
	text-indent: 2em;
	text-align: justify;
}

/* ---------- 12. 历史评估记录 ---------- */
.aie-page .history-count {
	font-size: 22rpx;
	color: #98a4b8;
}

.aie-page .history-item {
	display: flex;
	flex-direction: row;
	align-items: center;
	justify-content: space-between;
	background: #ffffff;
	border: 1rpx solid #e6eefb;
	border-radius: 20rpx;
	padding: 24rpx 28rpx;
	margin-bottom: 16rpx;
}

.aie-page .history-item:last-child {
	margin-bottom: 0;
}

.aie-page .history-item__score-wrap {
	display: flex;
	flex-direction: row;
	align-items: baseline;
}

.aie-page .history-item__score {
	font-size: 52rpx;
	font-weight: 800;
	color: #2b73f8;
	line-height: 1;
	font-variant-numeric: tabular-nums;
}

.aie-page .history-item__unit {
	margin-left: 8rpx;
	font-size: 22rpx;
	color: #98a4b8;
}

.aie-page .history-item__info {
	display: flex;
	flex-direction: column;
	align-items: flex-end;
}

.aie-page .history-item__rating {
	font-size: 22rpx;
	font-weight: 600;
	color: #0f9d63;
	background: rgba(22, 179, 120, 0.12);
	border-radius: 8rpx;
	padding: 4rpx 14rpx;
	margin-bottom: 12rpx;
}

.aie-page .history-item__time {
	font-size: 22rpx;
	color: #a4afc0;
}

/* ---------- 13. 操作按钮 ---------- */
.aie-page .actions {
	margin-top: 28rpx;
	display: flex;
	flex-direction: column;
	gap: 24rpx;
}

.aie-page .btn {
	background: linear-gradient(135deg, #2b73f8, #4a8cff) !important;
	color: #ffffff !important;
	border: none;
	border-radius: 18rpx;
	font-size: 30rpx;
	font-weight: 600;
	height: 92rpx;
	line-height: 92rpx;
	margin: 0;
	display: inline-flex;
	flex-direction: row;
	align-items: center;
	justify-content: center;
	box-shadow: 0 14rpx 30rpx rgba(43, 115, 248, 0.28);
}

/* 去 uni-button 默认描边 */
.aie-page .btn::after,
.aie-page .primary-btn::after {
	border: none;
}

.aie-page .btn--ghost {
	background: #ffffff !important;
	color: #2b73f8 !important;
	border: 2rpx solid rgba(43, 115, 248, 0.45);
	box-shadow: 0 10rpx 24rpx rgba(43, 115, 248, 0.1);
}

.aie-page .primary-btn {
	margin-top: 32rpx;
	background: linear-gradient(135deg, #2b73f8, #4a8cff) !important;
	color: #ffffff !important;
	font-size: 26rpx !important;
	font-weight: 600;
	border-radius: 999rpx !important;
	padding: 0 40rpx;
	box-shadow: 0 12rpx 26rpx rgba(43, 115, 248, 0.26);
	display: inline-flex;
	flex-direction: row;
	align-items: center;
	justify-content: center;
}

/* ---------- 14. 流式打字机预览区 ---------- */
.aie-page .stream-section {
	border: 1rpx dashed rgba(43, 115, 248, 0.35);
	background: linear-gradient(180deg, rgba(43, 115, 248, 0.04), rgba(43, 115, 248, 0.01));
}

/* ==========================================================================
   AI 评估动效（aie- 前缀：本页 style 无 scoped，keyframes 必须防全局冲突）
   ========================================================================== */

/* —— 流式文字：词级渐现 + 呼吸光标 —— */
@keyframes aieWordIn {
	from { opacity: 0; transform: translateY(6rpx); }
	to   { opacity: 1; transform: translateY(0); }
}

.aie-word-in {
	display: inline-block;
	animation: aieWordIn 220ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes aieFadeUp {
	from { opacity: 0; transform: translateY(12rpx); }
	to   { opacity: 1; transform: translateY(0); }
}

.aie-fade-up {
	animation: aieFadeUp 320ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes aieCaret {
	0%, 100% { opacity: 1; }
	50%      { opacity: 0.3; }
}

.aie-caret {
	display: inline-block;
	margin-left: 2rpx;
	color: #2b73f8;
	animation: aieCaret 900ms ease-in-out infinite;
}

/* —— 评分入场：count-up 到达回弹 / 卡片 stagger / 徽章 pop —— */
@keyframes aieNumPop {
	0%   { transform: scale(1); }
	40%  { transform: scale(1.06); }
	100% { transform: scale(1); }
}

.total-num--pop {
	animation: aieNumPop 320ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes aieBadgePop {
	0%   { transform: scale(0.85); }
	60%  { transform: scale(1.08); }
	100% { transform: scale(1); }
}

.aie-badge-pop {
	display: inline-block;
	animation: aieBadgePop 360ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes aieCardIn {
	from { opacity: 0; transform: translateY(20rpx) scale(0.97); }
	to   { opacity: 1; transform: translateY(0) scale(1); }
}

/* 逐卡错峰由模板 inline animation-delay 提供（80ms / 卡） */
.aie-card-in {
	animation: aieCardIn 360ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

/* —— 状态过渡：queued → running → succeeded/failed —— */
.aie-state-enter-active {
	transition: opacity 260ms ease, transform 260ms cubic-bezier(0.22, 1, 0.36, 1);
}

.aie-state-leave-active {
	transition: opacity 140ms ease, transform 140ms ease;
}

.aie-state-enter-from {
	opacity: 0;
	transform: translateY(16rpx);
}

.aie-state-leave-to {
	opacity: 0;
	transform: translateY(-8rpx);
}

/* 阶段文案换挡（stageText） */
.aie-stage-enter-active {
	transition: opacity 240ms ease, transform 240ms cubic-bezier(0.22, 1, 0.36, 1);
}

.aie-stage-leave-active {
	transition: opacity 120ms ease;
}

.aie-stage-enter-from {
	opacity: 0;
	transform: translateY(8rpx);
}

.aie-stage-leave-to {
	opacity: 0;
}

.stage-line {
	display: block;
}

/* —— 排队/评估中：呼吸灯 dots + 待机 shimmer 条 —— */
.aie-stage-dots {
	display: flex;
	flex-direction: row;
	gap: 12rpx;
	justify-content: center;
	margin: 8rpx 0 20rpx;
}

.aie-dot {
	width: 12rpx;
	height: 12rpx;
	border-radius: 50%;
	background: #2b73f8;
	animation: aieBreathe 1.2s ease-in-out infinite;
}

.aie-dot:nth-child(2) {
	animation-delay: 0.16s;
}

.aie-dot:nth-child(3) {
	animation-delay: 0.32s;
}

@keyframes aieBreathe {
	0%, 100% { transform: scale(0.7); opacity: 0.35; }
	50%      { transform: scale(1);   opacity: 1; }
}

.aie-progress-shimmer {
	width: 60%;
	height: 8rpx;
	margin: 20rpx auto 0;
	border-radius: 999rpx;
	background: rgba(43, 115, 248, 0.1);
	position: relative;
	overflow: hidden;
}

.aie-progress-shimmer::after {
	content: '';
	position: absolute;
	left: 0;
	top: 0;
	right: 0;
	bottom: 0;
	background: linear-gradient(90deg, transparent, #2b73f8, transparent);
	transform: translateX(-100%);
	animation: aieShimmer 1.6s ease infinite;
}

@keyframes aieShimmer {
	to { transform: translateX(100%); }
}

/* —— 按钮 loading spinner —— */
.aie-mini-spin {
	width: 28rpx;
	height: 28rpx;
	margin-right: 10rpx;
	border: 3rpx solid rgba(255, 255, 255, 0.35);
	border-top-color: #ffffff;
	border-radius: 50%;
	box-sizing: border-box;
	animation: aieSpin 0.8s linear infinite;
}

.aie-mini-spin--blue {
	border-color: rgba(43, 115, 248, 0.25);
	border-top-color: #2b73f8;
}

@keyframes aieSpin {
	to { transform: rotate(360deg); }
}

/* —— 微交互：按下反馈（移动端 :active） —— */
.aie-page .history-item,
.aie-page .dim-card {
	transition: transform 150ms cubic-bezier(0.22, 1, 0.36, 1), opacity 150ms ease, background-color 150ms ease;
}

.aie-page .history-item:active,
.aie-page .dim-card:active {
	transform: scale(0.97);
	opacity: 0.88;
}

.aie-page .btn:active,
.aie-page .primary-btn:active {
	transform: scale(0.96);
}

/* 桌面预览 hover（不影响移动端） */
@media (hover: hover) {
	.aie-page .history-item:hover {
		background: #f4f8ff;
		transform: translateY(-2rpx);
		box-shadow: 0 8rpx 22rpx rgba(43, 115, 248, 0.12);
	}
	.aie-page .btn:hover {
		filter: brightness(1.06);
	}
}

/* —— 可访问性：减少动画偏好 → 全部降级为瞬时/静止（JS 侧同步走静态终态） —— */
@media (prefers-reduced-motion: reduce) {
	*, *::before, *::after {
		animation-duration: 0.01ms !important;
		animation-iteration-count: 1 !important;
		transition-duration: 0.01ms !important;
	}
	.aie-progress-shimmer::after {
		animation: none !important;
		opacity: 0.5;
	}
}
</style>
