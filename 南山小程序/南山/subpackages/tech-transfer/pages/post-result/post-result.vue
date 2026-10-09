<template>
	<view class="page">
		<!-- 发布成功态：提供 AI 评估入口（决策 D13） -->
		<view v-if="submitted" class="success-box">
			<text class="success-icon">✓</text>
			<text class="success-title">成果已提交审核</text>
			<text class="success-desc">{{ aiEnabled ? '审核通过后将在成果列表展示；现在可以先发起 AI 评估，评估任务将在排队后执行' : '审核通过后将在成果列表展示' }}</text>
			<button v-if="aiEnabled" class="eval-btn" size="mini" :disabled="evaluating" @click="onStartEvaluation">
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
				<view class="form-item"><text class="label">英文名称</text><input class="input" v-model="form.titleEn" placeholder="选填，如 English title" /></view>
				<view class="form-item"><text class="label">成果类型</text><picker mode="selector" :range="achievementKindLabels" :value="achievementKindIndex" @change="onAchievementKindChange"><view class="picker-value">{{ achievementKindLabel }}</view></picker></view>
				<view v-if="categories.length" class="form-item"><text class="label">成果分类</text><picker mode="selector" :range="categoryNames" :value="categoryIndex" @change="onCategoryChange"><view class="picker-value">{{ categoryLabel }}</view></picker></view>
				<view v-if="industries.length" class="form-item"><text class="label">所属产业 <text class="optional">选填，可多选</text></text><checkbox-group class="industry-options" @change="onIndustryChange"><label v-for="industry in industries" :key="industry.id" class="industry-option"><checkbox :value="String(industry.id)" :checked="form.industryIds.includes(industry.id)" /><text>{{ industry.name }}</text></label></checkbox-group></view>
				<view class="form-item">
					<text class="label">来源 <text class="required">*</text></text>
					<view v-if="certifiedCompanyLocked" class="locked-row">
						<input class="input input-disabled" disabled :value="form.sourceOrgName" />
						<text class="cert-badge">认证</text>
					</view>
					<input v-else class="input" v-model="form.sourceOrgName" placeholder="例如：某高校 · 某学院/研究所" />
				</view>
				<view class="form-item">
					<text class="label">成熟度 <text class="optional">选填</text></text>
					<picker mode="selector" :range="maturityLabels" :value="maturityIndex" @change="onMaturityChange">
						<view class="picker-value">{{ maturityLabel }}</view>
					</picker>
				</view>
				<view class="form-item">
					<text class="label">报价方式 <text class="optional">选填</text></text>
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
					<text class="label">可对接名额 <text class="optional">留空表示不限量</text></text>
					<input class="input" v-model="form.cooperationCapacity" type="number" placeholder="例如：3" />
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
				<view class="section-head"><text class="section-title">媒体资料</text><text class="add-link" @click="chooseMedia">{{ uploading ? '上传中…' : '+ 添加图片' }}</text></view>
				<view v-if="!form.media.length" class="upload-hint">可设置一张封面及多张成果图，动态图片不会进入小程序包</view>
				<view v-for="(media, index) in form.media" :key="media.fileId || media.id || index" class="media-item">
					<image class="media-thumb" :src="mediaSrc(media)" mode="aspectFill" /><view class="media-info"><text class="media-name">{{ media.name }}</text><text class="media-role" @click="toggleCover(index)">{{ media.role === 'cover' ? '封面图' : '设为封面' }}</text></view><text class="remove-link" @click="removeMedia(index)">删除</text>
				</view>
			</view>

			<view class="section">
				<view class="section-head"><text class="section-title">扩展技术信息</text><text class="add-link" @click="addSection">+ 添加</text></view>
				<view v-for="(section, index) in form.sections" :key="index" class="repeat-card">
					<view class="repeat-head"><text>信息区块 {{ index + 1 }}</text><text class="remove-link" @click="removeSection(index)">删除</text></view>
					<picker mode="selector" :range="sectionLabels" :value="sectionIndex(section.code)" @change="onSectionTypeChange(index, $event)"><view class="picker-value">{{ sectionLabel(section.code) }}</view></picker>
					<input class="input repeat-input" v-model="section.title" placeholder="区块标题" />
					<textarea class="textarea compact-textarea" v-model="section.content" placeholder="填写真实来源内容" maxlength="20000" />
				</view>
			</view>

			<view class="section">
				<view class="section-head"><text class="section-title">关联专利</text><text class="add-link" @click="addPatent">+ 添加专利</text></view>
				<view v-for="(patent, index) in form.patents" :key="index" class="repeat-card">
					<view class="repeat-head"><text>专利 {{ index + 1 }}</text><text class="remove-link" @click="removePatent(index)">删除</text></view>
					<input class="input repeat-input" v-model="patent.patentNo" placeholder="专利号，如 CN202310366203.1" />
					<input class="input repeat-input" v-model="patent.title" placeholder="专利名称（选填）" />
					<label class="primary-check"><checkbox :checked="patent.isPrimary" @click="setPrimaryPatent(index)" /> 主专利</label>
				</view>
			</view>

			<view class="section">
				<view class="section-head"><text class="section-title">相关链接</text><text class="add-link" @click="addLink">+ 添加链接</text></view>
				<view v-for="(link, index) in form.links" :key="index" class="repeat-card">
					<view class="repeat-head"><text>链接 {{ index + 1 }}</text><text class="remove-link" @click="removeLink(index)">删除</text></view>
					<picker mode="selector" :range="linkTypeLabels" :value="linkTypeIndex(link.type)" @change="onLinkTypeChange(index, $event)"><view class="picker-value">{{ linkTypeLabel(link.type) }}</view></picker>
					<input class="input repeat-input" v-model="link.label" placeholder="链接标题，例如：项目官网" />
					<input class="input repeat-input" v-model="link.url" placeholder="https://example.com" />
				</view>
			</view>

			<view class="section">
				<view class="section-head"><text class="section-title">成果完成人</text><text class="add-link" @click="addInventor">+ 添加完成人</text></view>
				<view v-for="(inventor, index) in form.inventors" :key="index" class="repeat-card">
					<view class="repeat-head"><text>完成人 {{ index + 1 }}</text><text class="remove-link" @click="removeInventor(index)">删除</text></view>
					<input class="input repeat-input" v-model="inventor.name" placeholder="姓名 *" />
					<input class="input repeat-input" v-model="inventor.orgName" placeholder="所属机构（选填）" />
					<input class="input repeat-input" v-model="inventor.department" placeholder="院系/部门（选填）" />
					<input class="input repeat-input" v-model="inventor.title" placeholder="职务/职称（选填）" />
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

			<view v-if="previewError" class="preview-error">{{ previewError }}</view>
			<button class="submit-btn" type="primary" hover-class="none" :disabled="submitting" @tap="onPreview">
				{{ submitting ? '提交中…' : '预览并提交' }}
			</button>
			<publish-preview :visible="previewing" :items="previewItems" :images="previewImages" :submitting="submitting" @back="previewing = false" @confirm="onSubmit" />
		</block>
	</view>
</template>

<script>
	import { getSessionPhone, getUserProfile, isLoggedIn } from '../../api/user.js'
	import { createAchievement, submitAchievement, getAchievementCategories, getAchievementIndustries } from '../../api/achievement.js'
	import { createEvaluationTask } from '../../api/ai.js'
	import { getMyOrganizationCertification } from '../../api/membership.js'
	import { validateEmail, validatePhone } from '../../api/contact-validation.mjs'
	import HostBridge from '../../../../host/host-bridge.js'
	import { AI_FEATURE_ENABLED } from '../../../../config/feature-flags.js'
	import { clearPublishDraft, restorePublishDraft, savePublishDraft } from '../../api/publish-draft.mjs'
	import { uploadContentFile } from '../../api/file.js'
	import PublishPreview from '../../components/publish-preview.vue'
	import { mediaDisplayUrl } from '../../api/media-url.mjs'

	const MATURITY_OPTIONS = [
		{ value: '', label: '未填写' },
		{ value: '01_idea', label: '概念阶段' },
		{ value: '02_lab', label: '实验室验证' },
		{ value: '03_pilot_ready', label: '可进入中试' },
		{ value: '04_pilot_done', label: '中试完成' },
		{ value: '05_mass_ready', label: '可量产' }
	]

	const PRICING_OPTIONS = [
		{ value: '', label: '未填写' },
		{ value: 'negotiable', label: '面议' },
		{ value: 'license', label: '许可' },
		{ value: 'transfer', label: '转让' },
		{ value: 'cooperation', label: '合作' },
		{ value: 'other', label: '其他' }
	]
	const SECTION_OPTIONS = [
		{ value: 'innovation', label: '技术创新点' }, { value: 'maturity_detail', label: '成熟度说明' },
		{ value: 'project_support', label: '项目支持' }, { value: 'application', label: '可应用领域' },
		{ value: 'tech_problem', label: '技术问题' }, { value: 'tech_method', label: '技术手段' },
		{ value: 'tech_effect', label: '技术功效' }, { value: 'market_prospect', label: '市场前景' },
		{ value: 'industrialization', label: '产业化情况' }, { value: 'team_intro', label: '团队介绍' },
		{ value: 'technical_route', label: '技术路径' }, { value: 'commercialization', label: '商业化情况' }, { value: 'other', label: '其他' }
	]
	const LINK_TYPE_OPTIONS = [
		{ value: 'official_site', label: '官方网站' }, { value: 'personal_homepage', label: '个人主页' },
		{ value: 'company_site', label: '机构网站' }, { value: 'demo', label: '演示链接' },
		{ value: 'video', label: '视频' }, { value: 'paper', label: '论文' }, { value: 'other', label: '其他' }
	]
	const ACHIEVEMENT_KIND_OPTIONS = [{ value: 'technology', label: '技术成果' }, { value: 'patent', label: '专利成果' }, { value: 'project', label: '项目成果' }, { value: 'product', label: '产品成果' }, { value: 'other', label: '其他' }]

	function splitLines(text) {
		return String(text || '')
			.split(/[\n；;]+/)
			.map((s) => s.trim())
			.filter(Boolean)
	}

	export default {
		components: { PublishPreview },
		data() {
			return {
				aiEnabled: AI_FEATURE_ENABLED,
				organizations: [],
				categories: [],
				industries: [],
				submitting: false,
				evaluating: false,
				submitted: false,
					submittedId: null,
					previewing: false,
					uploading: false,
					previewError: '',
				form: {
					orgId: '',
					categoryId: '',
					industryIds: [],
					title: '',
					titleEn: '',
					achievementKind: 'technology',
					sourceOrgName: '',
					maturityLevel: '',
					pricingMode: '',
					priceMinWan: '',
					priceMaxWan: '',
					cooperationCapacity: '',
					techIntro: '',
					applicationFields: '',
					techRoute: '',
					contactName: '',
					contactTitle: '',
					contactPhone: '',
					contactEmail: '',
					contactWechat: '',
					sections: [],
					patents: [],
					links: [],
					inventors: [],
					media: []
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
			, certifiedCompanyLocked() { return this.organizations.length > 0 }
			, previewItems() {
				const f = this.form
				return [
					{ label: '成果名称', value: f.title }, { label: '来源', value: f.sourceOrgName },
					{ label: '成熟度', value: f.maturityLevel ? this.maturityLabel : '' },
					{ label: '技术简介', value: f.techIntro }, { label: '联系人', value: f.contactName }
				]
			}
			, previewImages() {
				return (this.form.media || []).map((item) => this.mediaSrc(item)).filter(Boolean)
			}
			, sectionLabels() { return SECTION_OPTIONS.map((item) => item.label) }
			, linkTypeLabels() { return LINK_TYPE_OPTIONS.map((item) => item.label) }
			, achievementKindLabels() { return ACHIEVEMENT_KIND_OPTIONS.map((item) => item.label) }
			, achievementKindIndex() { const index = ACHIEVEMENT_KIND_OPTIONS.findIndex((item) => item.value === this.form.achievementKind); return index < 0 ? 0 : index }
			, achievementKindLabel() { return (ACHIEVEMENT_KIND_OPTIONS[this.achievementKindIndex] || ACHIEVEMENT_KIND_OPTIONS[0]).label }
			, categoryNames() { return this.categories.map((item) => item.name) }
			, categoryIndex() { const index = this.categories.findIndex((item) => String(item.id) === String(this.form.categoryId)); return index < 0 ? 0 : index }
			, categoryLabel() { return this.categories.length ? this.categoryNames[this.categoryIndex] : '请选择分类' }
		},
		onLoad() {
			const saved = restorePublishDraft('achievement')
			if (saved) this.form = { ...this.form, ...saved }
			this.loadCategories()
			this.loadIndustries()
			this.prefillFromProfile()
			if (isLoggedIn()) this.loadOrganizations()
		},
		onShow() {
			if (isLoggedIn() && !this.form.contactPhone) this.prefillFromProfile()
		},
		methods: {
			prefillFromProfile() {
				const phone = getSessionPhone()
				const profile = getUserProfile()
				if (!this.form.contactPhone) this.form.contactPhone = phone || ''
				if (profile) {
					if (!this.form.contactName) this.form.contactName = profile.nickname || ''
					if (!this.form.contactEmail) this.form.contactEmail = profile.email || ''
					if (!this.form.contactWechat) this.form.contactWechat = profile.wechat || ''
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
				if (org && org.orgName) this.form.sourceOrgName = org.orgName
			},
			onOrganizationChange(e) {
				const org = this.organizations[Number(e.detail.value)]
				if (org) {
					this.form.orgId = org.orgId
					this.syncCertifiedCompany()
				}
			},
			onMaturityChange(e) {
				const opt = MATURITY_OPTIONS[Number(e.detail.value)]
				if (opt) this.form.maturityLevel = opt.value
			},
			onPricingChange(e) {
				const opt = PRICING_OPTIONS[Number(e.detail.value)]
				if (opt) this.form.pricingMode = opt.value
			},
			async loadCategories() { try { this.categories = await getAchievementCategories() || [] } catch (e) { console.error('[post-result] loadCategories failed:', e) } },
			async loadIndustries() { try { this.industries = await getAchievementIndustries() || [] } catch (e) { this.industries = [] } },
			onAchievementKindChange(e) { const item = ACHIEVEMENT_KIND_OPTIONS[Number(e.detail.value)]; if (item) this.form.achievementKind = item.value },
			onCategoryChange(e) { const item = this.categories[Number(e.detail.value)]; if (item) this.form.categoryId = item.id },
			onIndustryChange(e) { this.form.industryIds = (e.detail.value || []).map((value) => Number(value)).filter((value) => value > 0) },
			sectionLabel(code) { return (SECTION_OPTIONS.find((item) => item.value === code) || {}).label || '请选择类型' },
			sectionIndex(code) { const index = SECTION_OPTIONS.findIndex((item) => item.value === code); return index < 0 ? 0 : index },
			onSectionTypeChange(index, e) { const item = SECTION_OPTIONS[Number(e.detail.value)]; if (item) { this.form.sections[index].code = item.value; if (!this.form.sections[index].title) this.form.sections[index].title = item.label } },
			addSection() { this.form.sections.push({ code: 'innovation', title: '技术创新点', content: '' }) },
			removeSection(index) { this.form.sections.splice(index, 1) },
			addPatent() { this.form.patents.push({ patentNo: '', title: '', isPrimary: this.form.patents.length === 0 }) },
			removePatent(index) { this.form.patents.splice(index, 1) },
			setPrimaryPatent(index) { this.form.patents.forEach((item, itemIndex) => { item.isPrimary = itemIndex === index }) },
			linkTypeLabel(type) { return (LINK_TYPE_OPTIONS.find((item) => item.value === type) || LINK_TYPE_OPTIONS[0]).label },
			linkTypeIndex(type) { const index = LINK_TYPE_OPTIONS.findIndex((item) => item.value === type); return index < 0 ? 0 : index },
			onLinkTypeChange(index, e) { const item = LINK_TYPE_OPTIONS[Number(e.detail.value)]; if (item) this.form.links[index].type = item.value },
			addLink() { this.form.links.push({ type: 'official_site', label: '', url: '' }) },
			removeLink(index) { this.form.links.splice(index, 1) },
			addInventor() { this.form.inventors.push({ name: '', orgName: '', department: '', title: '', personType: 'co_inventor' }) },
			removeInventor(index) { this.form.inventors.splice(index, 1) },
			chooseMedia() {
				if (this.uploading) return
				uni.chooseImage({ count: 9, success: async (result) => {
					this.uploading = true
					try {
						for (const path of (result.tempFilePaths || [])) {
							const uploaded = await uploadContentFile(path)
							this.form.media.push({
								...uploaded,
								fileId: uploaded.id,
								role: this.form.media.some((item) => item.role === 'cover') ? 'gallery' : 'cover',
								localPath: path,
							})
						}
					}
					catch (error) { uni.showToast({ title: (error && error.message) || '图片上传失败', icon: 'none' }) }
					finally { this.uploading = false }
				} })
			},
			removeMedia(index) { this.form.media.splice(index, 1) },
			toggleCover(index) { this.form.media.forEach((item, itemIndex) => { item.role = itemIndex === index ? 'cover' : 'gallery' }) },
			mediaSrc(item) {
				return mediaDisplayUrl(
					item,
					HostBridge.getEnvironment() || {},
					HostBridge.getStorage('tt_access_token') || '',
				)
			},
			showPreviewError(message) {
				this.previewError = message
				uni.showToast({ title: message, icon: 'none' })
				return false
			},
			validate() {
				this.previewError = ''
				const f = this.form
				const required = [
					{ key: 'title', tip: '请填写成果名称' },
					{ key: 'techIntro', tip: '请填写技术简介' },
					{ key: 'contactName', tip: '请填写联系人' },
					{ key: 'contactPhone', tip: '请填写电话' }
				]
				for (let i = 0; i < required.length; i++) {
					if (!String(f[required[i].key] || '').trim()) {
						return this.showPreviewError(required[i].tip)
					}
				}
				if (!validatePhone(f.contactPhone, { required: true }).ok) {
					return this.showPreviewError('请输入11位手机号码')
				}
				const emailCheck = validateEmail(f.contactEmail, { required: false })
				if (!emailCheck.ok) {
					return this.showPreviewError(emailCheck.message)
				}
				for (let index = 0; index < (f.links || []).length; index++) {
					const link = f.links[index]
					if (!String(link.label || '').trim() || !/^https?:\/\//i.test(String(link.url || '').trim())) {
						return this.showPreviewError(`请完善第${index + 1}条相关链接`)
					}
				}
				for (let index = 0; index < (f.inventors || []).length; index++) {
					if (!String(f.inventors[index].name || '').trim()) {
						return this.showPreviewError(`请填写第${index + 1}位完成人姓名`)
					}
				}
				if (f.pricingMode !== 'negotiable' && (f.priceMinWan || f.priceMaxWan)) {
					const min = parseFloat(f.priceMinWan)
					const max = parseFloat(f.priceMaxWan)
					if (f.priceMinWan && isNaN(min)) {
						return this.showPreviewError('最低价格必须是数字')
					}
					if (f.priceMaxWan && isNaN(max)) {
						return this.showPreviewError('最高价格必须是数字')
					}
					if (!isNaN(min) && !isNaN(max) && min > max) {
						return this.showPreviewError('最低价格不能大于最高价格')
					}
				}
				return true
			},
			buildBody() {
				const f = this.form
				const body = {
					orgId: f.orgId || undefined,
					categoryId: f.categoryId || undefined,
					title: f.title.trim(),
					titleEn: f.titleEn.trim() || undefined,
					achievementKind: f.achievementKind || 'technology',
					sourceOrgName: f.sourceOrgName.trim() || undefined,
					techIntro: f.techIntro.trim(),
					applicationFields: splitLines(f.applicationFields),
					techRoute: f.techRoute.trim() || undefined,
					contactName: f.contactName.trim(),
					contactTitle: f.contactTitle.trim() || undefined,
					contactPhone: f.contactPhone.trim(),
					contactEmail: f.contactEmail.trim() || undefined,
					contactWechat: f.contactWechat.trim() || undefined
				}
				if (f.maturityLevel) {
					body.maturityLevel = f.maturityLevel
					body.maturityDesc = (MATURITY_OPTIONS.find((o) => o.value === f.maturityLevel) || {}).label
				}
				if (f.pricingMode) body.pricingMode = f.pricingMode
				const sections = (f.sections || []).filter((item) => String(item.content || '').trim()).map((item, index) => ({ code: item.code, title: String(item.title || '').trim() || this.sectionLabel(item.code), content: String(item.content).trim(), sortOrder: index }))
				if (sections.length) body.sections = sections
				const patents = (f.patents || []).filter((item) => String(item.patentNo || '').trim()).map((item, index) => ({ patentNo: String(item.patentNo).trim(), title: String(item.title || '').trim() || undefined, isPrimary: !!item.isPrimary, sortOrder: index }))
				if (patents.length) body.patents = patents
				const links = (f.links || []).filter((item) => String(item.label || '').trim() && String(item.url || '').trim()).map((item, index) => ({ type: item.type || 'other', label: String(item.label).trim(), url: String(item.url).trim(), sortOrder: index }))
				if (links.length) body.links = links
				const inventorRefs = (f.inventors || []).filter((item) => String(item.name || '').trim()).map((item, index) => ({ name: String(item.name).trim(), orgName: String(item.orgName || '').trim() || undefined, department: String(item.department || '').trim() || undefined, title: String(item.title || '').trim() || undefined, personType: item.personType || 'co_inventor', sortOrder: index }))
				if (inventorRefs.length) body.inventorRefs = inventorRefs
				if (f.industryIds && f.industryIds.length) body.industryIds = f.industryIds
				const media = (f.media || []).map((item, index) => ({ fileId: item.id || item.fileId, role: item.role || 'gallery', sortOrder: index })).filter((item) => item.fileId)
				if (media.length) body.media = media
				if (f.cooperationCapacity) body.cooperationCapacity = Number(f.cooperationCapacity)
				if (f.pricingMode && f.pricingMode !== 'negotiable') {
					const min = parseFloat(f.priceMinWan)
					const max = parseFloat(f.priceMaxWan)
					if (!isNaN(min)) body.priceMinWan = min
					if (!isNaN(max)) body.priceMaxWan = max
				}
				return body
			},
			onPreview() {
				if (this.submitting || this.uploading) {
					if (this.uploading) uni.showToast({ title: '图片上传中，请稍候', icon: 'none' })
					return
				}
				if (this.validate()) this.previewing = true
			},
			saveDraftAndRequestLogin() {
				savePublishDraft('achievement', this.form)
				uni.showToast({ title: '请登录后提交，内容会自动保留', icon: 'none', duration: 1800 })
				setTimeout(() => HostBridge.navigate('pages/mine/mine'), 350)
			},
			async onSubmit() {
				if (this.submitting || this.uploading) { if (this.uploading) uni.showToast({ title: '图片上传中，请稍候', icon: 'none' }); return }
				if (!isLoggedIn()) {
					this.saveDraftAndRequestLogin()
					return
				}
				if (!this.validate()) return
				this.previewing = false

			this.submitting = true
			uni.showLoading({ title: '提交中', mask: true })
			try {
				const created = await createAchievement(this.buildBody())
				clearPublishDraft('achievement')
				// 提交审核：draft → pending_review（提交后即可发起 AI 评估）
				await submitAchievement(created.id, created.version)
				this.submittedId = created.id
				this.submitted = true
				uni.showToast({ title: '提交成功', icon: 'success' })
			} catch (e) {
				console.error('[post-result] submit failed:', e)
				uni.showToast({ title: (e && e.message) || '提交失败，请稍后重试', icon: 'none' })
			} finally {
				uni.hideLoading()
				this.submitting = false
			}
			},
			async onStartEvaluation() {
				if (!this.aiEnabled || !this.submittedId || this.evaluating) return
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
		.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; }
		.add-link, .remove-link { color: #2b73f8; font-size: 26rpx; }
		.remove-link { color: #e56a63; }
		.repeat-card { background: #f7f9fc; border-radius: 12rpx; padding: 18rpx; margin-bottom: 18rpx; }
		.repeat-head { display: flex; justify-content: space-between; color: #526276; font-size: 25rpx; margin-bottom: 14rpx; }
		.repeat-input { display: block; margin-top: 14rpx; box-sizing: border-box; }
		.compact-textarea { min-height: 130rpx; margin-top: 14rpx; }
		.primary-check { display: block; margin-top: 16rpx; color: #526276; font-size: 25rpx; }
		.upload-hint { color: #8b98aa; font-size: 25rpx; line-height: 1.55; }
		.media-item { display: flex; align-items: center; min-height: 112rpx; padding: 12rpx 0; border-bottom: 1rpx solid #edf1f5; }
		.media-thumb { width: 88rpx; height: 88rpx; border-radius: 10rpx; background: #eef4ff; flex-shrink: 0; }
		.media-info { flex: 1; min-width: 0; margin-left: 16rpx; }
		.media-name { display: block; color: #45556b; font-size: 25rpx; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
		.media-role { display: block; color: #2b73f8; font-size: 24rpx; margin-top: 8rpx; }

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

	.picker-value {
		height: 80rpx;
		line-height: 80rpx;
		background-color: #f7f9fc;
		border-radius: 12rpx;
		padding: 0 24rpx;
		font-size: 28rpx;
		color: #222222;
	}

	.industry-options {
		display: flex;
		flex-wrap: wrap;
		gap: 14rpx 18rpx;
		padding: 18rpx 20rpx;
		border-radius: 12rpx;
		background-color: #f7f9fc;
	}

	.industry-option {
		display: flex;
		align-items: center;
		min-width: 42%;
		font-size: 26rpx;
		color: #36465d;
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
	.preview-error { margin: 8rpx 0 14rpx; color: #d64545; font-size: 26rpx; line-height: 1.5; }

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
