<template>
	<view :class="mode === 'badge' ? 'ai-mark ai-mark--badge' : 'ai-mark ai-mark--banner'">
		<text class="ai-mark__tag">AI生成</text>
		<text v-if="mode !== 'badge'" class="ai-mark__text">{{ notice }}</text>
		<text v-else-if="showBadgeCaption && badgeCaption" class="ai-mark__badge-caption">{{ badgeCaption }}</text>
	</view>
</template>

<script>
	import { AI_BADGE_CAPTION, AI_MATCH_NOTICE } from '../api/ai-disclosure.mjs'

	export default {
		name: 'AiGeneratedMark',
		options: {
			virtualHost: true,
			styleIsolation: 'shared'
		},
		props: {
			mode: {
				type: String,
				default: 'banner'
			},
			notice: {
				type: String,
				default: AI_MATCH_NOTICE
			},
			badgeCaption: {
				type: String,
				default: AI_BADGE_CAPTION
			},
			showBadgeCaption: {
				type: Boolean,
				default: true
			}
		}
	}
</script>

<style>
	.ai-mark--banner {
		display: flex;
		flex-direction: row;
		align-items: flex-start;
		padding: 18rpx 22rpx;
		background: #fff3d6;
		border: 2rpx solid #f0b44c;
		border-left: 8rpx solid #e08200;
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
		padding: 4rpx 14rpx;
		border-radius: 6rpx;
		background: #1d5fe6;
		color: #ffffff;
		font-size: 24rpx;
		font-weight: 700;
		line-height: 1.45;
	}

	.ai-mark--banner .ai-mark__tag {
		margin-top: 2rpx;
	}

	.ai-mark--badge .ai-mark__tag {
		padding: 3rpx 12rpx;
		font-size: 22rpx;
	}

	.ai-mark__text {
		flex: 1;
		min-width: 0;
		margin-left: 14rpx;
		color: #6b3e00;
		font-size: 26rpx;
		font-weight: 600;
		line-height: 1.55;
	}

	.ai-mark__badge-caption {
		margin-left: 10rpx;
		color: #5b6b82;
		font-size: 22rpx;
		line-height: 1.45;
	}
</style>
