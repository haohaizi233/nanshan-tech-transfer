<script>
	import HostBridge from './subpackages/tech-transfer/runtime/host-bridge.js'
	import LocalAdapter from './host/local-adapter.js'
	import { assertEnvironment } from './config/env-check.js'

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
		},
		onHide: function() {
			console.log('App Hide')
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
</style>
