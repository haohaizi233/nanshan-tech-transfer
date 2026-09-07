<template>
	<view class="page">
		<view class="header">
			<text class="header__title">AI 智能匹配</text>
			<text class="header__desc">通过对话描述需求，获取成果匹配建议（不主动展示技术清单）</text>
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
				:class="msg.role === 'user' ? 'msg msg--user' : 'msg msg--bot'"
			>
				<view :class="msg.role === 'user' ? 'bubble bubble--user' : 'bubble bubble--bot'">
					<text class="bubble__text">{{ msg.content }}</text>
				</view>
			</view>

			<view v-if="typing" class="msg msg--bot">
				<view class="bubble bubble--bot bubble--typing">
					<text class="bubble__text">正在思考…</text>
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

		<view class="composer">
			<input
				class="composer__input"
				type="text"
				:value="inputText"
				placeholder="输入需求方向或问题…"
				confirm-type="send"
				:disabled="typing"
				@input="onInput"
				@confirm="onSend"
			/>
			<button class="composer__btn" size="mini" :disabled="typing" @click="onSend">发送</button>
		</view>
	</view>
</template>

<script>
	import {
		createWelcomeMessage,
		getChatSuggestions,
		buildDemoReply,
		createMessage
	} from '../../common/ai-chat.js'

	export default {
		data() {
			return {
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
			scrollToBottom() {
				this.scrollIntoView = ''
				this.$nextTick(() => {
					this.scrollIntoView = 'msg-bottom'
				})
			},
			onSend() {
				const text = (this.inputText || '').trim()
				if (!text || this.typing) return

				this.messages.push(createMessage('user', text))
				this.inputText = ''
				this.typing = true
				this.scrollToBottom()

				// 演示：短暂延迟后返回本地假回复（大模型接入点）
				setTimeout(() => {
					this.messages.push(createMessage('assistant', buildDemoReply(text)))
					this.typing = false
					this.scrollToBottom()
				}, 600)
			}
		}
	}
</script>

<style lang="scss">
	/* 全局：页面根节点高度撑满，防止页面整体可滑动，确保输入框固定底部 */
	page {
		height: 100%;
		overflow: hidden;
	}
</style>

<style lang="scss" scoped>
	.page {
		height: 100%;
		display: flex;
		flex-direction: column;
		background-color: #f5f6f8;
		box-sizing: border-box;
		overflow: hidden;
	}

	.header {
		flex: 0 0 auto;
		padding: 24rpx 28rpx 16rpx;
		background: #ffffff;
		border-bottom: 1rpx solid #eef1f5;

		&__title {
			display: block;
			font-size: 32rpx;
			font-weight: 600;
			color: #1a1a1a;
		}

		&__desc {
			display: block;
			margin-top: 8rpx;
			font-size: 24rpx;
			color: #888888;
			line-height: 1.45;
		}
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

		&--user {
			justify-content: flex-end;
		}

		&--bot {
			justify-content: flex-start;
		}
	}

	.bubble {
		max-width: 82%;
		padding: 20rpx 24rpx;
		border-radius: 20rpx;
		box-sizing: border-box;

		&--bot {
			background: #ffffff;
			border: 1rpx solid #e8ecf2;
			border-top-left-radius: 8rpx;
		}

		&--user {
			background: #2b73f8;
			border-top-right-radius: 8rpx;
		}

		&--typing {
			opacity: 0.85;
		}

		&__text {
			font-size: 28rpx;
			line-height: 1.55;
			white-space: pre-wrap;
			word-break: break-word;
		}

		&--bot &__text {
			color: #333333;
		}

		&--user &__text {
			color: #ffffff;
		}
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

	.composer {
		flex-shrink: 0;
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 16rpx 20rpx;
		padding-bottom: calc(16rpx + env(safe-area-inset-bottom));
		background: #ffffff;
		border-top: 1rpx solid #eef1f5;

		&__input {
			flex: 1;
			height: 72rpx;
			padding: 0 24rpx;
			background: #f5f6f8;
			border-radius: 36rpx;
			font-size: 28rpx;
			color: #333333;
		}

		&__btn {
			margin-left: 16rpx;
			margin-right: 0;
			background: #2b73f8 !important;
			color: #ffffff !important;
			border-radius: 12rpx;
		}
	}
</style>
