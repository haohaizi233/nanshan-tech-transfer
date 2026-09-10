<template>
	<view class="app-tabbar-root">
		<!-- 占位：固定导航条不占文档流，用同高占位避免内容被遮挡 -->
		<view class="app-tabbar-spacer"></view>
		<view class="app-tabbar">
			<view v-for="item in visibleTabs" :key="item.key" class="tabbar-item" @click="go(item)">
				<image
					class="tabbar-icon"
					:src="active === item.key ? item.activeIcon : item.icon"
					mode="aspectFit"
				></image>
				<text :class="active === item.key ? 'tabbar-text tabbar-text-active' : 'tabbar-text'">{{ item.label }}</text>
			</view>
		</view>
	</view>
</template>

<script>
	import { SHOW_AI_MATCH_ENTRY } from '../../../config/feature-flags.js'

	const SUBPACKAGE_ROOT = '/subpackages/tech-transfer/'

	export default {
		name: 'AppTabbar',
		props: {
			// 当前高亮 tab：home | ai | mine
			active: {
				type: String,
				default: 'home',
			},
		},
		data() {
			return {
				tabs: [
					{
						key: 'home',
						label: '首页',
						path: 'pages/home/home',
						icon: '/static/tab/home.png',
						activeIcon: '/static/tab/home-active.png',
					},
					{
						key: 'ai',
						label: 'AI匹配',
						path: 'pages/ai-match/ai-match',
						icon: '/static/tab/ai.png',
						activeIcon: '/static/tab/ai-active.png',
						hidden: !SHOW_AI_MATCH_ENTRY,
					},
					{
						key: 'mine',
						label: '我的',
						path: 'pages/mine/mine',
						icon: '/static/tab/mine.png',
						activeIcon: '/static/tab/mine-active.png',
					},
				],
			}
		},
		computed: {
			visibleTabs() {
				return this.tabs.filter((item) => !item.hidden)
			},
		},
		methods: {
			go(item) {
				if (item.key === this.active) return
				// redirectTo 替换当前页，避免页面栈随 tab 切换无限增长
				uni.redirectTo({ url: SUBPACKAGE_ROOT + item.path })
			},
		},
	}
</script>

<style scoped>
	.app-tabbar-root {
		width: 100%;
	}

	.app-tabbar-spacer {
		height: calc(110rpx + env(safe-area-inset-bottom));
	}

	.app-tabbar {
		position: fixed;
		left: 0;
		right: 0;
		bottom: 0;
		display: flex;
		flex-direction: row;
		background-color: #ffffff;
		border-top: 1rpx solid #e8ecf2;
		padding-bottom: env(safe-area-inset-bottom);
		z-index: 998;
		/* #ifdef H5 */
		/* 宽屏（桌面浏览器）下 uni-app 将页面内容约束为 414px 居中列（globalStyle/rpxCalcMaxDeviceWidth），
		   tabbar 必须同宽居中，否则会铺满整个视口、三个图标散布在巨大白条里；414 需与 pages.json 保持同步 */
		max-width: 414px;
		margin: 0 auto;
		/* #endif */
	}

	.tabbar-item {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 10rpx 0 6rpx;
	}

	.tabbar-icon {
		width: 48rpx;
		height: 48rpx;
	}

	.tabbar-text {
		font-size: 20rpx;
		color: #999999;
		margin-top: 4rpx;
		line-height: 1.2;
	}

	.tabbar-text-active {
		color: #2b73f8;
		font-weight: 500;
	}
</style>
