<template>
	<view class="page" v-if="detail">
		<view class="section">
			<text class="title">{{ detail.title }}</text>
			<text class="source">{{ detail.source }}</text>
			<text class="intro">{{ detail.techIntro }}</text>
		</view>

		<view class="section score-section">
			<view class="total-wrap">
				<text class="total-label">综合评分</text>
				<text class="total-num">{{ detail.totalScore }}</text>
				<text class="total-unit">/ 100</text>
			</view>
			<text class="tip">演示数据 · 正式上线后由 AI 接口生成</text>
		</view>

		<view class="section">
			<text class="section-title">四维评分</text>
			<view v-for="dim in detail.dimensions" :key="dim.key" class="dim-item">
				<view class="dim-top">
					<text class="dim-label">{{ dim.label }}</text>
					<text class="dim-score">{{ dim.score }}</text>
				</view>
				<view class="bar-track">
					<view class="bar-fill" :style="{ width: dim.score + '%' }"></view>
				</view>
			</view>
		</view>

		<view class="section">
			<text class="section-title">简要结论</text>
			<text class="conclusion">{{ detail.conclusion }}</text>
		</view>

		<view class="section">
			<text class="section-title">亮点优势</text>
			<view v-for="(item, index) in detail.highlights" :key="index" class="highlight">
				<text class="highlight__dot">{{ index + 1 }}</text>
				<text class="highlight__text">{{ item }}</text>
			</view>
		</view>

		<view class="actions">
			<button class="btn" @click="goDock">查看成果对接详情</button>
		</view>
	</view>
</template>

<script>
	import { getAiEvalByResultId } from '../../common/ai-eval.js'

	export default {
		data() {
			return {
				detail: null,
				resultId: ''
			}
		},
		onLoad(options) {
			const id = options.id || ''
			this.resultId = id
			const detail = getAiEvalByResultId(id)
			if (!detail) {
				uni.showToast({ title: '未找到评估结果', icon: 'none' })
				setTimeout(() => uni.navigateBack(), 1200)
				return
			}
			this.detail = detail
			uni.setNavigationBarTitle({ title: 'AI 评估结果' })
		},
		methods: {
			goDock() {
				uni.navigateTo({
					url: '/packageA/dock-detail/dock-detail?type=result&id=' + this.resultId
				})
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
		margin-bottom: 10rpx;
	}

	.source {
		display: block;
		font-size: 24rpx;
		color: #2b73f8;
		margin-bottom: 14rpx;
	}

	.intro {
		display: block;
		font-size: 26rpx;
		color: #555555;
		line-height: 1.55;
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
