<template>
	<view class="page-loading">
		<text class="loading-text">正在进入科转通...</text>
	</view>
</template>

<script>
	export default {
		data() {
			return {}
		},
		onLoad() {
			this.goAchievementList()
		},
		onShow() {
			this.goAchievementList()
		},
		methods: {
			goAchievementList() {
				uni.navigateTo({
					url: '/subpackages/tech-transfer/pages/achievement-list/achievement-list'
				})
			}
		}
	}
</script>

<style>
	.page-loading {
		min-height: 100vh;
		display: flex;
		align-items: center;
		justify-content: center;
		background-color: #f5f6f8;
	}
	.loading-text {
		font-size: 28rpx;
		color: #999;
	}
</style>
