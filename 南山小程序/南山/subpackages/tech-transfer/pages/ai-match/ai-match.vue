<template>
	<view class="page">
		<view v-if="!aiEnabled" class="coming-soon-page">
			<view class="coming-soon">
				<text class="coming-soon__title">功能即将开放</text>
				<text class="coming-soon__desc">智能匹配正在建设中，敬请期待。</text>
			</view>
			<AppTabbar active="home" />
		</view>
		<block v-else>
		<view class="header">
			<text class="header__title">AI 智能匹配</text>
			<text class="header__desc">对话描述需求，或输入 / 调用技能</text>
			<AiGeneratedMark class="header__mark" />
			<text class="header__desc" @click="clearConversation">清空对话</text>
		</view>

		<scroll-view
			class="chat-scroll"
			scroll-y
			:scroll-into-view="scrollIntoView"
			:scroll-top="scrollTopValue"
			:scroll-with-animation="scrollAnimation"
		>
			<view v-if="chatPreview.collapsed" class="history-fold" @click="historyExpanded = true">
				<text class="history-fold__text">更早的 {{ chatPreview.hiddenCount }} 条对话已折叠，点击展开</text>
			</view>
			<view
				v-else-if="chatPreview.canCollapse"
				class="history-fold history-fold--open"
				@click="historyExpanded = false"
			>
				<text class="history-fold__text">收起较早对话</text>
			</view>
			<view
				v-for="msg in visibleMessages"
				:id="'msg-' + msg.id"
				:key="msg.id"
			>
				<view v-if="msg.type === 'text'" :class="msg.role === 'user' ? 'msg msg--user' : 'msg msg--bot'">
					<AiGeneratedMark v-if="msg.role !== 'user'" mode="badge" />
					<view :class="msg.role === 'user' ? 'bubble bubble--user' : 'bubble bubble--bot'">
						<text class="bubble__text">{{ msg.content }}</text>
					</view>
				</view>

				<view v-else class="msg msg--bot msg--block">
					<AiGeneratedMark mode="badge" />
					<view class="panel">
						<text v-if="msg.content" class="panel__text">{{ msg.content }}</text>

						<view v-if="msg.type === 'demand-empty'" class="panel__actions">
							<button class="primary-btn" size="mini" @click="goPostDemand">去发布需求</button>
						</view>

						<view v-else-if="msg.type === 'demand-picker'">
							<view
								v-for="d in (msg.payload && msg.payload.demands) || []"
								:key="d.id"
								class="pick-item"
								@click="onPickDemand(d)"
							>
								<text class="pick-item__title">{{ d.title }}</text>
								<text class="pick-item__meta">{{ d.statusLabel }} · {{ d.demandDesc || '无需求说明' }}</text>
							</view>
						</view>

						<view v-else-if="msg.type === 'agent-cards'">
							<view
								v-for="(card, i) in (msg.payload && msg.payload.cards) || []"
								:key="i"
								class="agent-card"
								@click="openCard(card)"
							>
								<view class="agent-card__head">
									<text :class="'agent-card__tag agent-card__tag--' + (card.card_type || '')">{{ card.card_type === 'demand' ? '技术需求' : '科技成果' }}</text>
									<text class="agent-card__title">{{ card.title }}</text>
								</view>
								<text v-if="card.organization" class="agent-card__org">{{ card.organization }}</text>
								<view v-if="card.advisorSummary" class="agent-card__advice">
									<text class="agent-card__advice-label">发布资料摘要</text>
									<text class="agent-card__advice-text">{{ card.advisorSummary }}</text>
								</view>
								<text v-else-if="card.description" class="agent-card__desc">{{ card.description }}</text>
								<view v-if="card.advisorInsight" class="agent-card__advice">
									<text class="agent-card__advice-label">AI适配解读（供参考）</text>
									<text class="agent-card__advice-text">{{ card.advisorInsight }}</text>
								</view>
								<text class="agent-card__views">浏览 {{ cardViewCount(card) }} 次</text>
								<button v-if="referenceForCard(msg, card)" size="mini" :disabled="typing" @click.stop="introduceCard(msg, card)">介绍这项</button>

								<view v-if="card.card_type === 'achievement'" class="agent-card__meta">
									<text v-if="card.maturity && card.maturity.label" class="meta-chip">成熟度：{{ card.maturity.label }}</text>
									<text v-if="card.price && card.price.text" class="meta-chip">价格：{{ card.price.text }}</text>
								</view>

								<view v-else-if="card.card_type === 'demand'" class="agent-card__meta">
									<text v-if="card.region" class="meta-chip">地域：{{ card.region }}</text>
									<text v-if="card.budget && card.budget.text" class="meta-chip">预算：{{ card.budget.text }}</text>
								</view>

								<view v-if="card.application_fields && card.application_fields.length" class="agent-card__fields">
									<text v-for="(f, k) in card.application_fields" :key="k" class="field-chip">{{ f }}</text>
								</view>
								<view v-else-if="card.coop_mode && card.coop_mode.length" class="agent-card__fields">
									<text v-for="(c, k) in card.coop_mode" :key="k" class="field-chip">{{ c }}</text>
								</view>

								<view v-if="card.matchReason && card.matchReason.length" class="agent-card__reasons">
									<text v-for="(reason, k) in card.matchReason" :key="k" class="reason-chip">{{ reason }}</text>
								</view>
								<view v-if="card.advisorCautions && card.advisorCautions.length" class="agent-card__advice agent-card__advice--caution">
									<text class="agent-card__advice-label">待确认</text>
									<text v-for="(concern, index) in card.advisorCautions" :key="index" class="agent-card__advice-text">{{ concern }}</text>
								</view>
							</view>
						</view>
					</view>
				</view>
			</view>

			<view v-if="typing" class="msg msg--bot">
				<AiGeneratedMark mode="badge" />
				<view class="bubble bubble--bot bubble--typing">
					<text class="bubble__text">{{ progressText }}</text>
				</view>
			</view>

			<view v-if="showSuggestions" class="suggest-wrap">
				<text class="suggest-label">可以这样问</text>
				<view
					v-for="(item, index) in suggestions"
					:key="index"
					class="suggest-item"
					@click="onSuggest(item)"
				>
					<text class="suggest-text">{{ item }}</text>
				</view>
			</view>

			<view id="msg-bottom" class="scroll-pad"></view>
		</scroll-view>

		<view v-if="skillOptions.length" class="skill-sheet">
			<text class="skill-sheet__label">技能</text>
			<view
				v-for="skill in skillOptions"
				:key="skill.id"
				class="skill-item"
				@click="onPickSkill(skill)"
			>
				<text class="skill-item__cmd">{{ skill.cmd }}</text>
				<view class="skill-item__meta">
					<text class="skill-item__label">{{ skill.label }}</text>
					<text class="skill-item__desc">{{ skill.desc }}</text>
				</view>
			</view>
		</view>

		<view v-if="pendingQueue.length" class="queue-dock">
			<view class="queue-dock__head">
				<text class="queue-dock__title">排队 {{ pendingQueue.length }} 条，生成结束后自动发送</text>
				<text
					v-if="queuePreview.collapsed"
					class="queue-dock__toggle"
					@click="queueExpanded = true"
				>展开</text>
				<text
					v-else-if="pendingQueue.length > queuePreviewCount"
					class="queue-dock__toggle"
					@click="queueExpanded = false"
				>收起</text>
			</view>
			<view
				v-for="item in queuePreview.visible"
				:key="item.id"
				class="queue-item"
			>
				<text class="queue-item__text">{{ item.text }}</text>
				<text class="queue-item__remove" @click.stop="removeQueued(item.id)">取消</text>
			</view>
			<view
				v-if="queuePreview.collapsed"
				class="queue-item queue-item--more"
				@click="queueExpanded = true"
			>
				<text class="queue-item__text">还有 {{ queuePreview.hiddenCount }} 条已折叠</text>
			</view>
		</view>

		<view class="composer">
			<text class="composer__hint">{{ composerHint }}</text>
			<view class="composer__row">
			<input
				class="composer__input"
				type="text"
				:value="inputText"
				placeholder="输入问题，或 / 调用技能"
				confirm-type="send"
				@input="onInput"
				@confirm="onSend"
			/>
			<button class="composer__btn" size="mini" :disabled="!canSend" @click="onSend">{{ sendLabel }}</button>
			</view>
		</view>

		<AppTabbar active="ai" />
		</block>
	</view>
</template>

<script>
	import AppTabbar from '../../components/app-tabbar.vue'
	import AiGeneratedMark from '../../components/ai-generated-mark.vue'
	import { getMyDemands, toDemandCard } from '../../api/demand.js'
	import {
		chatWithAgent,
		matchDemand,
		getChatHistory,
		getCardViewCounts,
		getChatTurn,
		clearChatHistory
	} from '../../api/ai.js'
	import {
		createWelcomeMessage,
		getChatSuggestions,
		createMessage,
		isSlashDraft,
		filterSkills,
		resolveSkillCommand,
		formatAgentReply,
		cardNavigateTarget
	} from '../../api/ai-chat.mjs'
	import {
		CHAT_COLLAPSE_THRESHOLD,
		INFLIGHT_POLL_MS,
		INFLIGHT_WAIT_MS,
		MAX_QUEUE_SIZE,
		QUEUE_PREVIEW_COUNT,
		dequeueMessage,
		enqueueMessage,
		findInflightStatus,
		loadQueueState,
		previewChatMessages,
		previewQueue,
		removeQueueItem,
		saveQueueState
	} from '../../api/ai-chat-queue.mjs'
	import {
		acknowledgeTurn,
		beginTurn,
		loadActiveTurn,
		saveTurnResult,
		saveTurnProgress
	} from '../../api/ai-chat-wal.mjs'
	import { createChatProgress, mergeChatProgress, chatProgressText, cardReference } from '../../api/ai-chat-progress.mjs'
	import { getPageStateScope, createPageStateMixin } from '../../api/page-state-cache.mjs'

// P0-A: 模块级内存缓存（跨页面切换保持数据）
const _chatMemoryCache = new Map()  // scope -> { messages, pendingQueue, inputText, scrollPos }
	import { ensureLoginForDock } from '../../api/user.js'
	import HostBridge from '../../../../host/host-bridge.js'
	import { AI_FEATURE_ENABLED } from '../../../../config/feature-flags.js'
	import { safeNavigateTo } from '../../utils/nav.mjs'

	const SUBPACKAGE_ROOT = '/subpackages/tech-transfer/'

	const ACTIVE_STATUSES = ['published', 'matched']

	function createTurnId() {
		return 'ai_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 12)
	}

	export default {
		mixins: [createPageStateMixin({
			route: 'pages/ai-match/ai-match',
			groups: [{ name: 'chat', dataClass: 'draft', fields: ['messages', 'pendingQueue', 'inputText'] }]
		})],
		components: {
			AppTabbar,
			AiGeneratedMark
		},
	data() {
		return {
			aiEnabled: AI_FEATURE_ENABLED,
			messages: [createWelcomeMessage()],
			suggestions: getChatSuggestions(),
			cardViewCounts: {},
			inputText: '',
			typing: false,
			scrollIntoView: '',
			scrollAnimation: false,
			scrollTopValue: 0,
			pendingQueue: [],
			inflightText: '',
			inflightTurnId: '',
			recoveringTurn: false,
			chatGeneration: null,
			referenceSupported: false,
			chatProgress: null,
			waitNotice: '',
			queueExpanded: false,
			historyExpanded: false,
			waitingDemandPick: false,
			queuePreviewCount: QUEUE_PREVIEW_COUNT
		}
	},
	computed: {
		progressText() {
			return this.waitNotice || chatProgressText(this.chatProgress)
		},
		showSuggestions() {
			return !this.typing && this.messages.length <= 1 && !this.pendingQueue.length
		},
		skillOptions() {
			return isSlashDraft(this.inputText) ? filterSkills(this.inputText) : []
		},
		canSend() {
			return !!(this.inputText || '').trim()
		},
		sendLabel() {
			return this.typing ? '排队' : '发送'
		},
		composerHint() {
			if (this.recoveringTurn) return '正在确认上一条问答结果；后续消息会排队，不会重复发送'
			if (this.typing) return '正在生成中，发送后会排队，结束后自动发出'
			if (this.pendingQueue.length) return '还有排队消息，当前回复结束后会自动发送'
			return '回答由人工智能生成，请注意甄别'
		},
		chatPreview() {
			const preview = previewChatMessages(this.messages, this.historyExpanded)
			return {
				...preview,
				canCollapse: this.historyExpanded && this.messages.length > CHAT_COLLAPSE_THRESHOLD
			}
		},
		visibleMessages() {
			return this.chatPreview.visible
		},
		queuePreview() {
			return previewQueue(this.pendingQueue, this.queueExpanded)
		}
	},
	watch: {
		visibleMessages() {
			this.refreshCardViewCounts()
		}
	},
	onLoad() {
		this._alive = true
		this._visible = true
		this._scope = getPageStateScope(uni)
		this._sessionReady = false
		this._requestInFlight = false
		this._recovering = false
		this._recoveryTimer = null
		if (!this.aiEnabled) {
			uni.setNavigationBarTitle({ title: '南山科转通' })
			return
		}
		this.resumeSession()
	},
	onShow() {
		if (!this.aiEnabled || !this._alive) return
		this._visible = true
		const currentScope = getPageStateScope(uni)
		this.startCardStatsRefresh()
		if (currentScope !== this._scope) {
			this.stopTurnPolling()
			this._scope = currentScope
			this.chatGeneration = null
			this.referenceSupported = false
			this.chatProgress = null
			this.cardViewCounts = {}
			this._sessionReady = false
			this.messages = [createWelcomeMessage()]
			this.pendingQueue = []
			this.inflightText = ''
			this.inflightTurnId = ''
			this.inputText = ''
			this.typing = false
			this.recoveringTurn = false
			this.waitingDemandPick = false
			this.resumeSession()
			return
		}
		if (this._clearingHistory || this._recovering) return
		if (this._requestInFlight) this.stopTurnPolling()
		if (!this._sessionReady) {
			this.resumeSession()
			return
		}
		const activeTurn = loadActiveTurn(uni, this._scope)
		if (activeTurn) {
			this.recoverActiveTurn(activeTurn)
		} else {
			this.restoreScrollPosition()
		}
	},
	onHide() {
		this._visible = false
		this.stopTurnPolling(false)
		this.stopCardStatsRefresh()
		if (!this.aiEnabled) return
		this.persistQueue()
	},
	onUnload() {
		this._alive = false
		this._visible = false
		this.stopTurnPolling()
		this.stopCardStatsRefresh()
		if (this._recoveryTimer) clearTimeout(this._recoveryTimer)
		if (!this.aiEnabled) return
		this.persistQueue()
	},
	methods: {
		stopTurnPolling(invalidate = true) {
			if (invalidate) this._chatRequestVersion = (this._chatRequestVersion || 0) + 1
			if (this._recoveryTimer) clearTimeout(this._recoveryTimer)
			this._recoveryTimer = null
			if (this._pollTimer) clearTimeout(this._pollTimer)
			this._pollTimer = null
			if (this._pollWake) this._pollWake()
			this._pollWake = null
			this._requestInFlight = false
			this._recovering = false
		},
		isCurrentChatRequest(version, scope) {
			return this._alive && (this._chatRequestVersion || 0) === version && this._scope === scope && scope === getPageStateScope(uni)
		},
		acceptChatProgress(response, turnId) {
			if (Number.isSafeInteger(response.generation) && Number.isSafeInteger(this.chatGeneration) && response.generation < this.chatGeneration) return false
			if (!this.chatProgress || this.chatProgress.turnId !== turnId) {
				const active = loadActiveTurn(uni, this._scope)
				this.chatProgress = createChatProgress({ ...active, scope: this._scope, turnId, generation: active?.generation ?? this.chatGeneration, generationConfirmed: active?.generationConfirmed === true || active?.stageSeq >= 0 })
			}
			const next = mergeChatProgress(this.chatProgress, response, getPageStateScope(uni))
			if (next === this.chatProgress) return false
			this.chatProgress = next
			this.referenceSupported = response.referenceSupported === true
			this.chatGeneration = next.generation
			saveTurnProgress(turnId, next, uni, this._scope)
			return true
		},
		referenceForCard(message, card) {
			if (!this.referenceSupported || message.serverGeneration !== this.chatGeneration) return null
			return cardReference(message, card)
		},
		introduceCard(message, card) {
			const reference = this.referenceForCard(message, card)
			if (!reference || this.typing) return
			this.runAgentChat('介绍这项：' + card.title, reference)
		},
		async clearConversation() {
			if (this._clearingHistory) return
			this.stopTurnPolling()
			this._clearingHistory = true
			this._sessionReady = false
			this.typing = true
			const scope = this._scope
			const version = this._chatRequestVersion || 0
			try {
				const result = await clearChatHistory()
				if (!this.isCurrentChatRequest(version, scope)) return
				this.chatGeneration = result.generation ?? null
				this._sessionReady = true
				this.chatProgress = null
				this.waitNotice = ''
				this.messages = [createWelcomeMessage()]
				this.pendingQueue = []
				this.inputText = ''
				this.finishTurn()
			} catch (error) {
				if (this.isCurrentChatRequest(version, scope)) {
					this._sessionReady = true
					uni.showToast({ title: error.message || '清空失败，请稍后重试', icon: 'none' })
					this.typing = !!loadActiveTurn(uni, scope)
					this.scheduleTurnRecovery()
				}
			} finally {
				this._clearingHistory = false
			}
		},
		cardViewCount(card) {
			const value = this.cardViewCounts[card.card_type + ':' + card.id] ?? card.viewCount
			return Number.isSafeInteger(value) && value >= 0 ? value : '—'
		},
		startCardStatsRefresh() {
			this.refreshCardViewCounts()
			if (!this._cardStatsTimer) {
				this._cardStatsTimer = setInterval(() => this.refreshCardViewCounts(), 15000)
			}
		},
		stopCardStatsRefresh() {
			if (this._cardStatsTimer) clearInterval(this._cardStatsTimer)
			this._cardStatsTimer = null
		},
		async refreshCardViewCounts() {
			const scope = this._scope
			if (!this._alive || !this._visible || scope !== getPageStateScope(uni)) return
			const targets = new Map()
			for (const message of this.visibleMessages) {
				for (const card of Array.isArray(message.payload?.cards) ? message.payload.cards : []) {
					if (!card || typeof card !== 'object') continue
					const id = Number(card.id)
					if (!['achievement', 'demand'].includes(card.card_type) || !Number.isSafeInteger(id) || id <= 0) continue
					const key = card.card_type + ':' + id
					targets.set(key, { card_type: card.card_type, id })
				}
			}
			if (!targets.size) return
			const requestId = (this._cardStatsRequestId || 0) + 1
			this._cardStatsRequestId = requestId
			try {
				const counts = {}
				const cards = [...targets.values()]
				for (let offset = 0; offset < cards.length; offset += 50) {
					const batch = cards.slice(offset, offset + 50)
					const batchKeys = new Set(batch.map(card => card.card_type + ':' + card.id))
					const data = await getCardViewCounts(batch)
					if (!this._alive || !this._visible || this._cardStatsRequestId !== requestId || scope !== this._scope || scope !== getPageStateScope(uni)) return
					for (const item of data.list || []) {
						const key = item.card_type + ':' + item.id
						if (batchKeys.has(key) && Number.isSafeInteger(item.viewCount) && item.viewCount >= 0) counts[key] = item.viewCount
					}
				}
				this.cardViewCounts = counts
			} catch {
			}
		},
		persistQueue() {
			if (this._scope !== getPageStateScope(uni)) return
			saveQueueState({
				queue: this.pendingQueue,
				inflight: this.inflightText,
				inflightTurnId: this.inflightTurnId,
				draft: this.inputText,
			}, uni, this._scope)
		},
		async loadHistory() {
			// 从后端回放历史聊天（切页/重登后不丢）。欢迎语前置，历史卡片快照复用
			// 现有 agent-cards 模板渲染，openCard 仍按 card.id 跳最新详情页。
			const requestScope = this._scope
			const requestVersion = this._chatRequestVersion || 0
			try {
				const data = await getChatHistory()
				if (requestScope !== this._scope || requestScope !== getPageStateScope(uni)) return false
				if (requestVersion !== (this._chatRequestVersion || 0)) return false
				if (Number.isSafeInteger(data.generation)) this.chatGeneration = data.generation
				this.referenceSupported = data.referenceSupported === true
				const msgs = (data && data.messages) || []
				const restored = msgs.map((m) => {
					const cards = Array.isArray(m.cards) ? m.cards : null
					return createMessage(m.role === 'user' ? 'user' : 'assistant', m.content || '', {
						id: 'm_' + m.id,
						serverMessageId: m.id,
						serverTurnId: m.turnId,
						serverGeneration: m.generation,
						type: cards && cards.length ? 'agent-cards' : 'text',
						payload: cards && cards.length ? { cards } : null,
					})
				})
				this.messages = [createWelcomeMessage(), ...restored]
				if (restored.length) this.scrollToBottom()
				return true
			} catch (e) {
				// 历史拉取失败时保留页面与 WAL 中已有内容，不覆盖当前会话。
				return false
			}
		},
		ensureLocalUserMessage(text) {
			const last = this.messages[this.messages.length - 1]
			if (last && last.role === 'user' && last.content === text) return
			this.messages.push(createMessage('user', text))
			this.scrollToBottom()
		},
		async presentSavedTurn(turn) {
			if (!turn || !['succeeded', 'failed'].includes(turn.status)) return false
			if (!this._alive || this._scope !== getPageStateScope(uni)) return false
			this.inflightText = turn.message
			this.inflightTurnId = turn.turnId
			const scope = this._scope
			const version = this._chatRequestVersion || 0
			const historyLoaded = await this.loadHistory()
			if (!this.isCurrentChatRequest(version, scope)) return false
			const result = turn.result || {}
			const alreadyShown = result.serverMessageId
				? this.messages.some(message => String(message.serverMessageId) === String(result.serverMessageId))
				: historyLoaded && findInflightStatus(this.messages, turn.message) === 'done'
			if (!alreadyShown) {
				this.ensureLocalUserMessage(turn.message)
				this.pushMessage('assistant', result.content || 'AI 助手暂时不可用，请稍后重试。', {
					type: result.type || 'text',
					payload: result.payload || null,
					serverMessageId: result.serverMessageId,
					serverTurnId: result.serverTurnId,
					serverGeneration: result.serverGeneration,
				})
			}
			acknowledgeTurn(turn.turnId, uni, this._scope)
			this.finishTurn()
			return true
		},
		async saveServerTurn(turn) {
			if (!turn || !['succeeded', 'failed'].includes(turn.status)) return false
			let result
			if (turn.status === 'succeeded') {
				result = formatAgentReply({
					success: true,
					message: turn.reply || '',
					data: Array.isArray(turn.cards) ? turn.cards : [],
				})
				result.serverMessageId = turn.messageId || null
				result.serverTurnId = turn.turnId || null
				result.serverGeneration = turn.generation ?? null
			} else {
				result = {
					content: String(turn.errorMessage || turn.reply || 'AI 助手暂时不可用，请稍后重试。'),
					type: 'text',
					payload: null,
				}
			}
			const saved = saveTurnResult(turn.turnId, result, turn.status, uni, this._scope)
			if (!saved) return false
			return this.presentSavedTurn(loadActiveTurn(uni, this._scope))
		},
		async waitForTurnStatus(turnId, message) {
			const scope = this._scope
			const version = this._chatRequestVersion || 0
			const deadline = Date.now() + INFLIGHT_WAIT_MS
			let nextPollAt = Date.now()
			while (this.isCurrentChatRequest(version, scope) && Date.now() < deadline) {
				if (!this._visible) return 'paused'
				const delay = nextPollAt - Date.now()
				if (delay > 0) await new Promise(resolve => {
					this._pollWake = resolve
					this._pollTimer = setTimeout(() => {
						this._pollTimer = null
						this._pollWake = null
						resolve()
					}, delay)
				})
				if (!this.isCurrentChatRequest(version, scope)) return 'left'
				if (!this._visible) return 'paused'
				try {
					const turn = await getChatTurn(turnId)
					if (!this.isCurrentChatRequest(version, scope) || !this._visible) return 'left'
					if (this.acceptChatProgress(turn, turnId) && ['succeeded', 'failed'].includes(turn.status)) {
						this.inflightText = message
						this.inflightTurnId = turnId
						this.ensureLocalUserMessage(message)
						if (await this.saveServerTurn(turn)) return 'done'
					}
				} catch (e) {
					if (!this.isCurrentChatRequest(version, scope)) return 'left'
					if (e.details?.reason === 'chat_history_cleared') {
						acknowledgeTurn(turnId, uni, scope)
						this.pendingQueue = []
						this.finishTurn()
						await this.loadHistory()
						return 'done'
					}
				}
				nextPollAt = Date.now() + INFLIGHT_POLL_MS
			}
			if (!this.isCurrentChatRequest(version, scope)) return 'left'
			this.waitNotice = '等待时间较长，请稍后回来查看；本轮仍会继续确认。'
			return 'pending'
		},
		scheduleTurnRecovery() {
			if (this._recoveryTimer) clearTimeout(this._recoveryTimer)
			if (!this._alive || !this._visible) return
			this._recoveryTimer = setTimeout(() => {
				this._recoveryTimer = null
				if (!this._alive || !this._visible || this._requestInFlight || this._recovering) return
				const active = loadActiveTurn(uni, this._scope)
				if (active) this.recoverActiveTurn(active)
			}, INFLIGHT_POLL_MS)
		},
		async recoverActiveTurn(turn) {
			if (!turn || !this._alive || !this._visible || this._recovering || this._requestInFlight) return
			const scope = this._scope
			const version = this._chatRequestVersion || 0
			if (turn.status !== 'pending') {
				await this.presentSavedTurn(turn)
				return
			}
			this._recovering = true
			this.waitNotice = ''
			this.recoveringTurn = true
			this.typing = true
			this.inflightText = turn.message
			this.inflightTurnId = turn.turnId
			this.ensureLocalUserMessage(turn.message)
			this.persistQueue()
			try {
				const result = await this.waitForTurnStatus(turn.turnId, turn.message)
				if (result === 'pending' && this._alive) this.scheduleTurnRecovery()
			} finally {
				if (!this.isCurrentChatRequest(version, scope)) return
				this._recovering = false
				const active = loadActiveTurn(uni, this._scope)
				if (this._alive && active && active.turnId === turn.turnId && active.status === 'pending') {
					this.typing = true
					this.recoveringTurn = true
				} else if (this._alive && !this.inflightTurnId) {
					this.pumpQueue()
				}
			}
		},
		async resumeSession() {
			const scope = this._scope
			const version = this._chatRequestVersion || 0
			const saved = loadQueueState(uni, this._scope)
			this.pendingQueue = saved.queue
			if (saved.draft) this.inputText = saved.draft
			this.inflightText = saved.inflight
			this.inflightTurnId = saved.inflightTurnId
			await this.loadHistory()
			if (!this.isCurrentChatRequest(version, scope)) return
			this._sessionReady = true
			const activeTurn = loadActiveTurn(uni, this._scope)
			if (activeTurn) {
					this.inflightText = activeTurn.message
					this.inflightTurnId = activeTurn.turnId
					this.ensureLocalUserMessage(activeTurn.message)
					if (activeTurn.status === 'pending') await this.recoverActiveTurn(activeTurn)
					else await this.presentSavedTurn(activeTurn)
					return
			}
			this.typing = false
			this.recoveringTurn = false
			this.chatProgress = null
			const status = findInflightStatus(this.messages, this.inflightText)
			if (!this.inflightText || status === 'done') {
				this.inflightText = ''
				this.inflightTurnId = ''
				this.typing = false
				this.recoveringTurn = false
				this.chatProgress = null
				this.persistQueue()
				this.pumpQueue()
				return
			}
			const interruptedText = this.inflightText
			if (resolveSkillCommand(interruptedText)?.id === 'match') {
				this.inflightText = ''
				this.persistQueue()
				this.dispatchUserText(interruptedText)
				return
			}
			this.ensureLocalUserMessage(interruptedText)
			this.pushMessage('assistant', '上一版本中断的问答没有可恢复的轮次记录。为避免重复请求，我没有自动重发；如需继续，请手动重新发送。')
			this.inflightText = ''
			this.inflightTurnId = ''
			this.persistQueue()
			this.pumpQueue()
		},
		pumpQueue() {
			if (!this._alive || !this._visible || this.typing || this.waitingDemandPick || this._clearingHistory) return
			const { queue, item } = dequeueMessage(this.pendingQueue)
			if (!item) {
				this.persistQueue()
				return
			}
			this.pendingQueue = queue
			this.persistQueue()
			this.dispatchUserText(item.text)
		},
		finishTurn() {
			this.chatProgress = null
			this.waitNotice = ''
			this.typing = false
			this.recoveringTurn = false
			this.inflightText = ''
			this.inflightTurnId = ''
			this.persistQueue()
			this.scrollToBottom()
			if (this._alive && !this._requestInFlight && !this._recovering) this.pumpQueue()
		},
		removeQueued(id) {
			this.pendingQueue = removeQueueItem(this.pendingQueue, id)
			this.persistQueue()
		},
		onInput(e) {
			this.inputText = e.detail.value
		},
			onSuggest(text) {
				this.inputText = text
				this.onSend()
			},
			onPickSkill(skill) {
				this.inputText = skill.cmd
				this.onSend()
			},
			restoreScrollPosition() {
			// P0-B: 精确恢复滚动位置（无动画，瞬时定位）
			this.scrollAnimation = false
			// 优先从内存缓存恢复
			const memCache = _chatMemoryCache.get(this._scope)
			const cached = memCache?.scrollPos || uni.getStorageSync('tt_ai_match_scroll') || 0
			if (cached > 0) {
				this.scrollTopValue = cached
				// 强制Vue更新scroll-view的scrollTop
				this.$nextTick(() => {
					this.scrollIntoView = ''
				})
			} else {
				this.$nextTick(() => {
					this.scrollIntoView = 'msg-bottom'
				})
			}
			// 恢复后重新启用动画
			setTimeout(() => { this.scrollAnimation = true }, 100)
		},
		saveScrollPosition() {
			try {
				const query = uni.createSelectorQuery().in(this)
				query.select('.chat-scroll').scrollOffset()
				query.exec((res) => {
					if (res && res[0]) {
						uni.setStorageSync('tt_ai_match_scroll', res[0].scrollTop || 0)
					}
				})
			} catch (e) {}
		},
		scrollToBottom() {
				this.scrollIntoView = ''
				this.$nextTick(() => {
					this.scrollIntoView = 'msg-bottom'
				})
			},
			pushMessage(role, content, extra) {
				this.messages.push(createMessage(role, content, extra))
				this.scrollToBottom()
			},
			onSend() {
				if (!this.aiEnabled) return
				const text = (this.inputText || '').trim()
				if (!text) return
				if (this.typing) {
					const { queue, item, overflow } = enqueueMessage(this.pendingQueue, text, MAX_QUEUE_SIZE)
					if (overflow) {
						uni.showToast({ title: '排队已满，请等待当前回复', icon: 'none' })
						return
					}
					this.inputText = ''
					this.pendingQueue = queue
					if (item && this.pendingQueue.length > QUEUE_PREVIEW_COUNT) this.queueExpanded = false
					this.persistQueue()
					return
				}
				this.inputText = ''
				this.persistQueue()
				this.dispatchUserText(text)
			},
			dispatchUserText(text) {
				this.waitingDemandPick = false
				const skill = resolveSkillCommand(text)
				if (skill && skill.id === 'match') {
					this.ensureLocalUserMessage(text)
					this.inflightText = text
					this.persistQueue()
					this.runMatchSkill()
					return
				}
				if (text.startsWith('/')) {
					this.ensureLocalUserMessage(text)
					this.inflightText = text
					this.pushMessage('assistant', '未识别的技能。输入 / 查看可用技能，当前支持 /匹配。')
					this.finishTurn()
					return
				}
				this.runAgentChat(text)
			},
			async runAgentChat(text, reference) {
				const turnId = createTurnId()
				const scope = this._scope
				const version = this._chatRequestVersion || 0
				if (this._scope !== getPageStateScope(uni)) return
				if (!beginTurn({ turnId, message: text, reference, generation: this.chatGeneration }, uni, this._scope)) {
					this.inputText = text
					const active = loadActiveTurn(uni, this._scope)
					uni.showToast({
						title: active ? '上一条问答仍在恢复，当前问题未发送' : '本地暂存失败，问题未发送',
						icon: 'none',
					})
					return
				}
				this.inflightText = text
				this.inflightTurnId = turnId
				this.ensureLocalUserMessage(text)
				this.persistQueue()
				this.typing = true
				this.waitNotice = ''
				this.chatProgress = createChatProgress({ scope, turnId, generation: this.chatGeneration, generationConfirmed: false })
				this.recoveringTurn = false
				this._requestInFlight = true
				try {
					const res = await chatWithAgent(text, turnId, reference)
					if (!this.isCurrentChatRequest(version, scope)) return
					if (!this.acceptChatProgress(res, turnId)) return
					if (res && res.status === 'running') {
						const pollResult = await this.waitForTurnStatus(turnId, text)
						if ((pollResult === 'pending' || pollResult === 'paused') && this._alive) this.scheduleTurnRecovery()
						return
					}
					if (res.status === 'succeeded' || res.status === 'failed') {
						await this.saveServerTurn(res)
						return
					}
					const reply = formatAgentReply(res)
					reply.serverMessageId = res.messageId || null
					reply.serverTurnId = res.turnId || null
					reply.serverGeneration = res.generation ?? null
					if (saveTurnResult(turnId, reply, res.success === false ? 'failed' : 'succeeded', uni, this._scope)) {
						await this.presentSavedTurn(loadActiveTurn(uni, this._scope))
					} else {
						const pollResult = await this.waitForTurnStatus(turnId, text)
						if ((pollResult === 'pending' || pollResult === 'paused') && this._alive) this.scheduleTurnRecovery()
					}
				} catch (e) {
					if (!this.isCurrentChatRequest(version, scope)) return
					if (e.details?.reason === 'chat_history_cleared') {
						acknowledgeTurn(turnId, uni, this._scope)
						this.pendingQueue = []
						this.finishTurn()
						await this.loadHistory()
						return
					}
					if (e.details?.accepted === false) {
						if (saveTurnResult(turnId, { content: e.message || '本轮未受理，请稍后重试。', type: 'text', payload: null }, 'failed', uni, this._scope)) {
							await this.presentSavedTurn(loadActiveTurn(uni, this._scope))
						}
						return
					}
					const pollResult = await this.waitForTurnStatus(turnId, text)
					if ((pollResult === 'pending' || pollResult === 'paused') && this._alive) this.scheduleTurnRecovery()
				} finally {
					if (!this.isCurrentChatRequest(version, scope)) return
					this._requestInFlight = false
					if (this._alive && this.inflightTurnId === turnId) {
						this.typing = true
						this.recoveringTurn = true
					} else if (this._alive && !this.inflightTurnId) {
						this.pumpQueue()
					}
				}
			},
			openCard(card) {
				const target = cardNavigateTarget(card)
				if (!target) {
					uni.showToast({ title: '暂不支持查看该卡片详情', icon: 'none' })
					return
				}
				// 卡片详情统一走分包内页面，并用 safeNavigateTo 规避 10 层页面栈上限
				safeNavigateTo(SUBPACKAGE_ROOT + target.path, target.query)
			},
			goPostDemand() {
				HostBridge.navigate('pages/post-demand/post-demand')
			},
			async runMatchSkill() {
				if (!this.aiEnabled) return
				if (!ensureLoginForDock()) {
					this.finishTurn()
					return
				}
				this.typing = true
				try {
					const data = await getMyDemands({ page: 1, pageSize: 50 })
					if (!this._alive) return
					const demands = (data.list || [])
						.map(toDemandCard)
						.filter((d) => ACTIVE_STATUSES.indexOf(d.status) >= 0)
					if (!demands.length) {
						this.pushMessage(
							'assistant',
							'暂无进行中的需求。发布需求并通过审核后，即可在这里发起 AI 匹配。',
							{ type: 'demand-empty' }
						)
						return
					}
					this.waitingDemandPick = true
					this.pushMessage('assistant', '请选择一条已发布需求，我将为它推荐合适的技术成果：', {
						type: 'demand-picker',
						payload: { demands }
					})
				} catch (e) {
					if (!this._alive) return
					this.pushMessage('assistant', (e && e.message) || '需求加载失败，请稍后重试。')
				} finally {
					if (!this._alive) return
					this.typing = false
					this.inflightText = ''
					this.persistQueue()
					this.scrollToBottom()
					if (!this.waitingDemandPick) this.pumpQueue()
				}
			},
			async onPickDemand(demand) {
				if (!this.aiEnabled || this.typing) return
				this.waitingDemandPick = false
				this.typing = true
				this.pushMessage('user', '匹配需求：' + demand.title)
				this.inflightText = '匹配需求：' + demand.title
				this.persistQueue()
				try {
					const res = await matchDemand(demand.id)
					if (!this._alive) return
					const cards = (res && res.cards) || []
					const agentMsg = (res && res.agentMessage) || ''
					if (!cards.length) {
						this.pushMessage('assistant', agentMsg || '暂未找到匹配的科技成果。')
						return
					}
					this.pushMessage(
						'assistant',
						agentMsg || ('找到 ' + cards.length + ' 条相关科技成果，点击卡片可查看详情。'),
						{ type: 'agent-cards', payload: { cards } }
					)
					await this.loadHistory()
				} catch (e) {
					if (!this._alive) return
					const code = e && e.code
					let msg = (e && e.message) || '匹配失败，请稍后重试。'
					if (code === 'AI_DISABLED') msg = '该功能即将开放'
					this.pushMessage('assistant', msg)
				} finally {
					if (this._alive) this.finishTurn()
				}
			}
		}
	}
</script>

<style>
	.agent-card__advice { margin-top: 14rpx; }
	.agent-card__advice-label { display: block; font-size: 23rpx; color: #51627a; font-weight: 600; margin-bottom: 6rpx; }
	.agent-card__advice-text { display: block; font-size: 24rpx; line-height: 1.65; color: #40516b; white-space: pre-wrap; overflow-wrap: anywhere; }
	.agent-card__advice--caution { padding: 12rpx; background: #fff8ed; border-radius: 10rpx; }
	.agent-card__views {
		display: block;
		margin-top: 12rpx;
		font-size: 22rpx;
		color: #888888;
	}
	page {
		height: 100%;
		overflow: hidden;
	}

	.page {
		height: 100%;
		display: flex;
		flex-direction: column;
		background-color: #f5f6f8;
		box-sizing: border-box;
		overflow: hidden;
	}

	.coming-soon-page {
		flex: 1;
		min-height: 100%;
		display: flex;
		flex-direction: column;
	}

	.coming-soon {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 48rpx;
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

	.header {
		flex: 0 0 auto;
		padding: 24rpx 28rpx 16rpx;
		background: #ffffff;
		border-bottom: 1rpx solid #eef1f5;
	}

	.header__title {
		display: block;
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.header__desc {
		display: block;
		margin-top: 8rpx;
		font-size: 24rpx;
		color: #888888;
		line-height: 1.45;
	}

	.header__mark {
		margin-top: 16rpx;
	}

	.chat-scroll {
		flex: 1 1 auto;
		height: 0;
		min-height: 0;
		padding: 24rpx 24rpx 8rpx;
		box-sizing: border-box;
	}

	.msg {
		display: flex;
		margin-bottom: 20rpx;
	}

	.msg--user {
		justify-content: flex-end;
	}

	.msg--bot {
		flex-direction: column;
		align-items: flex-start;
		justify-content: flex-start;
	}

	.msg--block {
		width: 100%;
	}

	.bubble {
		max-width: 82%;
		padding: 20rpx 24rpx;
		border-radius: 20rpx;
		box-sizing: border-box;
	}

	.bubble--bot {
		background: #ffffff;
		border: 1rpx solid #e8ecf2;
		border-top-left-radius: 8rpx;
	}

	.bubble--user {
		background: #2b73f8;
		border-top-right-radius: 8rpx;
	}

	.bubble--typing {
		opacity: 0.85;
	}

	.bubble__text {
		font-size: 28rpx;
		line-height: 1.55;
		white-space: pre-wrap;
		word-break: break-word;
	}

	.bubble--bot .bubble__text {
		color: #333333;
	}

	.bubble--user .bubble__text {
		color: #ffffff;
	}

	.panel {
		width: 100%;
		background: #ffffff;
		border: 1rpx solid #e8ecf2;
		border-radius: 16rpx;
		padding: 24rpx;
		box-sizing: border-box;
	}

	.panel__text {
		display: block;
		font-size: 28rpx;
		color: #333333;
		line-height: 1.55;
		margin-bottom: 16rpx;
	}

	.panel__hint {
		display: block;
		font-size: 24rpx;
		color: #888888;
		line-height: 1.55;
	}

	.panel__actions {
		margin-top: 8rpx;
	}

	.pick-item {
		padding: 20rpx 0;
		border-top: 1rpx solid #eef1f5;
	}

	.pick-item:first-child {
		border-top: none;
		padding-top: 0;
	}

	.pick-item__title {
		display: block;
		font-size: 28rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.pick-item__meta {
		display: block;
		margin-top: 6rpx;
		font-size: 22rpx;
		color: #888888;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.task-head {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 12rpx;
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

	.match-item {
		background: #f7f9fc;
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
		background: #ffffff;
		border-radius: 8rpx;
		padding: 4rpx 12rpx;
		margin: 0 8rpx 8rpx 0;
	}

	.agent-card {
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 20rpx;
		margin-top: 16rpx;
	}

	.agent-card:first-child {
		margin-top: 0;
	}

	.agent-card__head {
		display: flex;
		flex-direction: row;
		align-items: flex-start;
	}

	.agent-card__tag {
		flex-shrink: 0;
		font-size: 20rpx;
		color: #2b73f8;
		background: rgba(43, 115, 248, 0.1);
		border-radius: 6rpx;
		padding: 4rpx 10rpx;
		margin-right: 12rpx;
		line-height: 1.4;
	}

	.agent-card__tag--demand {
		color: #c47b1a;
		background: #fff4e5;
	}

	.agent-card__title {
		flex: 1;
		font-size: 28rpx;
		font-weight: 600;
		color: #1a1a1a;
		line-height: 1.4;
	}

	.agent-card__org {
		display: block;
		margin-top: 8rpx;
		font-size: 24rpx;
		color: #666666;
	}

	.agent-card__desc {
		display: block;
		margin-top: 8rpx;
		font-size: 24rpx;
		color: #888888;
		line-height: 1.5;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		overflow: hidden;
	}

	.agent-card__meta {
		margin-top: 12rpx;
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
	}

	.meta-chip {
		font-size: 22rpx;
		color: #555555;
		background: #ffffff;
		border-radius: 8rpx;
		padding: 4rpx 12rpx;
		margin: 0 8rpx 8rpx 0;
	}

	.agent-card__fields {
		margin-top: 4rpx;
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
	}

	.agent-card__reasons {
		margin-top: 12rpx;
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
	}

	.field-chip {
		font-size: 22rpx;
		color: #2b73f8;
		background: #ffffff;
		border: 1rpx solid #dce6f8;
		border-radius: 8rpx;
		padding: 4rpx 12rpx;
		margin: 8rpx 8rpx 0 0;
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

	.suggest-wrap {
		margin-top: 8rpx;
		margin-bottom: 12rpx;
	}

	.suggest-label {
		display: block;
		font-size: 22rpx;
		color: #999999;
		margin-bottom: 12rpx;
	}

	.suggest-item {
		display: inline-flex;
		margin: 0 12rpx 12rpx 0;
		padding: 12rpx 20rpx;
		background: #ffffff;
		border: 1rpx solid #dce6f8;
		border-radius: 28rpx;
	}

	.suggest-text {
		font-size: 24rpx;
		color: #2b73f8;
	}

	.scroll-pad {
		height: 24rpx;
	}

	.history-fold {
		margin: 0 0 20rpx;
		padding: 16rpx 20rpx;
		background: #ffffff;
		border: 1rpx dashed #dce6f8;
		border-radius: 16rpx;
		text-align: center;
	}

	.history-fold--open {
		border-style: solid;
	}

	.history-fold__text {
		font-size: 24rpx;
		color: #2b73f8;
	}

	.queue-dock {
		flex: 0 0 auto;
		margin: 0 20rpx 8rpx;
		background: #f7f9fc;
		border: 1rpx solid #dce6f8;
		border-radius: 16rpx;
		padding: 12rpx 16rpx 8rpx;
	}

	.queue-dock__head {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 8rpx;
	}

	.queue-dock__title {
		flex: 1;
		font-size: 22rpx;
		color: #666666;
		padding-right: 12rpx;
	}

	.queue-dock__toggle {
		flex-shrink: 0;
		font-size: 22rpx;
		color: #2b73f8;
	}

	.queue-item {
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 10rpx 0;
	}

	.queue-item__text {
		flex: 1;
		min-width: 0;
		font-size: 24rpx;
		color: #333333;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.queue-item__remove {
		flex-shrink: 0;
		margin-left: 16rpx;
		font-size: 22rpx;
		color: #999999;
	}

	.queue-item--more .queue-item__text {
		color: #2b73f8;
	}

	.skill-sheet {
		flex: 0 0 auto;
		margin: 0 20rpx 8rpx;
		background: #ffffff;
		border: 1rpx solid #e8ecf2;
		border-radius: 16rpx;
		padding: 12rpx 8rpx;
	}

	.skill-sheet__label {
		display: block;
		padding: 8rpx 16rpx 4rpx;
		font-size: 22rpx;
		color: #999999;
	}

	.skill-item {
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 16rpx 16rpx;
	}

	.skill-item__cmd {
		flex-shrink: 0;
		font-size: 26rpx;
		font-weight: 600;
		color: #2b73f8;
		margin-right: 16rpx;
	}

	.skill-item__meta {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}

	.skill-item__label {
		font-size: 26rpx;
		color: #222222;
	}

	.skill-item__desc {
		margin-top: 4rpx;
		font-size: 22rpx;
		color: #999999;
	}

	.composer {
		flex: 0 0 auto;
		padding: 12rpx 20rpx 16rpx;
		background: #ffffff;
		border-top: 1rpx solid #eef1f5;
	}

	.composer__hint {
		display: block;
		margin-bottom: 10rpx;
		font-size: 20rpx;
		color: #999999;
	}

	.composer__row {
		display: flex;
		align-items: center;
		width: 100%;
		display: flex;
		flex-direction: row;
		align-items: center;
	}

	.composer__input {
		flex: 1;
		height: 72rpx;
		padding: 0 24rpx;
		background: #f5f6f8;
		border-radius: 36rpx;
		font-size: 28rpx;
		color: #333333;
	}

	.composer__btn {
		margin-left: 16rpx;
		margin-right: 0;
		background: #2b73f8 !important;
		color: #ffffff !important;
		border-radius: 12rpx;
	}

	.composer__btn[disabled] {
		opacity: 0.45;
	}
</style>
