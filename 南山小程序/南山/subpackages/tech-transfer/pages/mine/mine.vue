<template>
	<view class="page">
		<!-- 步骤1：手机号 + 密码 登录/注册 -->
		<view v-if="viewMode === 'auth'" class="login-wrap">
			<view class="login-card">
				<text class="login-title">{{ authMode === 'register' ? '注册账号' : '登录账号' }}</text>
				<text class="login-desc">使用手机号注册登录，账号数据云端同步，小程序与 H5 通用</text>

				<view class="form-item">
					<text class="label">手机号 <text class="required">*</text></text>
					<input
						class="input"
						type="number"
						maxlength="11"
						:value="authForm.phone"
						placeholder="请输入11位手机号"
						@input="onAuthInput('phone', $event)"
					/>
				</view>
				<view class="form-item">
					<text class="label">密码 <text class="required">*</text></text>
					<input
						class="input"
						password
						:value="authForm.password"
						:placeholder="authMode === 'register' ? '设置密码（至少6位）' : '请输入密码'"
						@input="onAuthInput('password', $event)"
					/>
				</view>

				<button class="login-btn" type="primary" @click="onAuthSubmit">
					{{ authMode === 'register' ? '注册并继续' : '登录' }}
				</button>
				<text class="switch-auth" @click="toggleAuthMode">
					{{ authMode === 'register' ? '已有账号？去登录' : '没有账号？去注册' }}
				</text>

				<view v-if="cachedAccounts.length" class="cache-box">
					<text class="cache-title">已缓存账号（点击填入手机号）</text>
					<view class="cache-list">
						<view
							v-for="item in cachedAccounts"
							:key="item.phone"
							class="cache-item"
							@click="fillCachedAccount(item)"
						>
							<text class="cache-phone">{{ item.phone }}</text>
							<text class="cache-meta">{{ item.nickname || '未完善资料' }}</text>
						</view>
					</view>
				</view>

			</view>
		</view>

		<!-- 步骤2：完善 / 编辑资料 -->
		<view v-else-if="viewMode === 'profile'" class="login-wrap">
			<view class="login-card">
				<text class="login-title">{{ editing ? '编辑资料' : '完善个人信息' }}</text>
				<text class="login-desc">账号 {{ authPhone }}，请完善资料后使用对接等功能</text>

				<view class="avatar-block" @click="openAvatarSheet">
					<image class="avatar" :src="form.avatar || '/static/logo.png'" mode="aspectFill"></image>
				</view>

				<view v-if="showAvatarSheet" class="sheet-mask" @click="closeAvatarSheet">
					<view class="sheet-panel" @click.stop>
						<button class="sheet-item sheet-btn" open-type="chooseAvatar" @chooseavatar="onWxAvatar">使用微信头像</button>
						<view class="sheet-item" @click="onChooseAlbum">从相册选择</view>
						<view class="sheet-cancel" @click="closeAvatarSheet">取消</view>
					</view>
				</view>

				<view class="form-item">
					<text class="label">昵称 <text class="required">*</text></text>
					<input
						class="input"
						type="nickname"
						:value="form.nickname"
						placeholder="请输入昵称"
						@input="onFieldInput('nickname', $event)"
						@blur="onNicknameBlur"
					/>
				</view>
				<view class="form-item">
					<text class="label">公司 <text class="required">*</text></text>
					<view v-if="isOrgCertified" class="locked-row">
						<input class="input input-disabled" disabled :value="certifiedOrgName" />
						<text class="cert-badge">认证</text>
					</view>
					<view v-else class="company-select">
						<input class="input" :value="form.company" placeholder="可填写或选择已有机构" @focus="showCompanySuggestions" @input="onCompanyInput" />
						<view v-if="showingCompanySuggestions && companySuggestions.length" class="company-suggestion-list">
							<view v-for="org in companySuggestions" :key="org.id" class="company-suggestion-item" @click="selectCompanySuggestion(org)">
								<text>{{ org.name }}</text>
							</view>
						</view>
					</view>
				</view>
				<view class="form-item">
					<text class="label">主体类型 <text class="required">*</text></text>
					<picker
						:value="subjectTypeIndex"
						:range="subjectPickerOptions"
						range-key="label"
						@change="onSubjectTypeChange"
					>
						<view :class="form.subjectType ? 'form-picker' : 'form-picker placeholder'">
							{{ subjectTypeText || '请选择主体类型' }}
						</view>
					</picker>
				</view>
				<view class="form-item">
					<text class="label">合作方向 <text class="optional">可多选，用于内容推荐</text></text>
					<view class="cap-row">
						<view
							v-for="opt in capabilityOptions"
							:key="opt.value"
							:class="form.businessCapabilities.indexOf(opt.value) >= 0 ? 'cap-btn active' : 'cap-btn'"
							@click="toggleCapability(opt.value)"
						>{{ opt.label }}</view>
					</view>
					<text class="cap-tip">主体类型与合作方向仅用于画像与推荐，不影响您可发布或可对接的内容</text>
				</view>
				<view class="form-item">
					<text class="label">手机号</text>
					<input class="input input-disabled" disabled :value="authPhone" />
				</view>
				<view class="form-item">
					<text class="label">邮箱 <text class="required">*</text></text>
					<input class="input" :value="form.email" placeholder="请输入邮箱" @input="onFieldInput('email', $event)" />
				</view>
				<view class="form-item">
					<text class="label">微信 <text class="required">*</text></text>
					<input class="input" :value="form.wechat" placeholder="请输入微信号" @input="onFieldInput('wechat', $event)" />
				</view>

				<button class="login-btn" type="primary" @click="onSaveProfile">{{ editing ? '保存资料' : '完成并进入' }}</button>
				<button v-if="editing" class="cancel-btn" @click="onCancelEdit">取消</button>
				<button v-else class="cancel-btn" @click="onLogout">退出登录</button>
			</view>
		</view>

		<!-- 已登录且资料齐全 -->
		<view v-else class="logged-wrap">
			<view class="profile-card">
				<view class="profile-head">
					<image class="avatar lg" :src="profile.avatar || '/static/logo.png'" mode="aspectFill"></image>
					<view class="profile-main">
						<view class="name-row">
							<text class="nickname">{{ profile.nickname }}</text>
							<text v-if="profileSubjectLabel" class="identity-tag">{{ profileSubjectLabel }}</text>
						</view>
						<view v-if="displayCompany" class="company-row">
							<text class="company">{{ displayCompany }}</text>
							<view v-if="isOrgCertified" class="cert-badge">
								<image class="cert-badge-icon" src="/static/icons/mine/certification-badge.png" mode="aspectFit"></image>
								<text>认证</text>
							</view>
						</view>
					</view>
				</view>
				<view v-if="profileCapabilityLabels.length" class="tag-row">
					<text
						v-for="label in profileCapabilityLabels"
						:key="label"
						class="cap-tag"
					>{{ label }}</text>
				</view>
				<view class="contact-list">
					<view class="contact-row">
						<image class="contact-icon" src="/static/icons/mine/phone.png" mode="aspectFit"></image>
						<text class="contact-label">电话</text>
						<text class="contact-value">{{ profile.phone || '未填写' }}</text>
					</view>
					<view class="contact-row">
						<image class="contact-icon" src="/static/icons/mine/email.png" mode="aspectFit"></image>
						<text class="contact-label">邮箱</text>
						<text class="contact-value">{{ profile.email || '未填写' }}</text>
					</view>
					<view class="contact-row">
						<image class="contact-icon" src="/static/icons/mine/wechat.png" mode="aspectFit"></image>
						<text class="contact-label">微信</text>
						<text class="contact-value">{{ profile.wechat || '未填写' }}</text>
					</view>
				</view>
			</view>

			<view :class="'org-card org-card-' + certification.status">
      <image class="org-card-bg" src="/static/images/mine/org-certification-bg.png" mode="aspectFit"></image>
				<view class="org-card-content">
					<image class="org-card-icon" src="/static/icons/mine/org-certification.png" mode="aspectFit"></image>
					<view :class="certification.canApply ? 'org-card-main org-card-main-actionable' : 'org-card-main'">
						<view class="org-card-heading">
							<text class="org-card-title">机构认证</text>
							<text class="org-role admin" v-if="certification.status === 'certified_admin'">机构管理员</text>
							<text class="org-role" v-else-if="certification.status === 'certified_member'">认证成员</text>
						</view>
						<view v-if="memberships.length">
							<view v-for="m in memberships" :key="m.id" class="org-row">
								<view class="org-info">
									<view class="org-name-row">
										<text class="org-name">{{ m.orgName }}</text>
									</view>
								</view>
								<view v-if="m.role === 'admin'" class="org-actions">
									<button class="org-manage-btn" size="mini" @click="goOrgManage()">进入机构管理</button>
								</view>
							</view>
						</view>
						<view v-else class="org-none">
							<view v-if="certification.canApply" class="org-none-actions">
								<button class="org-action-btn" size="mini" @click="goOrgJoin">加入机构</button>
								<button class="org-action-btn ghost" size="mini" @click="goOrgApply">机构入驻</button>
							</view>
							<text v-else class="org-none-text">{{ certificationHint }}</text>
						</view>
					</view>
				</view>
			</view>

			<view class="module-grid">
				<view class="module-box" @click="goMyList('demand')">
					<image class="module-icon" src="/static/icons/mine/demand.png" mode="aspectFit"></image>
					<view class="module-body">
						<text class="module-title">我发布的需求</text>
						<text class="module-count">已发布 {{ myDemandCount }} 条</text>
						<text class="module-pending">待审核 {{ myDemandPendingCount }} 条</text>
					</view>
				</view>
				<view class="module-box" @click="goMyList('result')">
					<image class="module-icon" src="/static/icons/mine/result.png" mode="aspectFit"></image>
					<view class="module-body">
						<text class="module-title">我发布的成果</text>
						<text class="module-count">已发布 {{ myResultCount }} 条</text>
						<text class="module-pending">待审核 {{ myResultPendingCount }} 条</text>
					</view>
				</view>
				<view class="module-box" @click="goMyList('favorite')">
					<image class="module-icon" src="/static/icons/mine/favorite.png" mode="aspectFit"></image>
					<view class="module-body">
						<text class="module-title">我的收藏</text>
						<text class="module-count">需求 {{ favoriteDemandCount }} 条</text>
						<text class="module-pending">成果 {{ favoriteResultCount }} 条</text>
					</view>
				</view>
				<view class="module-box" @click="goMyList('intention')">
					<image class="module-icon" src="/static/icons/mine/intention.png" mode="aspectFit"></image>
					<view class="module-body">
						<text class="module-title">意向请求</text>
						<text class="module-count">需处理 {{ intentionPendingCount }} 个</text>
						<text class="module-pending">成功对接 {{ intentionSuccessCount }} 个</text>
					</view>
				</view>
			</view>

			<view class="bottom-actions">
				<button class="ghost-btn" @click="onEdit">编辑资料</button>
				<button class="ghost-btn danger" @click="onLogout">退出登录</button>
			</view>
		</view>

		<!-- 底部导航（分包业务壳统一 tab：首页 / AI匹配 / 我的） -->
		<AppTabbar active="mine" />
	</view>
</template>

<script>
	import AppTabbar from '../../components/app-tabbar.vue'
	import {
			getUserProfile,
			isLoggedIn,
			isAuthenticated,
			needsProfile,
			saveUserProfile,
			logout,
			registerAccount,
			loginAccount,
			listCachedAccounts,
			getSessionPhone,
			SUBJECT_TYPE_OPTIONS,
			CAPABILITY_OPTIONS,
			getSubjectTypeLabel,
			getCapabilityLabels,
			normalizeCapabilities
		} from '../../api/user.js'
	import { getMyDemands } from '../../api/demand.js'
	import { getMyAchievements } from '../../api/achievement.js'
	import { getMyFavorites, getMyCooperations } from '../../api/interaction.js'
	import { getPendingPublishRoute } from '../../api/publish-draft.mjs'
	import {
		fetchCurrentUser,
		getMyOrganizationCertification,
		getCachedOrganizationCertification,
		isOrganizationCertificationCacheFresh,
		cacheOrganizationCertification,
		clearCachedOrganizationCertification,
		searchInstitutions,
	} from '../../api/membership.js'
	import { validateEmail, validatePhone } from '../../api/contact-validation.mjs'
	import HostBridge from '../../../../host/host-bridge.js'
	import { createPageStateMixin, getPageStateScope } from '../../api/page-state-cache.mjs'

	export default {
		components: {
			AppTabbar,
		},
		mixins: [createPageStateMixin({
			route: 'pages/mine/mine',
			groups: [{
				name: 'dashboard', dataClass: 'list', fields: [
					'viewMode', 'editing', 'profile', 'form', 'memberships', 'certification',
					'myDemandCount', 'myDemandPendingCount', 'myResultCount', 'myResultPendingCount',
					'favoriteDemandCount', 'favoriteResultCount', 'intentionPendingCount', 'intentionSuccessCount'
				]
			}],
		})],
		data() {
			const cachedCertification = getCachedOrganizationCertification()
			const initialCertification = cachedCertification && cachedCertification.certification
			return {
				viewMode: 'auth',
				authMode: 'login',
				editing: false,
				showAvatarSheet: false,
				profile: null,
				authPhone: '',
				authForm: {
					phone: '',
					password: ''
				},
				cachedAccounts: [],
				capabilityOptions: CAPABILITY_OPTIONS,
				form: {
					avatar: '/static/logo.png',
					nickname: '',
					company: '',
					subjectType: '',
					businessCapabilities: [],
					phone: '',
					email: '',
					wechat: ''
				},
				myDemandCount: 0,
				myDemandPendingCount: 0,
				myResultCount: 0,
				myResultPendingCount: 0,
				favoriteDemandCount: 0,
				favoriteResultCount: 0,
				intentionPendingCount: 0,
				intentionSuccessCount: 0,
				companySuggestions: [],
				showingCompanySuggestions: false,
				companySuggestionRequestId: 0,
				memberships: (initialCertification && initialCertification.memberships) || [],
				certification: initialCertification || { status: 'unverified', label: '未认证', canApply: true, pendingName: '' }
			}
		},
		computed: {
			profileSubjectLabel() {
				return getSubjectTypeLabel(this.profile && this.profile.subjectType)
			},
			profileCapabilityLabels() {
				return getCapabilityLabels((this.profile && this.profile.businessCapabilities) || [])
			},
			subjectPickerOptions() {
				return [{ label: '请选择主体类型', value: '' }].concat(SUBJECT_TYPE_OPTIONS)
			},
			subjectTypeIndex() {
				const idx = this.subjectPickerOptions.findIndex((o) => o.value === this.form.subjectType)
				return idx >= 0 ? idx : 0
			},
			subjectTypeText() {
				return getSubjectTypeLabel(this.form.subjectType)
			},
			certificationHint() {
				if (this.certification.status === 'membership_pending') {
					return '正在申请加入：' + (this.certification.pendingName || '机构')
				}
				if (this.certification.status === 'organization_pending') {
					return '机构入驻审核中：' + (this.certification.pendingName || '待命名机构')
				}
				return '选择认证方式后可绑定机构身份'
			},
			isOrgCertified() {
				return this.certification.status === 'certified_admin' || this.certification.status === 'certified_member'
			},
			certifiedOrgName() {
				const primary = this.certification && this.certification.primaryMembership
				if (primary && primary.orgName) return primary.orgName
				const first = this.memberships && this.memberships[0]
				return (first && first.orgName) || ''
			},
			displayCompany() {
				return this.certifiedOrgName || (this.profile && this.profile.company) || ''
			}
		},
		onShow() {
			return this.refresh()
		},
		methods: {
			async refresh() {
				const requestId = (this._dashboardRequestId || 0) + 1
				this._dashboardRequestId = requestId
				const scope = getPageStateScope()
				this.cachedAccounts = listCachedAccounts()
				this.authPhone = getSessionPhone()
				this.profile = getUserProfile()

				if (this.editing) {
				this.viewMode = 'profile'
			} else if (isLoggedIn() && !needsProfile()) {
				this.viewMode = 'home'
			} else if (isAuthenticated() || needsProfile()) {
				this.viewMode = 'profile'
				if (this.profile) this.fillForm(this.profile)
				else {
					this.form.phone = this.authPhone
				}
			} else {
				this.viewMode = 'auth'
			}
				const loaded = await Promise.all([
					this.loadMyPublicationCounts(),
					this.loadInteractionCounts(),
					this.loadMemberships(),
				])
				if (this._dashboardRequestId !== requestId || getPageStateScope() !== scope) return

				if (this.profile && this.viewMode === 'home') {
					this.fillForm(this.profile)
				}
				if (loaded.every(Boolean)) this.markPageStateFresh('dashboard')
			},
			async loadMemberships() {
				if (!isLoggedIn()) {
					this.memberships = []
					this.certification = { status: 'unverified', label: '未认证', canApply: true, pendingName: '' }
					return true
				}
				const cachedCertification = getCachedOrganizationCertification()
				if (cachedCertification) {
					this.certification = cachedCertification.certification
					this.memberships = cachedCertification.certification.memberships || []
					if (isOrganizationCertificationCacheFresh(cachedCertification)) return true
				}
				try {
					const [user, certification] = await Promise.all([
						fetchCurrentUser(),
						getMyOrganizationCertification()
					])
					this.certification = certification
					this.memberships = certification.memberships
					cacheOrganizationCertification(certification)
					this.profile = getUserProfile()
					return true
				} catch (e) {
					console.error('[mine] loadMemberships failed:', e)
					return false
				}
			},
			async loadMyPublicationCounts() {
				const requestId = (this._publicationRequestId || 0) + 1
				this._publicationRequestId = requestId
				const scope = getPageStateScope()
				if (!isLoggedIn()) {
					this.myDemandCount = 0
					this.myDemandPendingCount = 0
					this.myResultCount = 0
					this.myResultPendingCount = 0
					return true
				}
				try {
					const [demands, pendingDemands, achievements, pendingAchievements] = await Promise.all([
						getMyDemands({ page: 1, pageSize: 1, status: 'published' }),
						getMyDemands({ page: 1, pageSize: 1, status: 'pending_review' }),
						getMyAchievements({ page: 1, pageSize: 1, status: 'published' }),
						getMyAchievements({ page: 1, pageSize: 1, status: 'pending_review' })
					])
					if (this._publicationRequestId !== requestId || getPageStateScope() !== scope) return false
					this.myDemandCount = demands.total || 0
					this.myDemandPendingCount = pendingDemands.total || 0
					this.myResultCount = achievements.total || 0
					this.myResultPendingCount = pendingAchievements.total || 0
					return true
				} catch (e) {
					console.error('[mine] loadMyPublicationCounts failed:', e)
					return false
				}
			},
			async loadInteractionCounts() {
				const requestId = (this._interactionRequestId || 0) + 1
				this._interactionRequestId = requestId
				const scope = getPageStateScope()
				const isCurrent = () => this._interactionRequestId === requestId && getPageStateScope() === scope
				if (!isLoggedIn()) {
					this.favoriteDemandCount = 0
					this.favoriteResultCount = 0
					this.intentionPendingCount = 0
					this.intentionSuccessCount = 0
					return true
				}
				const favorites = Promise.all([
					getMyFavorites('demand', { page: 1, pageSize: 1 }),
					getMyFavorites('result', { page: 1, pageSize: 1 }),
				]).then(([favDemand, favResult]) => {
					if (!isCurrent()) return false
					this.favoriteDemandCount = favDemand.total || 0
					this.favoriteResultCount = favResult.total || 0
					return true
				}).catch(e => {
					console.error('[mine] loadFavoriteCounts failed:', e)
					return false
				})
				const cooperations = Promise.all([
					getMyCooperations({ role: 'both', status: 'pending', page: 1, pageSize: 1 }),
					getMyCooperations({ role: 'both', status: 'accepted', page: 1, pageSize: 1 }),
					getMyCooperations({ role: 'both', status: 'confirmed', page: 1, pageSize: 1 }),
					getMyCooperations({ role: 'both', status: 'completed', page: 1, pageSize: 1 }),
				]).then(([pending, accepted, confirmed, completed]) => {
					if (!isCurrent()) return false
					this.intentionPendingCount = (pending.total || 0) + (accepted.total || 0)
					this.intentionSuccessCount = (confirmed.total || 0) + (completed.total || 0)
					return true
				}).catch(e => {
					console.error('[mine] loadCooperationCounts failed:', e)
					return false
				})
				const loaded = await Promise.all([favorites, cooperations])
				return loaded.every(Boolean)
			},
			toggleAuthMode() {
				this.authMode = this.authMode === 'login' ? 'register' : 'login'
			},
			onAuthInput(key, e) {
				this.authForm[key] = e.detail.value
			},
			fillCachedAccount(item) {
				this.authForm.phone = item.phone
				this.authForm.password = ''
				this.authMode = 'login'
				uni.showToast({ title: '已填入手机号，请输入密码', icon: 'none' })
			},
			async onAuthSubmit() {
			const phone = (this.authForm.phone || '').trim()
			const password = (this.authForm.password || '').trim()
			uni.showLoading({ title: this.authMode === 'register' ? '注册中...' : '登录中...', mask: true })
			let res
			try {
				res = this.authMode === 'register'
					? await registerAccount(phone, password)
					: await loginAccount(phone, password)
			} finally {
				uni.hideLoading()
			}
			if (!res.ok) {
				uni.showToast({ title: res.message || '操作失败', icon: 'none', duration: 2500 })
				return
			}
			this.authForm.password = ''
			this.editing = false
			uni.showToast({
				title: this.authMode === 'register' ? '注册成功' : '登录成功',
				icon: 'success'
			})
			await this.refresh()
			if (!res.needProfile) this.resumePublishDraftAfterLogin()
		},
			fillForm(profile) {
				this.form = {
					avatar: profile.avatar || '/static/logo.png',
					nickname: profile.nickname || '',
					company: this.isOrgCertified ? this.certifiedOrgName : (profile.company || ''),
					subjectType: profile.subjectType || '',
					businessCapabilities: normalizeCapabilities(profile.businessCapabilities || []),
					phone: profile.phone || getSessionPhone() || '',
					email: profile.email || '',
					wechat: profile.wechat || ''
				}
			},
			onSubjectTypeChange(e) {
				const opt = this.subjectPickerOptions[Number(e.detail.value)] || this.subjectPickerOptions[0]
				this.form.subjectType = opt ? opt.value : ''
			},
			isCapSelected(value) {
				return this.form.businessCapabilities.indexOf(value) >= 0
			},
			toggleCapability(value) {
				const idx = this.form.businessCapabilities.indexOf(value)
				if (idx >= 0) {
					this.form.businessCapabilities.splice(idx, 1)
				} else {
					this.form.businessCapabilities.push(value)
				}
			},
			onFieldInput(key, e) {
				this.form[key] = e.detail.value
			},
			showCompanySuggestions() {
				this.showingCompanySuggestions = true
				this.loadCompanySuggestions(this.form.company)
			},
			onCompanyInput(e) {
				this.form.company = e.detail.value
				this.showingCompanySuggestions = true
				this.loadCompanySuggestions(e.detail.value)
			},
			async loadCompanySuggestions(keyword) {
				const requestId = ++this.companySuggestionRequestId
				try {
					const data = await searchInstitutions(keyword, 1, 8)
					if (requestId !== this.companySuggestionRequestId) return
					this.companySuggestions = data.list || []
				} catch (e) {
					if (requestId === this.companySuggestionRequestId) this.companySuggestions = []
				}
			},
			selectCompanySuggestion(org) {
				this.form.company = org.name || ''
				this.showingCompanySuggestions = false
			},
			onWxAvatar(e) {
				const url = e.detail && e.detail.avatarUrl
				if (url) {
					this.form.avatar = url
					uni.showToast({ title: '已使用微信头像', icon: 'none' })
				}
				this.closeAvatarSheet()
			},
			openAvatarSheet() {
				this.showAvatarSheet = true
			},
			closeAvatarSheet() {
				this.showAvatarSheet = false
			},
			onChooseAlbum() {
				this.closeAvatarSheet()
				uni.chooseImage({
					count: 1,
					sizeType: ['compressed'],
					sourceType: ['album', 'camera'],
					success: (res) => {
						const path = res.tempFilePaths && res.tempFilePaths[0]
						if (path) this.form.avatar = path
					}
				})
			},
			onNicknameBlur(e) {
				const val = (e.detail.value || '').trim()
				if (val) this.form.nickname = val
			},
			async onSaveProfile() {
				const nickname = (this.form.nickname || '').trim()
				const company = (this.form.company || '').trim()
				const email = (this.form.email || '').trim()
				const wechat = (this.form.wechat || '').trim()
				if (!nickname) {
					uni.showToast({ title: '请填写昵称', icon: 'none' })
					return
				}
				if (!this.isOrgCertified && !company) {
					uni.showToast({ title: '请填写公司', icon: 'none' })
					return
				}
				if (!this.form.subjectType) {
					uni.showToast({ title: '请选择主体类型', icon: 'none' })
					return
				}
				const emailCheck = validateEmail(email, { required: true })
				if (!emailCheck.ok) {
					uni.showToast({ title: emailCheck.message, icon: 'none' })
					return
				}
				const phoneCheck = validatePhone(this.form.phone || getSessionPhone(), { required: false })
				if (!phoneCheck.ok) {
					uni.showToast({ title: phoneCheck.message, icon: 'none' })
					return
				}
				if (!wechat) {
					uni.showToast({ title: '请填写微信号', icon: 'none' })
					return
				}
				this.form.nickname = nickname
				this.form.company = this.isOrgCertified ? (this.profile && this.profile.company) || '' : company
				this.form.email = emailCheck.value
				this.form.wechat = wechat
				this.form.wechat = wechat
				this.form.phone = getSessionPhone()
				const wasEditing = this.editing
				uni.showLoading({ title: '保存中...', mask: true })
				let saved = null
				try {
					saved = await saveUserProfile(this.form)
				} finally {
					uni.hideLoading()
				}
				if (!saved) return
				this.profile = saved
				this.editing = false
				uni.showToast({ title: wasEditing ? '保存成功' : '资料已完善', icon: 'success' })
				await this.refresh()
				this.resumePublishDraftAfterLogin()
			},
			resumePublishDraftAfterLogin() {
				const route = getPendingPublishRoute()
				if (!route) return
				// 登录和资料补全后都从这里恢复发布页；草稿仅在真正发布成功后清除。
				setTimeout(() => HostBridge.navigate(route), 250)
			},
			onEdit() {
				if (this.profile) this.fillForm(this.profile)
				this.editing = true
				this.viewMode = 'profile'
			},
			onCancelEdit() {
				this.editing = false
				this.refresh()
			},
			onLogout() {
				uni.showModal({
					title: '提示',
					content: '退出后账号仍会保留登录历史，可再次登录切换',
					success: async (res) => {
						if (!res.confirm) return
						await logout()
						this.editing = false
						this.authForm.password = ''
						this.form = {
							avatar: '/static/logo.png',
							nickname: '',
							company: '',
							subjectType: '',
							businessCapabilities: [],
							phone: '',
							email: '',
							wechat: ''
						}
						this.refresh()
					}
				})
			},
			goMyList(type) {
				HostBridge.navigate('pages/my-list/my-list', { type })
			},
			goOrgJoin() {
				clearCachedOrganizationCertification()
				HostBridge.navigate('pages/org-join/org-join')
			},
			goOrgApply() {
				clearCachedOrganizationCertification()
				HostBridge.navigate('pages/org-apply/org-apply')
			},
			goOrgManage() {
				HostBridge.navigate('pages/org-manage/org-manage')
			}
		}
	}
</script>

<style>
	.page {
		min-height: 100vh;
		background: #f5f6f8;
		padding: 24rpx;
		padding-bottom: calc(80rpx + env(safe-area-inset-bottom));
		box-sizing: border-box;
	}

	.login-card,
	.profile-card {
		background: #ffffff;
		border-radius: 16rpx;
		padding: 32rpx;
		border: 1rpx solid #e8ecf2;
	}

	.login-title {
		display: block;
		font-size: 34rpx;
		font-weight: 600;
		color: #1a1a1a;
		margin-bottom: 8rpx;
	}

	.login-desc {
		display: block;
		font-size: 24rpx;
		color: #999999;
		margin-bottom: 28rpx;
		line-height: 1.5;
	}

	.switch-auth {
		display: block;
		text-align: center;
		margin-top: 24rpx;
		font-size: 26rpx;
		color: #2b73f8;
	}

	.cache-box {
		margin-top: 36rpx;
		padding-top: 24rpx;
		border-top: 1rpx solid #eef0f4;
	}

	.cache-title {
		display: block;
		font-size: 24rpx;
		color: #888888;
		margin-bottom: 16rpx;
	}

	.cache-list {
		display: flex;
		flex-direction: column;
	}

	.cache-item {
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 20rpx 24rpx;
		margin-bottom: 12rpx;
	}

	.cache-phone {
		display: block;
		font-size: 28rpx;
		color: #222222;
		font-weight: 600;
	}

	.cache-meta {
		display: block;
		margin-top: 6rpx;
		font-size: 22rpx;
		color: #999999;
	}

	.avatar-block {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: center;
		margin-bottom: 28rpx;
	}

	.avatar {
		width: 120rpx;
		height: 120rpx;
		border-radius: 60rpx;
		background: #eef2f8;
		flex-shrink: 0;
	}

	.avatar.lg {
		width: 112rpx;
		height: 112rpx;
		border-radius: 56rpx;
	}

	.profile-head {
		display: flex;
		flex-direction: row;
		align-items: center;
	}

	.profile-main {
		flex: 1;
		min-width: 0;
		margin-left: 24rpx;
	}

	.name-row {
		display: flex;
		flex-direction: row;
		align-items: center;
		min-width: 0;
	}

	.nickname {
		flex-shrink: 1;
		min-width: 0;
		font-size: 34rpx;
		font-weight: 600;
		color: #1a1a1a;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.identity-tag {
		flex-shrink: 0;
		margin-left: 12rpx;
		font-size: 20rpx;
		color: #2b73f8;
		background: rgba(43, 115, 248, 0.1);
		padding: 4rpx 12rpx;
		border-radius: 8rpx;
	}

	.company {
		display: block;
		margin-top: 8rpx;
		font-size: 24rpx;
		color: #888888;
		line-height: 1.4;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.company-row {
		display: flex;
		flex-direction: row;
		align-items: center;
		margin-top: 8rpx;
	}

	.company-row .company {
		margin-top: 0;
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

	.tag-row {
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
		margin-top: 20rpx;
	}

	.cap-tag {
		font-size: 22rpx;
		color: #0f9d58;
		background: rgba(15, 157, 88, 0.08);
		padding: 6rpx 14rpx;
		border-radius: 8rpx;
		margin: 0 12rpx 8rpx 0;
	}

	.contact-list {
		margin-top: 12rpx;
		padding-top: 8rpx;
		border-top: 1rpx solid #eef0f4;
	}

	.contact-row {
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 12rpx 0;
	}

	.contact-icon {
		width: 64rpx;
		height: 64rpx;
		flex-shrink: 0;
		margin-right: 16rpx;
	}

	.contact-label {
		width: 80rpx;
		flex-shrink: 0;
		font-size: 24rpx;
		color: #999999;
		line-height: 1.5;
	}

	.contact-value {
		flex: 1;
		min-width: 0;
		font-size: 26rpx;
		color: #333333;
		line-height: 1.5;
		word-break: break-all;
	}

	.cert-badge {
		display: flex;
		align-items: center;
		margin-left: 12rpx;
		padding: 4rpx 12rpx 4rpx 8rpx;
		border-radius: 10rpx;
		font-size: 22rpx;
		line-height: 1.2;
		color: #0f9d58;
		background: rgba(15, 157, 88, 0.1);
	}

	.cert-badge-icon {
		width: 34rpx;
		height: 34rpx;
		margin-right: 4rpx;
	}

	.sheet-mask {
		position: fixed;
		left: 0;
		right: 0;
		top: 0;
		bottom: 0;
		background: rgba(0, 0, 0, 0.45);
		z-index: 1000;
		display: flex;
		align-items: flex-end;
	}

	.sheet-panel {
		width: 100%;
		background: #f5f6f8;
		border-radius: 24rpx 24rpx 0 0;
		padding: 16rpx 24rpx calc(16rpx + env(safe-area-inset-bottom));
		box-sizing: border-box;
	}

	.sheet-item {
		height: 96rpx;
		line-height: 96rpx;
		text-align: center;
		background: #ffffff;
		font-size: 30rpx;
		color: #222222;
		border-radius: 12rpx;
		margin-bottom: 2rpx;
	}

	.sheet-btn {
		margin: 0;
		padding: 0;
		background: #ffffff;
		font-size: 30rpx;
		color: #222222;
		border-radius: 12rpx 12rpx 0 0;
	}

	.sheet-btn::after {
		border: none;
	}

	.sheet-cancel {
		margin-top: 16rpx;
		height: 96rpx;
		line-height: 96rpx;
		text-align: center;
		background: #ffffff;
		border-radius: 12rpx;
		font-size: 30rpx;
		color: #666666;
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

	.input {
		height: 80rpx;
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 0 24rpx;
		font-size: 28rpx;
	}

	.input-disabled {
		color: #999999;
	}

	.company-select {
		position: relative;
		z-index: 3;
	}

	.company-suggestion-list {
		position: absolute;
		z-index: 4;
		top: 84rpx;
		left: 0;
		right: 0;
		max-height: 300rpx;
		overflow-y: auto;
		background: #ffffff;
		border: 1rpx solid #d8e5f6;
		border-radius: 12rpx;
		box-shadow: 0 12rpx 28rpx rgba(37, 104, 193, 0.14);
	}

	.company-suggestion-item {
		padding: 20rpx 24rpx;
		font-size: 26rpx;
		color: #2b3a50;
		border-bottom: 1rpx solid #edf2f8;
	}

	.company-suggestion-item:last-child {
		border-bottom: 0;
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

	.optional {
		font-size: 22rpx;
		color: #999999;
		font-weight: 400;
	}

	.cap-row {
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
	}

	.cap-btn {
		height: 64rpx;
		line-height: 64rpx;
		padding: 0 26rpx;
		text-align: center;
		background: #f7f9fc;
		border-radius: 32rpx;
		margin: 0 16rpx 16rpx 0;
		font-size: 26rpx;
		color: #666666;
	}

	.cap-btn.active {
		background: rgba(43, 115, 248, 0.12);
		color: #2b73f8;
		font-weight: 600;
	}

	.cap-tip {
		display: block;
		font-size: 22rpx;
		color: #999999;
		line-height: 1.5;
	}

	.login-btn {
		margin-top: 12rpx;
		background: #2b73f8;
		color: #ffffff;
		border-radius: 12rpx;
	}

	.cancel-btn {
		margin-top: 16rpx;
		background: #ffffff;
		color: #666666;
		border: 1rpx solid #dddddd;
		border-radius: 12rpx;
	}

	.org-card {
		position: relative;
		overflow: hidden;
		min-height: 176rpx;
		margin-top: 24rpx;
		background: linear-gradient(135deg, #f8fbff 0%, #e3f1ff 100%);
		border-radius: 16rpx;
		padding: 28rpx 32rpx;
		border: 1rpx solid #a9caff;
		box-sizing: border-box;
	}

.org-card-bg {
  position: absolute;
  left: auto;
  right: -8rpx;
  top: 0;
  bottom: 0;
  width: 76%;
  height: 100%;
  opacity: 0.92;
}

	.org-card-content {
		position: relative;
		display: flex;
		align-items: flex-start;
	}

	.org-card-icon {
		width: 112rpx;
		height: 112rpx;
		flex-shrink: 0;
		margin: 0 20rpx 0 0;
	}

	.org-card-main {
		flex: 1;
		min-width: 0;
	}

	.org-card-certified_admin {
		background: linear-gradient(135deg, #f8fbff 0%, #e3f1ff 100%);
		border-color: #a9caff;
	}

	.org-card-certified_member {
		background: linear-gradient(135deg, #f8fbff 0%, #e3f1ff 100%);
		border-color: #a9caff;
	}

	.org-card-membership_pending,
	.org-card-organization_pending {
		background: linear-gradient(135deg, #f8fbff 0%, #e3f1ff 100%);
		border-color: #a9caff;
	}

	.org-card-unverified {
		min-height: 132rpx;
		background: linear-gradient(135deg, #f8fbff 0%, #e3f1ff 100%);
		border-color: #a9caff;
	}

	.org-card-unverified .org-card-content {
		align-items: center;
	}

	.org-card-unverified .org-card-icon {
		width: 88rpx;
		height: 88rpx;
		margin-right: 16rpx;
	}

	.org-card-main-actionable {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		gap: 14rpx;
	}

	.org-card-main-actionable .org-card-heading {
		width: auto;
		margin-bottom: 0;
		flex-shrink: 0;
	}

	.org-card-heading {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		flex-wrap: nowrap;
		width: 100%;
		margin-bottom: 18rpx;
	}

	.org-card-title {
		font-size: 28rpx;
		font-weight: 600;
		color: #1a1a1a;
	}

	.org-none-text {
		display: block;
		font-size: 26rpx;
		color: #5e718b;
		line-height: 1.5;
		margin-bottom: 18rpx;
	}

	.org-none-actions {
		display: flex;
		flex-direction: row;
		gap: 16rpx;
		flex: 1;
	}

	.org-action-btn {
		flex: 1;
		margin: 0;
		min-height: 56rpx;
		line-height: 54rpx;
		background: transparent;
		color: #2b73f8;
		border: 1rpx solid #2b73f8;
		border-radius: 12rpx;
		font-size: 22rpx;
		font-weight: 600;
	}

	.org-action-btn.ghost {
		background: transparent;
		color: #5e718b;
		border-color: #aabfd9;
	}

	.org-row {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		padding: 10rpx 0;
	}

	.org-info {
		flex: 1;
		min-width: 0;
	}

	.org-name-row {
		display: flex;
		flex-direction: row;
		align-items: center;
		min-width: 0;
	}

	.org-name {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 28rpx;
		color: #222222;
		font-weight: 600;
		word-break: break-all;
	}

	.org-role {
		flex-shrink: 0;
		margin-left: 12rpx;
		font-size: 22rpx;
		color: #0f9d58;
		background: rgba(15, 157, 88, 0.1);
		padding: 4rpx 12rpx;
		border-radius: 8rpx;
	}

	.org-role.admin {
		color: #2b73f8;
		background: rgba(43, 115, 248, 0.12);
	}

	.org-card-heading .org-role {
		margin-left: 12rpx;
		margin-bottom: 0;
	}

	.org-actions {
		display: flex;
		flex-direction: row;
		align-items: center;
		flex-shrink: 0;
		margin-left: 16rpx;
	}

	.org-manage-btn {
		margin-left: 0;
		background: transparent;
		color: #2b73f8;
		border: 1rpx solid #2b73f8;
		border-radius: 12rpx;
		font-size: 24rpx;
	}

	.module-grid {
		margin-top: 24rpx;
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
		justify-content: space-between;
	}

	.module-box {
		width: calc(50% - 10rpx);
		background: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		margin-bottom: 20rpx;
		padding: 24rpx 20rpx;
		display: flex;
		flex-direction: row;
		align-items: center;
		box-sizing: border-box;
	}

	.module-icon {
		width: 92rpx;
		height: 92rpx;
		flex-shrink: 0;
		margin-right: 18rpx;
	}

	.module-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}

	.module-title {
		font-size: 24rpx;
		color: #222222;
		text-align: left;
		line-height: 1.3;
	}

	.module-count {
		margin-top: 6rpx;
		font-size: 20rpx;
		color: #999999;
	}

	.module-pending {
		margin-top: 2rpx;
		font-size: 20rpx;
		color: #d98a00;
	}

	.bottom-actions {
		margin-top: 48rpx;
		display: flex;
		flex-direction: row;
	}

	.ghost-btn {
		flex: 1;
		margin: 0 8rpx;
		background: #ffffff !important;
		color: #2b73f8 !important;
		border: 1rpx solid #2b73f8 !important;
		border-radius: 12rpx;
		font-size: 28rpx;
	}

	.ghost-btn.danger {
		color: #e74c3c !important;
		border-color: #e74c3c !important;
	}
</style>
