<template>
	<view class="page">
		<view class="section">
			<text class="section-title">成果信息</text>
			<view class="form-item">
				<text class="label">成果名称 <text class="required">*</text></text>
				<input class="input" v-model="form.title" placeholder="请输入成果/专利名称" />
			</view>
			<view class="form-item">
				<text class="label">来源 <text class="required">*</text></text>
				<input class="input" v-model="form.source" placeholder="例如：某高校 · 某学院/研究所" />
			</view>
			<view class="form-item">
				<text class="label">期望报价 <text class="required">*</text></text>
				<input class="input" v-model="form.price" placeholder="例如：期望 60–90 万 / 洽谈" />
			</view>
			<view class="form-item">
				<text class="label">技术简介 <text class="required">*</text></text>
				<textarea
					class="textarea"
					v-model="form.techIntro"
					placeholder="请简要介绍技术内容与优势"
					maxlength="500"
				/>
			</view>
			<view class="form-item">
				<text class="label">成果用途 <text class="required">*</text></text>
				<textarea
					class="textarea"
					v-model="form.purpose"
					placeholder="请说明可应用的场景与价值"
					maxlength="400"
				/>
			</view>
			<view class="form-item">
				<text class="label">技术路径 <text class="required">*</text></text>
				<textarea
					class="textarea"
					v-model="form.techPath"
					placeholder="请说明主要技术路径或工艺步骤"
					maxlength="400"
				/>
			</view>
			<view class="form-item">
				<text class="label">专利持有人 <text class="required">*</text></text>
				<input class="input" v-model="form.patentHolder" placeholder="请输入专利持有人" />
			</view>
			<view class="form-item">
				<text class="label">专利号</text>
				<input class="input" v-model="form.patentNo" placeholder="例如：ZL20XXXXXXXX.X" />
			</view>
			<view class="form-item">
				<text class="label">成熟度</text>
				<input class="input" v-model="form.maturity" placeholder="例如：实验室验证完成，可进入中试" />
			</view>
		</view>

		<view class="section">
			<text class="section-title">联系方式</text>
			<view class="form-item">
				<text class="label">联系人 <text class="required">*</text></text>
				<input class="input" v-model="form.contactName" placeholder="请输入联系人姓名" />
			</view>
			<view class="form-item">
				<text class="label">职务</text>
				<input class="input" v-model="form.contactTitle" placeholder="例如：成果转化联系人" />
			</view>
			<view class="form-item">
				<text class="label">电话 <text class="required">*</text></text>
				<input class="input" v-model="form.phone" type="number" maxlength="11" placeholder="请输入11位手机号码" />
			</view>
			<view class="form-item">
				<text class="label">邮箱</text>
				<input class="input" v-model="form.email" placeholder="请输入邮箱" />
			</view>
			<view class="form-item">
				<text class="label">微信</text>
				<input class="input" v-model="form.wechat" placeholder="请输入微信号" />
			</view>
		</view>

		<button class="submit-btn" type="primary" @click="onSubmit">提交成果</button>
	</view>
</template>

<script>
	import { addResult, createId } from '../../common/mock-data.js'
	import { getSessionPhone, getUserProfile, ensureLoginForDock } from '../../common/user.js'

	export default {
		data() {
			return {
				form: {
					title: '',
					source: '',
					price: '',
					techIntro: '',
					purpose: '',
					techPath: '',
					patentHolder: '',
					patentNo: '',
					maturity: '',
					contactName: '',
					contactTitle: '',
					phone: '',
					email: '',
					wechat: ''
				}
			}
		},
		onLoad() {
			if (!ensureLoginForDock()) return
			this.prefillFromProfile()
		},
		onShow() {
			if (!getSessionPhone()) {
				ensureLoginForDock()
				return
			}
			if (!this.form.phone) this.prefillFromProfile()
		},
		methods: {
			prefillFromProfile() {
				const phone = getSessionPhone()
				const profile = getUserProfile()
				this.form.phone = phone || ''
				if (profile) {
					if (!this.form.contactName) this.form.contactName = profile.nickname || ''
					if (!this.form.email) this.form.email = profile.email || ''
					if (!this.form.wechat) this.form.wechat = profile.wechat || ''
				}
			},
			trimForm() {
				const result = {}
				Object.keys(this.form).forEach((key) => {
					result[key] = (this.form[key] || '').trim()
				})
				return result
			},
			validate(data) {
				const required = [
					{ key: 'title', tip: '请填写成果名称' },
					{ key: 'source', tip: '请填写来源' },
					{ key: 'price', tip: '请填写期望报价' },
					{ key: 'techIntro', tip: '请填写技术简介' },
					{ key: 'purpose', tip: '请填写成果用途' },
					{ key: 'techPath', tip: '请填写技术路径' },
					{ key: 'patentHolder', tip: '请填写专利持有人' },
					{ key: 'contactName', tip: '请填写联系人' },
					{ key: 'phone', tip: '请填写电话' }
				]
				for (let i = 0; i < required.length; i++) {
					const item = required[i]
					if (!data[item.key]) {
						uni.showToast({ title: item.tip, icon: 'none' })
						return false
					}
				}
				if (!/^\d{11}$/.test(data.phone)) {
					uni.showToast({ title: '请输入11位手机号码', icon: 'none' })
					return false
				}
				return true
			},
			onSubmit() {
				if (!ensureLoginForDock()) return
				const ownerPhone = getSessionPhone()
				if (!ownerPhone) {
					uni.showToast({ title: '请先登录后再发布', icon: 'none' })
					return
				}
				const data = this.trimForm()
				if (!this.validate(data)) return

				addResult({
					id: createId('ur'),
					title: data.title,
					source: data.source,
					price: data.price,
					techIntro: data.techIntro,
					purpose: data.purpose,
					techPath: data.techPath,
					patentHolder: data.patentHolder,
					patentNo: data.patentNo || '未填写',
					maturity: data.maturity || '待评估',
					contactName: data.contactName,
					contactTitle: data.contactTitle || '对接人',
					phone: ownerPhone,
					ownerPhone,
					email: data.email || '未填写',
					wechat: data.wechat || '未填写'
				})

				uni.showToast({
					title: '提交成功',
					icon: 'success'
				})
				setTimeout(() => {
					uni.navigateBack()
				}, 800)
			}
		}
	}
</script>

<style>
	.page {
		min-height: 100vh;
		background-color: #f5f6f8;
		padding: 24rpx;
		padding-bottom: calc(80rpx + env(safe-area-inset-bottom));
	}

	.section {
		background-color: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 28rpx;
		margin-bottom: 24rpx;
	}

	.section-title {
		display: block;
		font-size: 32rpx;
		color: #1a1a1a;
		font-weight: 600;
		margin-bottom: 20rpx;
	}

	.form-item {
		margin-bottom: 24rpx;
	}

	.form-item:last-child {
		margin-bottom: 0;
	}

	.label {
		display: block;
		font-size: 28rpx;
		color: #333333;
		font-weight: 500;
		margin-bottom: 12rpx;
	}

	.required {
		color: #e74c3c;
	}

	.input {
		height: 80rpx;
		background-color: #f7f9fc;
		border-radius: 12rpx;
		padding: 0 24rpx;
		font-size: 28rpx;
		color: #222222;
	}

	.textarea {
		width: 100%;
		min-height: 160rpx;
		background-color: #f7f9fc;
		border-radius: 12rpx;
		padding: 20rpx 24rpx;
		font-size: 28rpx;
		color: #222222;
		box-sizing: border-box;
	}

	.submit-btn {
		margin-top: 8rpx;
		background-color: #2b73f8;
		color: #ffffff;
		border-radius: 12rpx;
		font-size: 32rpx;
		height: 88rpx;
		line-height: 88rpx;
	}
</style>
