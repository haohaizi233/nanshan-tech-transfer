<template>
	<view class="page">
		<view v-if="!certification.canApply" class="card status-card">
			<text class="card-title">{{ certification.label }}</text>
			<text class="card-desc">{{ certificationHint }}</text>
		</view>
		<view v-if="certification.canApply" class="card">
			<text class="card-title">机构入驻申请</text>
			<text class="card-desc">机构尚未收录时，提交入驻申请。平台管理员审核通过后将创建机构，并授予您机构管理员身份</text>

			<view class="form-item">
				<text class="label">机构名称 <text class="required">*</text></text>
				<input class="input" :value="form.requestedName" placeholder="请输入机构全称" @input="onNameInput" />
				<text v-if="nameError" class="error-tip">{{ nameError }}</text>
				<text v-else class="tip">请先在「申请加入机构」页搜索确认机构未被收录</text>
			</view>
			<view class="form-item">
				<text class="label">机构类型 <text class="required">*</text></text>
				<picker :value="typeIndex" :range="typeOptions" range-key="label" @change="onTypeChange">
					<view :class="form.requestedType ? 'form-picker' : 'form-picker placeholder'">
						{{ typeText || '请选择机构类型' }}
					</view>
				</picker>
			</view>
			<view class="form-item">
				<text class="label">统一社会信用代码</text>
				<input class="input" :value="form.creditCode" placeholder="请输入统一社会信用代码" @input="onFieldInput('creditCode', $event)" />
			</view>
			<view class="form-item">
				<text class="label">官网</text>
				<input class="input" :value="form.website" placeholder="请输入官网地址" @input="onFieldInput('website', $event)" />
			</view>
			<view class="form-item">
				<text class="label">所在地区</text>
				<input class="input" :value="form.region" placeholder="如：广东省深圳市南山区" @input="onFieldInput('region', $event)" />
			</view>
			<view class="form-item">
				<text class="label">详细地址</text>
				<input class="input" :value="form.address" placeholder="请输入详细地址" @input="onFieldInput('address', $event)" />
			</view>

			<text class="section-title">联系人信息</text>
			<view class="form-item">
				<text class="label">联系人 <text class="required">*</text></text>
				<input class="input" :value="form.contactName" placeholder="请输入联系人姓名" @input="onFieldInput('contactName', $event)" />
			</view>
			<view class="form-item">
				<text class="label">联系电话 <text class="required">*</text></text>
				<input class="input" type="number" maxlength="11" :value="form.contactPhone" placeholder="请输入联系电话" @input="onFieldInput('contactPhone', $event)" />
			</view>
			<view class="form-item">
				<text class="label">联系邮箱</text>
				<input class="input" :value="form.contactEmail" placeholder="请输入联系邮箱" @input="onFieldInput('contactEmail', $event)" />
			</view>
			<view class="form-item">
				<text class="label">资质证明说明</text>
				<textarea class="textarea" :value="form.proofMaterial" placeholder="如营业执照、法人授权等材料说明（文字描述）" @input="onFieldInput('proofMaterial', $event)" />
			</view>

			<button class="submit-btn" type="primary" :disabled="submitting || !!nameError" @click="onSubmit">
				{{ submitting ? '提交中...' : '提交申请' }}
			</button>
		</view>
	</view>
</template>

<script>
	import { applyOrganization, getMyOrganizationCertification, searchInstitutions } from '../../api/membership.js'
	import { isLoggedIn } from '../../api/user.js'
	import { validateEmail, validatePhone } from '../../api/contact-validation.mjs'
	import { safeBackWithToast } from '../../utils/nav.mjs'

	const TYPE_OPTIONS = [
		{ label: '企业', value: 'enterprise' },
		{ label: '高校', value: 'university' },
		{ label: '科研院所', value: 'institute' },
		{ label: '服务机构', value: 'service' },
		{ label: '投资机构', value: 'invest' }
	]

	// 草稿持久化：离开页面 / 切后台后回来不丢填写内容（R2-42）
	const DRAFT_KEY = 'tt_org_apply_draft'

	export default {
		data() {
			return {
				typeOptions: TYPE_OPTIONS,
				submitting: false,
				nameError: '',
				nameChecking: false,
				certification: { status: 'unverified', label: '未认证', canApply: true, pendingName: '' },
				form: {
					requestedName: '',
					requestedType: '',
					creditCode: '',
					website: '',
					region: '',
					address: '',
					contactName: '',
					contactPhone: '',
					contactEmail: '',
					proofMaterial: ''
				}
			}
		},
		computed: {
			typeIndex() {
				const idx = this.typeOptions.findIndex((o) => o.value === this.form.requestedType)
				return idx >= 0 ? idx : 0
			},
			typeText() {
				const opt = this.typeOptions.find((o) => o.value === this.form.requestedType)
				return opt ? opt.label : ''
			},
			certificationHint() {
				if (this.certification.status === 'membership_pending') return '正在申请加入：' + (this.certification.pendingName || '机构')
				if (this.certification.status === 'organization_pending') return '机构入驻审核中：' + (this.certification.pendingName || '待命名机构')
				return '已完成机构认证，无需重复申请。'
			}
		},
		onLoad() {
			this.restoreDraft()
		},
		onShow() {
			if (!isLoggedIn()) {
				safeBackWithToast('请先登录', 800)
				return
			}
			this.loadCertification()
		},
		onUnload() {
			// 防止离开页面后 debounce 仍触发 checkExistingName
			clearTimeout(this._nameTimer)
		},
		methods: {
			saveDraft() {
				try {
					uni.setStorageSync(DRAFT_KEY, JSON.parse(JSON.stringify(this.form)))
				} catch (e) {
					// ignore
				}
			},
			restoreDraft() {
				try {
					const saved = uni.getStorageSync(DRAFT_KEY)
					if (saved && typeof saved === 'object') {
						this.form = { ...this.form, ...saved }
					}
				} catch (e) {
					// ignore
				}
			},
			clearDraft() {
				try {
					uni.removeStorageSync(DRAFT_KEY)
				} catch (e) {
					// ignore
				}
			},
			async loadCertification() {
				try {
					this.certification = await getMyOrganizationCertification()
				} catch (e) {
					uni.showToast({ title: (e && e.message) || '认证状态加载失败', icon: 'none' })
				}
			},
			onFieldInput(key, e) {
				this.form[key] = e.detail.value
				this.saveDraft()
			},
			onNameInput(e) {
				this.form.requestedName = e.detail.value
				this.saveDraft()
				this.scheduleNameCheck()
			},
			scheduleNameCheck() {
				clearTimeout(this._nameTimer)
				this.nameError = ''
				const name = (this.form.requestedName || '').trim()
				if (!name) return
				this._nameTimer = setTimeout(() => this.checkExistingName(name), 300)
			},
			async checkExistingName(name) {
				this.nameChecking = true
				try {
					const data = await searchInstitutions(name, 1, 50)
					const hit = (data.list || []).find((item) => String(item.name || '').trim() === name)
					this.nameError = hit ? '该机构已存在，请前往「申请加入机构」提交认证' : ''
				} catch (e) {
					this.nameError = ''
				} finally {
					this.nameChecking = false
				}
			},
			onTypeChange(e) {
				const opt = this.typeOptions[Number(e.detail.value)] || this.typeOptions[0]
				this.form.requestedType = opt ? opt.value : ''
				this.saveDraft()
			},
			async onSubmit() {
				if (!this.certification.canApply) {
					uni.showToast({ title: '当前认证状态不允许重复申请', icon: 'none' })
					return
				}
				const name = (this.form.requestedName || '').trim()
				if (!name) {
					uni.showToast({ title: '请填写机构名称', icon: 'none' })
					return
				}
				await this.checkExistingName(name)
				if (this.nameError) {
					uni.showToast({ title: this.nameError, icon: 'none' })
					return
				}
				if (!this.form.requestedType) {
					uni.showToast({ title: '请选择机构类型', icon: 'none' })
					return
				}
				const contactName = (this.form.contactName || '').trim()
				if (!contactName) {
					uni.showToast({ title: '请填写联系人', icon: 'none' })
					return
				}
				const phoneCheck = validatePhone(this.form.contactPhone, { required: true, label: '联系电话' })
				if (!phoneCheck.ok) {
					uni.showToast({ title: phoneCheck.message, icon: 'none' })
					return
				}
				const emailCheck = validateEmail(this.form.contactEmail, { required: false, label: '联系邮箱' })
				if (!emailCheck.ok) {
					uni.showToast({ title: emailCheck.message, icon: 'none' })
					return
				}
				this.submitting = true
				uni.showLoading({ title: '提交中', mask: true })
				try {
					await applyOrganization({
						requestedName: name,
						requestedType: this.form.requestedType,
						creditCode: (this.form.creditCode || '').trim() || undefined,
						website: (this.form.website || '').trim() || undefined,
						region: (this.form.region || '').trim() || undefined,
						address: (this.form.address || '').trim() || undefined,
						contactName,
						contactPhone: phoneCheck.value,
						contactEmail: emailCheck.value || undefined,
						proofMaterial: (this.form.proofMaterial || '').trim() || undefined
					})
					uni.hideLoading()
				uni.showToast({ title: '已提交，等待平台管理员审核', icon: 'none', duration: 2000 })
				this.clearDraft()
				safeBackWithToast('', 1200)
				} catch (e) {
					uni.hideLoading()
					uni.showToast({ title: (e && e.message) || '提交失败，请稍后重试', icon: 'none', duration: 2500 })
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
		background: #f5f6f8;
		padding: 24rpx;
		padding-bottom: calc(40rpx + env(safe-area-inset-bottom));
		box-sizing: border-box;
	}

	.card {
		background: #ffffff;
		border-radius: 16rpx;
		padding: 32rpx;
		border: 1rpx solid #e8ecf2;
	}

	.card-title {
		display: block;
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
		margin-bottom: 10rpx;
	}

	.card-desc {
		display: block;
		font-size: 24rpx;
		color: #999999;
		line-height: 1.6;
		margin-bottom: 28rpx;
	}

	.status-card {
		background: #fff8ea;
		border-color: #f0d090;
	}

	.section-title {
		display: block;
		font-size: 28rpx;
		font-weight: 600;
		color: #333333;
		margin: 28rpx 0 20rpx;
		padding-top: 24rpx;
		border-top: 1rpx solid #eef0f4;
	}

	.form-item {
		margin-bottom: 22rpx;
	}

	.label {
		display: block;
		font-size: 28rpx;
		color: #333333;
		margin-bottom: 10rpx;
	}

	.required {
		color: #e74c3c;
	}

	.tip {
		display: block;
		font-size: 22rpx;
		color: #999999;
		margin-top: 8rpx;
	}

	.error-tip {
		display: block;
		font-size: 22rpx;
		color: #e74c3c;
		margin-top: 8rpx;
	}

	.input {
		height: 80rpx;
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 0 24rpx;
		font-size: 28rpx;
	}

	.form-picker {
		height: 80rpx;
		line-height: 80rpx;
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 0 24rpx;
		font-size: 28rpx;
		color: #333333;
	}

	.form-picker.placeholder {
		color: #999999;
	}

	.textarea {
		width: 100%;
		min-height: 140rpx;
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 20rpx 24rpx;
		font-size: 28rpx;
		box-sizing: border-box;
	}

	.submit-btn {
		margin-top: 12rpx;
		background: #2b73f8;
		color: #ffffff;
		border-radius: 12rpx;
	}
</style>
