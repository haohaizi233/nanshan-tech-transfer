<template>
	<view class="privacy-gate">
		<text class="privacy-description">更换头像或绑定手机号前，请阅读并同意隐私保护指引。您可以拒绝并继续浏览。</text>
		<text class="privacy-link" @click="openContract">查看《{{ contractName || '用户隐私保护指引' }}》</text>
		<button class="privacy-agree" open-type="agreePrivacyAuthorization" @agreeprivacyauthorization="onAgree">同意并继续</button>
	</view>
</template>

<script>
export default {
	props: { contractName: { type: String, default: '' } },
	emits: ['agree'],
	methods: {
		openContract() {
			// #ifdef MP-WEIXIN
			if (typeof wx !== 'undefined' && typeof wx.openPrivacyContract === 'function') {
				wx.openPrivacyContract({ fail: () => uni.showToast({ title: '隐私指引暂不可用，请稍后重试', icon: 'none' }) })
			}
			// #endif
		},
		onAgree(event) {
			if (/fail/i.test(event.detail?.errMsg || '')) {
				uni.showToast({ title: '隐私授权未完成，请重新确认', icon: 'none' })
				return
			}
			this.$emit('agree')
		},
	},
}
</script>

<style scoped>
.privacy-gate { padding: 24rpx; background: #ffffff; border-radius: 12rpx; }
.privacy-description { display: block; font-size: 26rpx; line-height: 1.6; color: #555555; }
.privacy-link { display: block; font-size: 26rpx; color: #2979ff; margin: 16rpx 0; }
.privacy-agree { background: #07c160; color: #ffffff; font-size: 28rpx; }
</style>
