<template>
	<view class="ai-redirecting">
		<text>正在进入 AI 匹配…</text>
	</view>
</template>

<script>
	import { SHOW_AI_MATCH_ENTRY } from '../../config/feature-flags.js'

	const AI_MATCH_PAGE = '/subpackages/tech-transfer/pages/ai-match/ai-match'
	const BUSINESS_HOME = '/subpackages/tech-transfer/pages/home/home'

	export default {
		data() {
			return {
				redirecting: false,
			}
		},
		onLoad() {
			this.goAiMatch()
		},
		onShow() {
			this.goAiMatch()
		},
		methods: {
			goAiMatch() {
				if (this.redirecting) return
				this.redirecting = true
				// 开关关闭时不展示 AI，退回业务首页，避免落到空白跳转页
				const target = SHOW_AI_MATCH_ENTRY ? AI_MATCH_PAGE : BUSINESS_HOME
				uni.reLaunch({
					url: target,
					fail: () => {
						this.redirecting = false
						uni.showToast({ title: 'AI 匹配加载失败，请重试', icon: 'none' })
					},
				})
			},
		},
	}
</script>

<style scoped>
	.ai-redirecting {
		min-height: 100vh;
		display: flex;
		align-items: center;
		justify-content: center;
		background-color: #f5f6f8;
		font-size: 28rpx;
		color: #999999;
	}
</style>
