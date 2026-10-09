<template>
	<view class="page">
		<!-- 登录态卡片：壳页仅直读 storage 展示，账号操作在子包 mine 页 -->
		<view class="user-card" @click="goMine">
			<view class="avatar"><text class="avatar-text">{{ avatarText }}</text></view>
			<view class="user-info">
				<text class="user-name">{{ displayName }}</text>
				<text class="user-desc">{{ loginDesc }}</text>
			</view>
			<text class="arrow">›</text>
		</view>

		<!-- 功能入口：全部跳业务分包 -->
		<view class="grid">
			<view v-for="m in visibleModules" :key="m.key" class="grid-item" @click="go(m)">
				<view class="grid-icon"><text class="grid-icon-text">{{ m.icon }}</text></view>
				<text class="grid-label">{{ m.name }}</text>
			</view>
		</view>

		<view class="tip">
			<text class="tip-text">资料编辑、账号管理与机构成员入口在「我的」页内</text>
		</view>
	</view>
</template>

<script>
	import HostBridge from '../../host/host-bridge.js'
	import { SHOW_AI_MATCH_ENTRY } from '../../config/feature-flags.js'

	export default {
		data() {
			return {
				authMode: '',
				user: null,
				modules: [
					{ key: 'mine', name: '我的主页', icon: '我', path: 'pages/mine/mine' },
					{ key: 'demand', name: '我的需求', icon: '需', path: 'pages/my-list/my-list', params: { type: 'demand' } },
					{ key: 'result', name: '我的成果', icon: '果', path: 'pages/my-list/my-list', params: { type: 'result' } },
					{ key: 'favorite', name: '我的收藏', icon: '藏', path: 'pages/my-list/my-list', params: { type: 'favorite' } },
					{ key: 'intention', name: '意向请求', icon: '意', path: 'pages/my-list/my-list', params: { type: 'intention' } },
					{ key: 'org', name: '机构服务', icon: '构', path: 'pages/org-join/org-join' },
					{ key: 'capital', name: '资本对接', icon: '资', path: 'pages/capital-list/capital-list' },
					{ key: 'ai', name: 'AI 匹配', icon: 'AI', path: 'pages/ai-match/ai-match' }
				]
			}
		},
		computed: {
			displayName() {
				if (this.authMode === 'account' && this.user) {
					return this.user.displayName || this.user.nickname || this.user.phone || '已登录用户'
				}
				return '未登录'
			},
			loginDesc() {
				if (this.authMode === 'account') return '账号已登录 · 点击进入我的主页'
				if (this.authMode === 'mock') return '开发匿名会话 · 点击进入我的主页'
				return '点击前往登录 / 注册'
			},
			avatarText() {
				const name = this.displayName
				return name ? name.slice(0, 1) : '客'
			},
			visibleModules() {
				return this.modules.filter((m) => m.key !== 'ai' || SHOW_AI_MATCH_ENTRY)
			}
		},
		onShow() {
			this.readSession()
		},
		methods: {
			readSession() {
				try {
					this.authMode = uni.getStorageSync('tt_auth_mode') || ''
					const user = uni.getStorageSync('tt_current_user')
					this.user = user && typeof user === 'object' ? user : null
				} catch (e) {
					this.authMode = ''
					this.user = null
				}
			},
			goMine() {
				HostBridge.navigate('pages/mine/mine')
			},
			go(m) {
				HostBridge.navigate(m.path, m.params)
			}
		}
	}
</script>

<style>
	.page {
		min-height: 100vh;
		background-color: #f5f6f8;
		padding: 24rpx;
		box-sizing: border-box;
	}

	.user-card {
		display: flex;
		flex-direction: row;
		align-items: center;
		background-color: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 32rpx 28rpx;
		margin-bottom: 24rpx;
	}

	.avatar {
		width: 96rpx;
		height: 96rpx;
		border-radius: 48rpx;
		background-color: rgba(43, 115, 248, 0.12);
		display: flex;
		align-items: center;
		justify-content: center;
		margin-right: 24rpx;
		flex-shrink: 0;
	}

	.avatar-text {
		font-size: 40rpx;
		color: #2b73f8;
		font-weight: 600;
	}

	.user-info {
		flex: 1;
		min-width: 0;
	}

	.user-name {
		display: block;
		font-size: 34rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.user-desc {
		display: block;
		margin-top: 8rpx;
		font-size: 24rpx;
		color: #888888;
	}

	.arrow {
		flex-shrink: 0;
		font-size: 40rpx;
		color: #cccccc;
		line-height: 1;
	}

	.grid {
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
		background-color: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 12rpx 0;
	}

	.grid-item {
		width: 25%;
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 28rpx 0;
	}

	.grid-icon {
		width: 80rpx;
		height: 80rpx;
		border-radius: 16rpx;
		background: rgba(43, 115, 248, 0.1);
		display: flex;
		align-items: center;
		justify-content: center;
		margin-bottom: 14rpx;
	}

	.grid-icon-text {
		font-size: 30rpx;
		font-weight: 600;
		color: #2b73f8;
	}

	.grid-label {
		font-size: 24rpx;
		color: #333333;
	}

	.tip {
		margin-top: 28rpx;
		display: flex;
		justify-content: center;
	}

	.tip-text {
		font-size: 22rpx;
		color: #bbbbbb;
	}
</style>
