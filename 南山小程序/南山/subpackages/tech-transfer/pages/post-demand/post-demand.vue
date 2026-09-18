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
				<text class="label">预算 <text class="optional">选填</text></text>
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
				<text class="label">可对接名额 <text class="optional">留空表示不限量</text></text>
				<input class="input" v-model="form.cooperationCapacity" type="number" placeholder="例如：3" />
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
				<text class="label">公司简介 <text class="optional">选填</text></text>
				<textarea
					class="textarea"
					v-model="form.companyIntro"
					placeholder="请简要介绍公司业务"
					maxlength="300"
				/>
			</view>
		</view>

		<view class="section">
			<view class="section-head"><text class="section-title">附件资料</text><view><text class="add-link" @click="chooseDemandImage">+ 添加配图</text><text class="add-link add-link-gap" @click="chooseAttachment">{{ uploading ? '上传中…' : '+ 添加附件' }}</text></view></view>
			<view v-if="!form.attachments.length" class="upload-hint">可上传需求说明、图片或技术资料，单文件最大 20MB</view>
			<view v-for="(attachment, index) in form.attachments" :key="attachment.fileId || attachment.id" class="attachment-row">
				<image v-if="isImageAttachment(attachment)" class="attachment-thumb" :src="mediaSrc(attachment)" mode="aspectFill" />
				<text class="attachment-name">{{ attachment.name }}</text><text class="remove-link" @click="removeAttachment(index)">删除</text>
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

                <view v-if="previewError" class="preview-error">{{ previewError }}</view>
                <button class="submit-btn" type="primary" hover-class="none" :disabled="submitting" @tap="onPreview">预览并提交</button>
                <publish-preview :visible="previewing" :items="previewItems" :images="previewImages" :submitting="submitting" @back="previewing = false" @confirm="onSubmit" />
	</view>
</template>

<script>
	import { createDemand, submitDemand } from '../../api/demand.js'
	import { getSessionPhone, getUserProfile, isLoggedIn } from '../../api/user.js'
	import { getMyOrganizationCertification } from '../../api/membership.js'
	import { validateEmail, validatePhone } from '../../api/contact-validation.mjs'
	import { clearPublishDraft, restorePublishDraft, savePublishDraft } from '../../api/publish-draft.mjs'
	import { uploadContentFile } from '../../api/file.js'
        import HostBridge from '../../../../host/host-bridge.js'
        import PublishPreview from '../../components/publish-preview.vue'
	import { isImageMedia, mediaDisplayUrl } from '../../api/media-url.mjs'

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
		const attachments = (data.attachments || [])
			.map((item, index) => ({ fileId: item.fileId || item.id, role: item.role || 'attachment', caption: item.caption || undefined, sortOrder: index }))
			.filter((item) => Number(item.fileId) > 0)
		if (attachments.length) payload.attachments = attachments
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
		if (data.cooperationCapacity) payload.cooperationCapacity = Number(data.cooperationCapacity)
		if (data.industry) {
			const parts = data.industry.split(/[·•]/).map((s) => s.trim()).filter(Boolean)
			if (parts[0]) payload.categoryName = parts[0]
			if (parts.length > 1) payload.tags = parts.slice(1)
		}
		return payload
	}

        export default {
			components: { PublishPreview },
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
					cooperationCapacity: '',
					deadline: '',
					demandDesc: '',
					companyIntro: '',
					contactName: '',
					contactTitle: '',
					phone: '',
					email: '',
					wechat: '',
					attachments: []
				},
                                submitting: false,
						previewing: false,
						uploading: false,
						previewError: ''
			}
		},
		computed: {
			organizationNames() { return this.organizations.map((item) => item.orgName) },
			organizationIndex() { const index = this.organizations.findIndex((item) => String(item.orgId) === String(this.form.orgId)); return index < 0 ? 0 : index },
                        certifiedCompanyLocked() { return this.organizations.length > 0 }
						, previewItems() {
							const f = this.form
							const files = (f.attachments || []).filter((item) => !isImageMedia(item)).map((item) => item.name).filter(Boolean)
							return [{ label: '需求名称', value: f.title }, { label: '机构', value: f.company }, { label: '地点', value: f.location }, { label: '预算', value: f.budget }, { label: '合作方式', value: f.cooperationType }, { label: '需求说明', value: f.demandDesc }, { label: '附件', value: files.join('、') }, { label: '联系人', value: f.contactName }]
						}
						, previewImages() {
							return (this.form.attachments || []).filter(isImageMedia).map((item) => this.mediaSrc(item)).filter(Boolean)
						}
		},
		onLoad() {
			const saved = restorePublishDraft('demand')
			if (saved) this.form = { ...this.form, ...saved }
			this.prefillFromProfile()
			if (isLoggedIn()) this.loadOrganizations()
		},
		onShow() {
			if (isLoggedIn() && !this.form.phone) this.prefillFromProfile()
		},
		methods: {
			prefillFromProfile() {
				const phone = getSessionPhone()
				const profile = getUserProfile()
				if (!this.form.phone) this.form.phone = phone || ''
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
					result[key] = (key === 'orgId' || key === 'attachments') ? this.form[key] : (this.form[key] || '').trim()
				})
				return result
			},
						showPreviewError(message) {
							this.previewError = message
							uni.showToast({ title: message, icon: 'none' })
							return false
						},
						validate(data) {
							this.previewError = ''
				const required = [
					{ key: 'title', tip: '请填写需求标题' },
					{ key: 'company', tip: '请填写公司名称' },
					{ key: 'location', tip: '请填写地点' },
					{ key: 'demandDesc', tip: '请填写需求说明' },
					{ key: 'contactName', tip: '请填写联系人' },
					{ key: 'phone', tip: '请填写电话' }
				]
				for (let i = 0; i < required.length; i++) {
					const item = required[i]
					if (!data[item.key]) {
								return this.showPreviewError(item.tip)
					}
				}
				if (!validatePhone(data.phone, { required: true }).ok) {
							return this.showPreviewError('请输入11位手机号码')
				}
				const emailCheck = validateEmail(data.email, { required: false })
				if (!emailCheck.ok) {
							return this.showPreviewError(emailCheck.message)
				}
                                return true
                        },
				onPreview() {
							if (this.submitting || this.uploading) {
								if (this.uploading) uni.showToast({ title: '附件上传中，请稍候', icon: 'none' })
								return
							}
							if (this.validate(this.trimForm())) this.previewing = true
				},
				saveDraftAndRequestLogin() {
					savePublishDraft('demand', this.trimForm())
					uni.showToast({ title: '请登录后提交，内容会自动保留', icon: 'none', duration: 1800 })
					setTimeout(() => HostBridge.navigate('pages/mine/mine'), 350)
				},
				chooseAttachment() {
					if (this.uploading) return
					uni.chooseMessageFile({ count: 9, type: 'all', success: async (result) => {
						const files = result.tempFiles || []
						this.uploading = true
						try {
							for (const file of files) {
								const uploaded = await uploadContentFile(file.path)
								this.form.attachments.push({
									...uploaded,
									fileId: uploaded.id,
									role: (uploaded.mimeType || '').indexOf('image/') === 0 ? 'image' : 'attachment',
									localPath: file.path,
								})
							}
						} catch (error) { uni.showToast({ title: (error && error.message) || '附件上传失败', icon: 'none' }) } finally { this.uploading = false }
					} })
				},
				chooseDemandImage() {
					if (this.uploading) return
					uni.chooseImage({ count: 9, success: async (result) => {
						this.uploading = true
						try {
							for (const path of (result.tempFilePaths || [])) {
								const uploaded = await uploadContentFile(path)
								this.form.attachments.push({
									...uploaded,
									fileId: uploaded.id,
									role: 'image',
									localPath: path,
								})
							}
						} catch (error) { uni.showToast({ title: (error && error.message) || '配图上传失败', icon: 'none' }) } finally { this.uploading = false }
					} })
				},
				removeAttachment(index) { this.form.attachments.splice(index, 1) },
				isImageAttachment(item) { return isImageMedia(item) },
				mediaSrc(item) {
					return mediaDisplayUrl(
						item,
						HostBridge.getEnvironment() || {},
						HostBridge.getStorage('tt_access_token') || '',
					)
				},
                        async onSubmit() {
				if (this.submitting || this.uploading) { if (this.uploading) uni.showToast({ title: '附件上传中，请稍候', icon: 'none' }); return }
				if (!isLoggedIn()) {
					this.saveDraftAndRequestLogin()
					return
				}
				const ownerPhone = getSessionPhone()
				if (!ownerPhone) {
					uni.showToast({ title: '请先登录后再发布', icon: 'none' })
					return
				}
                                const data = this.trimForm()
                                if (!this.validate(data)) return

                                this.previewing = false
				this.submitting = true
				uni.showLoading({ title: '提交中', mask: true })
				try {
					// 创建（draft）→ 提交审核（pending_review）
					const detail = await createDemand(buildPayload(data))
					clearPublishDraft('demand')
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
		.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; }
		.add-link { color: #2b73f8; font-size: 26rpx; }
		.add-link-gap { margin-left: 20rpx; }
		.remove-link { color: #e56a63; font-size: 25rpx; }
		.upload-hint { color: #8b98aa; font-size: 25rpx; line-height: 1.55; }
		.attachment-row { min-height: 68rpx; display: flex; align-items: center; border-bottom: 1rpx solid #edf1f5; }
		.attachment-thumb { width: 88rpx; height: 88rpx; border-radius: 10rpx; background: #eef4ff; flex-shrink: 0; margin-right: 16rpx; }
		.attachment-name { flex: 1; min-width: 0; color: #2b73f8; font-size: 26rpx; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }

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
	.preview-error { margin: 8rpx 0 14rpx; color: #d64545; font-size: 26rpx; line-height: 1.5; }
</style>
