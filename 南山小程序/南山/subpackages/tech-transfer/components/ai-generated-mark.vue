<template>
	<view :class="mode === 'badge' ? 'ai-mark ai-mark--badge' : 'ai-mark ai-mark--banner'">
		<text class="ai-mark__tag">AI生成</text>
		<text v-if="mode !== 'badge'" class="ai-mark__text">{{ notice }}</text>
	</view>
</template>

<script>
	import { AI_MATCH_NOTICE } from '../api/ai-disclosure.mjs'

	export default {
		name: 'AiGeneratedMark',
		props: {
			mode: {
				type: String,
				default: 'banner'
			},
			notice: {
				type: String,
				default: AI_MATCH_NOTICE
			}
		}
	}
</script>

<style>
	.ai-mark--banner {
		display: flex;
		flex-direction: row;
		align-items: flex-start;
		padding: 16rpx 20rpx;
		background: #fff7e8;
		border: 1rpx solid #f3d7a3;
		border-radius: 12rpx;
	}

	.ai-mark--badge {
		display: inline-flex;
		flex-direction: row;
		align-items: center;
		margin-bottom: 8rpx;
	}

	.ai-mark__tag {
		flex-shrink: 0;
		padding: 2rpx 10rpx;
		border-radius: 6rpx;
		background: #2b73f8;
		color: #ffffff;
		font-size: 20rpx;
		font-weight: 600;
		line-height: 1.5;
	}

	.ai-mark--banner .ai-mark__tag {
		margin-top: 2rpx;
	}

	.ai-mark__text {
		flex: 1;
		min-width: 0;
		margin-left: 12rpx;
		color: #8a5a12;
		font-size: 22rpx;
		line-height: 1.5;
	}
</style>
