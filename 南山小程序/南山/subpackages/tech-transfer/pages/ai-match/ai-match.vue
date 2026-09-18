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
		</view>

		<scroll-view
			class="chat-scroll"
			scroll-y
			:scroll-into-view="scrollIntoView"
			scroll-with-animation
		>
			<view
				v-for="msg in messages"
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
								<text v-if="card.description" class="agent-card__desc">{{ card.description }}</text>

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
							</view>
						</view>
					</view>
				</view>
			</view>

			<view v-if="typing" class="msg msg--bot">
				<AiGeneratedMark mode="badge" />
				<view class="bubble bubble--bot bubble--typing">
					<text class="bubble__text">人工智能正在生成…</text>
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

		<view class="composer">
			<text class="composer__hint">回答由人工智能生成，请注意甄别</text>
			<view class="composer__row">
			<input
				class="composer__input"
				type="text"
				:value="inputText"
				placeholder="输入问题，或 / 调用技能"
				confirm-type="send"
				:disabled="typing"
				@input="onInput"
				@confirm="onSend"
			/>
			<button class="composer__btn" size="mini" :disabled="typing" @click="onSend">发送</button>
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
		matchDemand
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
	import { ensureLoginForDock } from '../../api/user.js'
	import HostBridge from '../../../../host/host-bridge.js'
	import { AI_FEATURE_ENABLED } from '../../../../config/feature-flags.js'

	const ACTIVE_STATUSES = ['published', 'matched']

	export default {
		components: {
			AppTabbar,
			AiGeneratedMark
		},
	data() {
		return {
			aiEnabled: AI_FEATURE_ENABLED,
			messages: [createWelcomeMessage()],
			suggestions: getChatSuggestions(),
			inputText: '',
			typing: false,
			scrollIntoView: ''
		}
	},
	computed: {
		showSuggestions() {
			return !this.typing && this.messages.length <= 1
		},
		skillOptions() {
			return isSlashDraft(this.inputText) ? filterSkills(this.inputText) : []
		}
	},
	onLoad() {
		if (!this.aiEnabled) {
			uni.setNavigationBarTitle({ title: '南山科转通' })
		}
	},
	methods: {
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
				if (!text || this.typing) return
				this.inputText = ''
				this.messages.push(createMessage('user', text))
				this.scrollToBottom()
				const skill = resolveSkillCommand(text)
				if (skill && skill.id === 'match') {
					this.runMatchSkill()
					return
				}
				if (text.startsWith('/')) {
					this.pushMessage('assistant', '未识别的技能。输入 / 查看可用技能，当前支持 /匹配。')
					return
				}
				this.runAgentChat(text)
			},
			async runAgentChat(text) {
				this.typing = true
				try {
					const res = await chatWithAgent(text)
					const reply = formatAgentReply(res)
					this.pushMessage('assistant', reply.content, {
						type: reply.type,
						payload: reply.payload,
					})
				} catch (e) {
					const code = e && e.code
					let msg = (e && e.message) || 'AI 助手暂时不可用，请稍后重试。'
					if (code === 'AI_DISABLED') msg = '该功能即将开放'
					this.pushMessage('assistant', msg)
				} finally {
					this.typing = false
					this.scrollToBottom()
				}
			},
			openCard(card) {
				const target = cardNavigateTarget(card)
				if (!target) {
					uni.showToast({ title: '暂不支持查看该卡片详情', icon: 'none' })
					return
				}
				HostBridge.navigate(target.path, target.query)
			},
			goPostDemand() {
				HostBridge.navigate('pages/post-demand/post-demand')
			},
			async runMatchSkill() {
				if (!this.aiEnabled) return
				if (!ensureLoginForDock()) return
				this.typing = true
				try {
					const data = await getMyDemands({ page: 1, pageSize: 50 })
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
					this.pushMessage('assistant', '请选择一条已发布需求，我将为它推荐合适的技术成果：', {
						type: 'demand-picker',
						payload: { demands }
					})
				} catch (e) {
					this.pushMessage('assistant', (e && e.message) || '需求加载失败，请稍后重试。')
				} finally {
					this.typing = false
					this.scrollToBottom()
				}
			},
			async onPickDemand(demand) {
				if (!this.aiEnabled || this.typing) return
				this.typing = true
				this.pushMessage('user', '匹配需求：' + demand.title)
				try {
					const res = await matchDemand(demand.id)
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
				} catch (e) {
					const code = e && e.code
					let msg = (e && e.message) || '匹配失败，请稍后重试。'
					if (code === 'AI_DISABLED') msg = '该功能即将开放'
					this.pushMessage('assistant', msg)
				} finally {
					this.typing = false
					this.scrollToBottom()
				}
			}
		}
	}
</script>

<style>
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
</style>
