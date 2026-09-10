<template>
	<view class="page">
		<view class="section">
			<text class="section-title">需求信息</text>
			<view v-if="organizations.length" class="form-item"><text class="label">发布主体</text><picker mode="selector" :range="organizationNames" :value="organizationIndex" @change="onOrganizationChange"><view class="picker-value">{{ organizationNames[organizationIndex] }}</view></picker></view>
			<view class="form-item">
				<text class="label">需求标题 <text class="required">*</text></text>
				<input class="input" v-model="form.title" placeholder="例如：高精度视觉检测算法合作需求" maxlength="50" />
			</view>
			<view class="form-item">
				<text class="label">公司名称 <text class="required">*</text></text>
				<view v-if="certifiedCompanyLocked" class="locked-row">
					<input class="input input-disabled" disabled :value="form.company" />
					<text class="cert-badge">认证</text>
				</view>
				<input v-else class="input" v-model="form.company" placeholder="请输入公司名称" />
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
	import { createDemand, submitDemand } from '../../api/demand.js'
	import { getSessionPhone, getUserProfile, ensureLoginForDock } from '../../api/user.js'
	import { getMyOrganizationCertification } from '../../api/membership.js'
	import { validateEmail, validatePhone } from '../../api/contact-validation.mjs'

	/** '80–120 万'→{min,max}；'50 万以内'→{max}；'面议'→{negotiable} */
	function parseBudgetText(text) {
		const t = (text || '').replace(/\s+/g, '').replace(/万/g, '')
		if (!t) return {}
		if (t.indexOf('面议') >= 0) return { budgetNegotiable: true }
		let m = t.match(/^(\d+(?:\.\d+)?)[–\-~至](\d+(?:\.\d+)?)$/)
		if (m) return { budgetMinWan: Number(m[1]), budgetMaxWan: Number(m[2]) }
		m = t.match(/^(\d+(?:\.\d+)?)以内$/)
		if (m) return { budgetMaxWan: Number(m[1]) }
		m = t.match(/^(\d+(?:\.\d+)?)以上$/)
		if (m) return { budgetMinWan: Number(m[1]) }
		return {}
	}

	/** 表单 → DemandUpsertRequest（orgName/categoryName 由后端 get-or-create） */
	function buildPayload(data) {
		const payload = {
			title: data.title,
			description: data.demandDesc,
			region: data.location || null,
			deadlineDesc: data.deadline || null,
			contactName: data.contactName || null,
			contactTitle: data.contactTitle || null,
			contactPhone: data.phone || null,
			contactEmail: data.email || null,
			contactWechat: data.wechat || null,
			...parseBudgetText(data.budget)
		}
		if (data.company) {
			payload.orgName = data.company
			if (data.companyIntro) payload.orgIntro = data.companyIntro
		}
		if (data.orgId) payload.orgId = data.orgId
		if (data.cooperationType) {
			payload.coopMode = data.cooperationType
				.split(/[\/、,，]/)
				.map((s) => s.trim())
				.filter(Boolean)
		}
		if (data.industry) {
			const parts = data.industry.split(/[·•]/).map((s) => s.trim()).filter(Boolean)
			if (parts[0]) payload.categoryName = parts[0]
			if (parts.length > 1) payload.tags = parts.slice(1)
		}
		return payload
	}

	export default {
		data() {
			return {
				organizations: [],
				form: {
					orgId: '',
					title: '',
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
				},
				submitting: false
			}
		},
		computed: {
			organizationNames() { return this.organizations.map((item) => item.orgName) },
			organizationIndex() { const index = this.organizations.findIndex((item) => String(item.orgId) === String(this.form.orgId)); return index < 0 ? 0 : index },
			certifiedCompanyLocked() { return this.organizations.length > 0 }
		},
		onLoad() {
			if (!ensureLoginForDock()) return
			this.prefillFromProfile()
			this.loadOrganizations()
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
			async loadOrganizations() {
				try {
					const data = await getMyOrganizationCertification()
					this.organizations = data.memberships || []
					if (this.organizations.length && !this.form.orgId) this.form.orgId = this.organizations[0].orgId
					this.syncCertifiedCompany()
				} catch (e) {
					this.organizations = []
				}
			},
			syncCertifiedCompany() {
				const org = this.organizations.find((item) => String(item.orgId) === String(this.form.orgId)) || this.organizations[0]
				if (org && org.orgName) this.form.company = org.orgName
			},
			onOrganizationChange(e) {
				const org = this.organizations[Number(e.detail.value)]
				if (org) {
					this.form.orgId = org.orgId
					this.syncCertifiedCompany()
				}
			},
			trimForm() {
				const result = {}
				Object.keys(this.form).forEach((key) => {
					result[key] = key === 'orgId' ? this.form[key] : (this.form[key] || '').trim()
				})
				return result
			},
			validate(data) {
				const required = [
					{ key: 'title', tip: '请填写需求标题' },
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
				if (!validatePhone(data.phone, { required: true }).ok) {
					uni.showToast({ title: '请输入11位手机号码', icon: 'none' })
					return false
				}
				const emailCheck = validateEmail(data.email, { required: false })
				if (!emailCheck.ok) {
					uni.showToast({ title: emailCheck.message, icon: 'none' })
					return false
				}
				return true
			},
			async onSubmit() {
				if (this.submitting) return
				if (!ensureLoginForDock()) return
				const ownerPhone = getSessionPhone()
				if (!ownerPhone) {
					uni.showToast({ title: '请先登录后再发布', icon: 'none' })
					return
				}
				const data = this.trimForm()
				if (!this.validate(data)) return

				this.submitting = true
				uni.showLoading({ title: '提交中', mask: true })
				try {
					// 创建（draft）→ 提交审核（pending_review）
					const detail = await createDemand(buildPayload(data))
					let submitted = false
					try {
						await submitDemand(detail.id, detail.version)
						submitted = true
					} catch (e) {
						console.error('[post-demand] submit review failed:', e)
					}
					uni.hideLoading()
					uni.showToast({
						title: submitted ? '已提交，等待审核' : '已保存为草稿',
						icon: 'success'
					})
					setTimeout(() => {
						uni.navigateBack()
					}, 900)
				} catch (e) {
					uni.hideLoading()
					console.error('[post-demand] create failed:', e)
					uni.showToast({
						title: (e && e.message) || '提交失败，请稍后重试',
						icon: 'none',
						duration: 2500
					})
				} finally {
					this.submitting = false
				}
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

	.input-disabled {
		color: #666666;
	}

	.locked-row {
		display: flex;
		flex-direction: row;
		align-items: center;
		gap: 12rpx;
	}

	.locked-row .input {
		flex: 1;
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
