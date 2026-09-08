<template>
	<view class="page" v-if="detail">
		<view class="section">
			<text class="patent-name">{{ detail.name }}</text>
			<view class="meta-list">
				<view class="meta-row">
					<text class="meta-label">单位名称</text>
					<text class="meta-value">{{ detail.unitName || detail.holder }}</text>
				</view>
				<view class="meta-row">
					<text class="meta-label">专利号</text>
					<text class="meta-value">{{ detail.patentNo }}</text>
				</view>
				<view class="meta-row">
					<text class="meta-label">专利类型</text>
					<text class="meta-value">{{ detail.typeLabel }}</text>
				</view>
				<view class="meta-row">
					<text class="meta-label">申请日</text>
					<text class="meta-value">{{ detail.applyDate }}</text>
				</view>
				<view class="meta-row">
					<text class="meta-label">缴费年度</text>
					<text class="meta-value">第 {{ detail.feeYear }} 年（{{ detail.fees.yearRange || '—' }}）</text>
				</view>
			</view>
			<text class="tip">专利类型、缴费年度等正式上线后由数据库获取，当前为演示数据</text>
		</view>

		<view class="section">
			<text class="section-title">应缴年费</text>
			<view v-if="detail.fees.ok" class="fee-table">
				<view class="fee-head">
					<text class="col-name">费用项目</text>
					<text class="col-amount">金额（元）</text>
					<text class="col-deadline">最晚缴费时间</text>
				</view>
				<view class="fee-row">
					<text class="col-name">年费标准</text>
					<text class="col-amount amount">{{ detail.fees.standard }}</text>
					<text class="col-deadline">{{ detail.latestPayDate }}</text>
				</view>
				<view class="fee-row">
					<text class="col-name">减 70% 年费标准</text>
					<text class="col-amount amount">{{ detail.fees.reduce70 }}</text>
					<text class="col-deadline">{{ detail.latestPayDate }}</text>
				</view>
				<view class="fee-row">
					<text class="col-name">减 85% 年费标准</text>
					<text class="col-amount amount">{{ detail.fees.reduce85 }}</text>
					<text class="col-deadline">{{ detail.latestPayDate }}</text>
				</view>
			</view>
			<view v-else class="fee-error">
				<text>{{ detail.fees.message || '暂无法计算年费' }}</text>
			</view>
			<text class="tip">最晚缴费时间 = 申请日 + 当前缴费年度对应年数 − 1 天</text>
		</view>
	</view>
</template>

<script>
	import { getPatentById, buildPatentFeeDetail } from '../../api/patent-fee.js'

	export default {
		data() {
			return {
				detail: null
			}
		},
		onLoad(options) {
			const id = options.id || ''
			const patent = getPatentById(id)
			if (!patent) {
				uni.showToast({ title: '未找到该专利', icon: 'none' })
				setTimeout(() => uni.navigateBack(), 1200)
				return
			}
			this.detail = buildPatentFeeDetail(patent)
			uni.setNavigationBarTitle({ title: '年费详情' })
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
		margin-bottom: 24rpx;
	}

	.patent-name {
		display: block;
		font-size: 34rpx;
		font-weight: 600;
		color: #1a1a1a;
		line-height: 1.4;
		margin-bottom: 24rpx;
	}

	.meta-list {
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 8rpx 20rpx;
	}

	.meta-row {
		display: flex;
		flex-direction: row;
		padding: 18rpx 0;
		border-bottom: 1rpx solid #e8ecf2;
	}

	.meta-row:last-child {
		border-bottom: none;
	}

	.meta-label {
		width: 160rpx;
		flex-shrink: 0;
		font-size: 26rpx;
		color: #888888;
	}

	.meta-value {
		flex: 1;
		font-size: 26rpx;
		color: #222222;
		line-height: 1.4;
	}

	.section-title {
		display: block;
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
		margin-bottom: 20rpx;
	}

	.fee-table {
		border: 1rpx solid #e8ecf2;
		border-radius: 12rpx;
		overflow: hidden;
	}

	.fee-head,
	.fee-row {
		display: flex;
		flex-direction: row;
		align-items: center;
	}

	.fee-head {
		background: #f0f4fa;
		padding: 18rpx 16rpx;
	}

	.fee-row {
		padding: 22rpx 16rpx;
		border-top: 1rpx solid #e8ecf2;
		background: #ffffff;
	}

	.fee-head text {
		font-size: 24rpx;
		color: #555555;
		font-weight: 600;
	}

	.col-name {
		flex: 1.2;
		font-size: 26rpx;
		color: #333333;
	}

	.col-amount {
		flex: 0.8;
		text-align: center;
		font-size: 26rpx;
		color: #333333;
	}

	.col-deadline {
		flex: 1.1;
		text-align: right;
		font-size: 24rpx;
		color: #555555;
	}

	.amount {
		color: #2b73f8;
		font-weight: 600;
	}

	.fee-error {
		padding: 40rpx 20rpx;
		text-align: center;
		font-size: 26rpx;
		color: #999999;
	}

	.tip {
		display: block;
		margin-top: 20rpx;
		font-size: 22rpx;
		color: #999999;
		line-height: 1.5;
	}
</style>
