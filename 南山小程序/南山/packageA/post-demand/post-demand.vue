<template>
	<view class="page">
		<view class="section">
			<text class="section-title">需求信息</text>
			<view class="form-item">
				<text class="label">公司名称 <text class="required">*</text></text>
				<input class="input" v-model="form.company" placeholder="请输入公司名称" />
			</view>
			<view class="form-item">
				<text class="label">地点 <text class="required">*</text></text>
				<input class="input" v-model="form.location" placeholder="例如：广东 · 深圳南山" />
			</view>
			<view class="form-item">
				<text class="label">预算 <text class="required">*</text></text>
				<input class="input" v-model="form.budget" placeholder="例如：80–120 万 / 面议" />
			</view>
			<view class="form-item">
				<text class="label">所属行业</text>
				<input class="input" v-model="form.industry" placeholder="例如：智能制造 · 工业视觉" />
			</view>
			<view class="form-item">
				<text class="label">合作方式</text>
				<input class="input" v-model="form.cooperationType" placeholder="例如：技术合作 / 联合开发" />
			</view>
			<view class="form-item">
				<text class="label">期望周期</text>
				<input class="input" v-model="form.deadline" placeholder="例如：期望 3 个月内完成样机" />
			</view>
			<view class="form-item">
				<text class="label">需求说明 <text class="required">*</text></text>
				<textarea
					class="textarea"
					v-model="form.demandDesc"
					placeholder="请描述你的技术需求"
					maxlength="500"
				/>
			</view>
			<view class="form-item">
				<text class="label">公司简介 <text class="required">*</text></text>
				<textarea
					class="textarea"
					v-model="form.companyIntro"
					placeholder="请简要介绍公司业务"
					maxlength="300"
				/>
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
				<input class="input" v-model="form.contactTitle" placeholder="例如：技术负责人" />
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

		<button class="submit-btn" type="primary" @click="onSubmit">提交需求</button>
	</view>
</template>

<script>
	import { addDemand, createId } from '../../common/mock-data.js'
	import { getSessionPhone, getUserProfile, ensureLoginForDock } from '../../common/user.js'

	export default {
		data() {
			return {
				form: {
					company: '',
					location: '',
					budget: '',
					industry: '',
					cooperationType: '',
					deadline: '',
					demandDesc: '',
					companyIntro: '',
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
					if (!this.form.company) this.form.company = profile.company || ''
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
					{ key: 'company', tip: '请填写公司名称' },
					{ key: 'location', tip: '请填写地点' },
					{ key: 'budget', tip: '请填写预算' },
					{ key: 'demandDesc', tip: '请填写需求说明' },
					{ key: 'companyIntro', tip: '请填写公司简介' },
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

				addDemand({
					id: createId('ud'),
					company: data.company,
					location: data.location,
					budget: data.budget,
					industry: data.industry || '未填写',
					cooperationType: data.cooperationType || '面议',
					deadline: data.deadline || '待沟通',
					demandDesc: data.demandDesc,
					companyIntro: data.companyIntro,
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
