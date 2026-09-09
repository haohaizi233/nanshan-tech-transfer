<template>
	<view class="page">
		<!-- 发布成功态：提供 AI 评估入口（决策 D13） -->
		<view v-if="submitted" class="success-box">
			<text class="success-icon">✓</text>
			<text class="success-title">成果已提交审核</text>
			<text class="success-desc">审核通过后将在成果列表展示；现在可以先发起 AI 评估，评估任务将在排队后执行</text>
			<button class="eval-btn" size="mini" :disabled="evaluating" @click="onStartEvaluation">
				{{ evaluating ? '提交中…' : '发起 AI 评估' }}
			</button>
			<button class="back-btn" size="mini" @click="goMyResults">查看我的成果</button>
		</view>

		<block v-else>
			<view class="section">
				<text class="section-title">成果信息</text>
				<view v-if="organizations.length" class="form-item"><text class="label">发布主体</text><picker mode="selector" :range="organizationNames" :value="organizationIndex" @change="onOrganizationChange"><view class="picker-value">{{ organizationNames[organizationIndex] }}</view></picker></view>
				<view class="form-item">
					<text class="label">成果名称 <text class="required">*</text></text>
					<input class="input" v-model="form.title" placeholder="请输入成果/专利名称" />
				</view>
				<view class="form-item">
					<text class="label">来源 <text class="required">*</text></text>
					<input class="input" v-model="form.sourceOrgName" placeholder="例如：某高校 · 某学院/研究所" />
				</view>
				<view class="form-item">
					<text class="label">成熟度 <text class="required">*</text></text>
					<picker mode="selector" :range="maturityLabels" :value="maturityIndex" @change="onMaturityChange">
						<view class="picker-value">{{ maturityLabel }}</view>
					</picker>
				</view>
				<view class="form-item">
					<text class="label">报价方式 <text class="required">*</text></text>
					<picker mode="selector" :range="pricingLabels" :value="pricingIndex" @change="onPricingChange">
						<view class="picker-value">{{ pricingLabels[pricingIndex] || '请选择报价方式' }}</view>
					</picker>
				</view>
				<view v-if="form.pricingMode !== 'negotiable'" class="form-item">
					<text class="label">期望价格（万元）</text>
					<view class="price-row">
						<input class="input price-input" v-model="form.priceMinWan" type="digit" placeholder="最低" />
						<text class="price-sep">—</text>
						<input class="input price-input" v-model="form.priceMaxWan" type="digit" placeholder="最高" />
					</view>
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
					<text class="label">成果用途（每行一条应用场景）</text>
					<textarea
						class="textarea"
						v-model="form.applicationFields"
						placeholder="请说明可应用的场景与价值，每行一条"
						maxlength="400"
					/>
				</view>
				<view class="form-item">
					<text class="label">技术路径</text>
					<textarea
						class="textarea"
						v-model="form.techRoute"
						placeholder="请说明主要技术路径或工艺步骤"
						maxlength="400"
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
					<input class="input" v-model="form.contactTitle" placeholder="例如：成果转化联系人" />
				</view>
				<view class="form-item">
					<text class="label">电话 <text class="required">*</text></text>
					<input class="input" v-model="form.contactPhone" type="number" maxlength="11" placeholder="请输入11位手机号码" />
				</view>
				<view class="form-item">
					<text class="label">邮箱</text>
					<input class="input" v-model="form.contactEmail" placeholder="请输入邮箱" />
				</view>
				<view class="form-item">
					<text class="label">微信</text>
					<input class="input" v-model="form.contactWechat" placeholder="请输入微信号" />
				</view>
			</view>

			<button class="submit-btn" type="primary" :disabled="submitting" @click="onSubmit">
				{{ submitting ? '提交中…' : '提交成果' }}
			</button>
		</block>
	</view>
</template>

<script>
	import { getSessionPhone, getUserProfile, ensureLoginForDock } from '../../api/user.js'
	import { createAchievement, submitAchievement } from '../../api/achievement.js'
	import { createEvaluationTask } from '../../api/ai.js'
	import { getMyOrganizationCertification } from '../../api/membership.js'
	import HostBridge from '../../../../host/host-bridge.js'

	const MATURITY_OPTIONS = [
		{ value: '01_idea', label: '概念阶段' },
		{ value: '02_lab', label: '实验室验证' },
		{ value: '03_pilot_ready', label: '可进入中试' },
		{ value: '04_pilot_done', label: '中试完成' },
		{ value: '05_mass_ready', label: '可量产' }
	]

	const PRICING_OPTIONS = [
		{ value: 'negotiable', label: '面议' },
		{ value: 'license', label: '许可' },
		{ value: 'transfer', label: '转让' },
		{ value: 'cooperation', label: '合作' },
		{ value: 'other', label: '其他' }
	]

	function splitLines(text) {
		return String(text || '')
			.split(/[\n；;]+/)
			.map((s) => s.trim())
			.filter(Boolean)
	}

	export default {
		data() {
			return {
				organizations: [],
				submitting: false,
				evaluating: false,
				submitted: false,
				submittedId: null,
				form: {
					orgId: '',
					title: '',
					sourceOrgName: '',
					maturityLevel: '01_idea',
					pricingMode: 'negotiable',
					priceMinWan: '',
					priceMaxWan: '',
					techIntro: '',
					applicationFields: '',
					techRoute: '',
					contactName: '',
					contactTitle: '',
					contactPhone: '',
					contactEmail: '',
					contactWechat: ''
				}
			}
		},
		computed: {
			maturityLabels() {
				return MATURITY_OPTIONS.map((o) => o.label)
			},
			maturityLabel() {
				const opt = MATURITY_OPTIONS.find((o) => o.value === this.form.maturityLevel)
				return opt ? opt.label : '请选择成熟度'
			},
			pricingLabels() {
				return PRICING_OPTIONS.map((o) => o.label)
			},
			maturityIndex() {
				const idx = MATURITY_OPTIONS.findIndex((o) => o.value === this.form.maturityLevel)
				return idx >= 0 ? idx : 0
			},
			pricingIndex() {
				const idx = PRICING_OPTIONS.findIndex((o) => o.value === this.form.pricingMode)
				return idx >= 0 ? idx : 0
			}
			, organizationNames() { return this.organizations.map((item) => item.orgName) }
			, organizationIndex() { const index = this.organizations.findIndex((item) => String(item.orgId) === String(this.form.orgId)); return index < 0 ? 0 : index }
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
			if (!this.form.contactPhone) this.prefillFromProfile()
		},
		methods: {
			prefillFromProfile() {
				const phone = getSessionPhone()
				const profile = getUserProfile()
				this.form.contactPhone = phone || ''
				if (profile) {
					if (!this.form.contactName) this.form.contactName = profile.nickname || ''
					if (!this.form.contactEmail) this.form.contactEmail = profile.email || ''
					if (!this.form.contactWechat) this.form.contactWechat = profile.wechat || ''
				}
			},
			async loadOrganizations() { try { const data = await getMyOrganizationCertification(); this.organizations = data.memberships || []; if (this.organizations.length && !this.form.orgId) this.form.orgId = this.organizations[0].orgId } catch (e) { this.organizations = [] } },
			onOrganizationChange(e) { const org = this.organizations[Number(e.detail.value)]; if (org) this.form.orgId = org.orgId },
			onMaturityChange(e) {
				const opt = MATURITY_OPTIONS[Number(e.detail.value)]
				if (opt) this.form.maturityLevel = opt.value
			},
			onPricingChange(e) {
				const opt = PRICING_OPTIONS[Number(e.detail.value)]
				if (opt) this.form.pricingMode = opt.value
			},
			validate() {
				const f = this.form
				const required = [
					{ key: 'title', tip: '请填写成果名称' },
					{ key: 'sourceOrgName', tip: '请填写来源' },
					{ key: 'maturityLevel', tip: '请选择成熟度' },
					{ key: 'techIntro', tip: '请填写技术简介' },
					{ key: 'contactName', tip: '请填写联系人' },
					{ key: 'contactPhone', tip: '请填写电话' }
				]
				for (let i = 0; i < required.length; i++) {
					if (!String(f[required[i].key] || '').trim()) {
						uni.showToast({ title: required[i].tip, icon: 'none' })
						return false
					}
				}
				if (!/^\d{11}$/.test(f.contactPhone)) {
					uni.showToast({ title: '请输入11位手机号码', icon: 'none' })
					return false
				}
				if (f.pricingMode !== 'negotiable' && (f.priceMinWan || f.priceMaxWan)) {
					const min = parseFloat(f.priceMinWan)
					const max = parseFloat(f.priceMaxWan)
					if (f.priceMinWan && isNaN(min)) {
						uni.showToast({ title: '最低价格必须是数字', icon: 'none' })
						return false
					}
					if (f.priceMaxWan && isNaN(max)) {
						uni.showToast({ title: '最高价格必须是数字', icon: 'none' })
						return false
					}
					if (!isNaN(min) && !isNaN(max) && min > max) {
						uni.showToast({ title: '最低价格不能大于最高价格', icon: 'none' })
						return false
					}
				}
				return true
			},
			buildBody() {
				const f = this.form
				const body = {
					orgId: f.orgId || undefined,
					title: f.title.trim(),
					sourceOrgName: f.sourceOrgName.trim() || undefined,
					maturityLevel: f.maturityLevel,
					maturityDesc: (MATURITY_OPTIONS.find((o) => o.value === f.maturityLevel) || {}).label,
					pricingMode: f.pricingMode,
					techIntro: f.techIntro.trim(),
					applicationFields: splitLines(f.applicationFields),
					techRoute: f.techRoute.trim() || undefined,
					contactName: f.contactName.trim(),
					contactTitle: f.contactTitle.trim() || undefined,
					contactPhone: f.contactPhone.trim(),
					contactEmail: f.contactEmail.trim() || undefined,
					contactWechat: f.contactWechat.trim() || undefined
				}
				if (f.pricingMode !== 'negotiable') {
					const min = parseFloat(f.priceMinWan)
					const max = parseFloat(f.priceMaxWan)
					if (!isNaN(min)) body.priceMinWan = min
					if (!isNaN(max)) body.priceMaxWan = max
				}
				return body
			},
			async onSubmit() {
				if (!ensureLoginForDock()) return
				if (this.submitting) return
				if (!this.validate()) return

				this.submitting = true
				try {
					const created = await createAchievement(this.buildBody())
					// 提交审核：draft → pending_review（提交后即可发起 AI 评估）
					await submitAchievement(created.id, created.version)
					this.submittedId = created.id
					this.submitted = true
					uni.showToast({ title: '提交成功', icon: 'success' })
				} catch (e) {
					console.error('[post-result] submit failed:', e)
					uni.showToast({ title: (e && e.message) || '提交失败，请稍后重试', icon: 'none' })
				} finally {
					this.submitting = false
				}
			},
			async onStartEvaluation() {
				if (!this.submittedId || this.evaluating) return
				this.evaluating = true
				try {
					const task = await createEvaluationTask(this.submittedId)
					HostBridge.navigate('pages/ai-eval-detail/ai-eval-detail', {
						taskId: task.taskId,
						achievementId: this.submittedId
					})
				} catch (e) {
					console.error('[post-result] createEvaluationTask failed:', e)
					uni.showToast({ title: (e && e.message) || '评估发起失败，可稍后在「我的成果」中重试', icon: 'none' })
				} finally {
					this.evaluating = false
				}
			},
			goMyResults() {
				HostBridge.navigate('pages/my-list/my-list', { type: 'result' })
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

	.picker-value {
		height: 80rpx;
		line-height: 80rpx;
		background-color: #f7f9fc;
		border-radius: 12rpx;
		padding: 0 24rpx;
		font-size: 28rpx;
		color: #222222;
	}

	.price-row {
		display: flex;
		flex-direction: row;
		align-items: center;
	}

	.price-input {
		flex: 1;
	}

	.price-sep {
		margin: 0 16rpx;
		color: #999999;
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

	.success-box {
		background-color: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 80rpx 40rpx;
		display: flex;
		flex-direction: column;
		align-items: center;
	}

	.success-icon {
		font-size: 80rpx;
		color: #1f9d63;
		line-height: 1;
	}

	.success-title {
		margin-top: 24rpx;
		font-size: 34rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.success-desc {
		margin-top: 16rpx;
		font-size: 24rpx;
		color: #888888;
		line-height: 1.6;
		text-align: center;
		margin-bottom: 36rpx;
	}

	.eval-btn {
		background-color: #2b73f8 !important;
		color: #ffffff !important;
		font-size: 28rpx !important;
		border-radius: 12rpx !important;
		width: 100%;
		margin: 0 0 20rpx;
	}

	.back-btn {
		background-color: #ffffff !important;
		color: #2b73f8 !important;
		font-size: 28rpx !important;
		border-radius: 12rpx !important;
		border: 1rpx solid #2b73f8 !important;
		width: 100%;
		margin: 0;
	}
</style>
