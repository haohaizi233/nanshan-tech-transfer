<script>
	import HostBridge from './host/host-bridge.js'
	import LocalAdapter from './host/local-adapter.js'
	import { assertEnvironment } from './config/env-check.js'
	import { startNotificationPolling, stopNotificationPolling } from './utils/notification-poller.js'

	export default {
		onLaunch: function() {
			try {
				assertEnvironment()
			} catch (e) {
				console.error('[App] environment check failed:', e.message)
				uni.showModal({
					title: '环境校验失败',
					content: e.message,
					showCancel: false,
				})
				return
			}

			try {
				HostBridge.registerAdapter(LocalAdapter)
				console.log('[App] LocalAdapter registered, HostBridge ready')
			} catch (e) {
				console.error('[App] HostBridge registration failed:', e.message)
				uni.showModal({
					title: '宿主装配失败',
					content: e.message,
					showCancel: false,
				})
			}
		},
		onShow: function() {
			console.log('App Show')
			startNotificationPolling()
		},
		onHide: function() {
			console.log('App Hide')
			stopNotificationPolling()
		},
		// 全局错误兜底：避免运行时错误导致整页白屏，改为提示用户稍后重试。
		onError: function(err) {
			console.error('[App] global onError:', err)
			try {
				uni.showToast({ title: '出错了，请稍后重试', icon: 'none' })
			} catch (e) {
				// ignore
			}
		},
		onUnhandledRejection: function(res) {
			console.error('[App] unhandled rejection:', res && res.reason)
			try {
				uni.showToast({ title: '出错了，请稍后重试', icon: 'none' })
			} catch (e) {
				// ignore
			}
		}
	}
</script>

<style lang="scss">
	/* 每个页面公共 css */
	page {
		background-color: #f5f6f8;
		color: #333;
		font-size: 28rpx;
		box-sizing: border-box;
	}

	view,
	text,
	image,
	input,
	button {
		box-sizing: border-box;
	}

	.cert-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		margin-left: 8rpx;
		padding: 0 10rpx;
		height: 32rpx;
		border-radius: 8rpx;
		border: 1rpx solid #7dcea0;
		background: #eaf8f0;
		color: #1a8f55;
		font-size: 20rpx;
		font-weight: 600;
		line-height: 32rpx;
		vertical-align: middle;
	}

	.cert-badge-with-icon {
		gap: 4rpx;
		padding-left: 6rpx;
	}

	.cert-badge-icon-inline {
		width: 24rpx;
		height: 24rpx;
		flex-shrink: 0;
	}
</style>
