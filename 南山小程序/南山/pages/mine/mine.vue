<template>
	<view class="page">
		<!-- 步骤1：手机号 + 密码 登录/注册 -->
		<view v-if="viewMode === 'auth'" class="login-wrap">
			<view class="login-card">
				<text class="login-title">{{ authMode === 'register' ? '注册账号' : '登录账号' }}</text>
				<text class="login-desc">使用手机号注册，密码设置一次即可；支持本地缓存多账号</text>

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

				<view class="diag-row">
					<text class="diag-link" @click="onCheckStorage">诊断存储</text>
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
					<input class="input" :value="form.company" placeholder="请输入公司名称" @input="onFieldInput('company', $event)" />
				</view>
				<view class="form-item">
					<text class="label">身份 <text class="required">*</text></text>
					<view class="identity-row">
						<view
							:class="form.identity === 'demand' ? 'identity-btn active' : 'identity-btn'"
							@click="setIdentity('demand')"
						>需求方</view>
						<view
							:class="form.identity === 'supply' ? 'identity-btn active' : 'identity-btn'"
							@click="setIdentity('supply')"
						>供给方</view>
					</view>
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
				<view class="profile-top">
					<view class="avatar-col">
						<image class="avatar lg" :src="profile.avatar || '/static/logo.png'" mode="aspectFill"></image>
					</view>
					<view class="profile-info">
						<text class="nickname">{{ profile.nickname }}</text>
						<text class="identity-tag">{{ identityText }}</text>
					</view>
					<view class="profile-divider"></view>
					<view class="contact-side">
						<text class="side-line">电话：{{ profile.phone }}</text>
						<text class="side-line">邮箱：{{ profile.email }}</text>
						<text class="side-line">微信：{{ profile.wechat }}</text>
					</view>
				</view>
				<view class="company-row">
					<text class="company">{{ profile.company }}</text>
				</view>
			</view>

			<view class="module-grid">
				<view class="module-box" @click="goMyList('demand')">
					<view class="module-icon demand-icon">需</view>
					<text class="module-title">我发布的需求</text>
					<text class="module-count">{{ myDemandCount }} 条</text>
				</view>
				<view class="module-box" @click="goMyList('result')">
					<view class="module-icon result-icon">果</view>
					<text class="module-title">我发布的成果</text>
					<text class="module-count">{{ myResultCount }} 条</text>
				</view>
				<view class="module-box" @click="goMyList('favorite')">
					<view class="module-icon fav-icon">藏</view>
					<text class="module-title">我的收藏</text>
					<text class="module-count">{{ favoriteCount }} 条</text>
				</view>
				<view class="module-box" @click="goMyList('intention')">
					<view class="module-icon intent-icon">意</view>
					<text class="module-title">意向请求</text>
					<text class="module-count">{{ intentionCount }} 条</text>
				</view>
			</view>

			<view class="bottom-actions">
				<button class="ghost-btn" @click="onEdit">编辑资料</button>
				<button class="ghost-btn danger" @click="onLogout">退出登录</button>
			</view>
		</view>
	</view>
</template>

<script>
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
		getIdentityLabel,
		getFavorites,
		getSentIntentions,
		getReceivedIntentions,
		getSessionPhone,
		checkStorageHealth
	} from '../../common/user.js'
	import { getMyResults } from '../../common/mock-data.js'
	import { getMyDemands } from '../../common/demand-api.js'

	export default {
		data() {
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
				form: {
					avatar: '/static/logo.png',
					nickname: '',
					company: '',
					identity: 'demand',
					phone: '',
					email: '',
					wechat: ''
				},
				myDemandCount: 0,
				myResultCount: 0,
				favoriteCount: 0,
				intentionCount: 0
			}
		},
		computed: {
			identityText() {
				return getIdentityLabel(this.profile && this.profile.identity)
			}
		},
		onShow() {
			this.refresh()
		},
		methods: {
			refresh() {
				// 首次加载时自动检查存储健康状态
				if (!this._diagDone) {
					this._diagDone = true
					const report = checkStorageHealth()
					if (!report.storageAvailable || report.errors.length > 0) {
						const msgs = report.errors.slice(0, 2).join('；')
						uni.showToast({
							title: '存储异常：' + (msgs || '请点击底部「诊断存储」排查'),
							icon: 'none',
							duration: 3000
						})
					}
				}

				this.cachedAccounts = listCachedAccounts()
				this.authPhone = getSessionPhone()
				this.profile = getUserProfile()

				if (this.editing) {
					this.viewMode = 'profile'
				} else if (isLoggedIn()) {
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

				const phone = this.authPhone || (this.profile && this.profile.phone) || ''
				this.loadMyDemandCount()
				this.myResultCount = getMyResults(phone).length
				this.favoriteCount = getFavorites().length
				this.intentionCount = getSentIntentions(phone).length + getReceivedIntentions(phone).length

				if (this.profile && this.viewMode === 'home') {
					this.fillForm(this.profile)
				}
			},
			async loadMyDemandCount() {
				if (!isLoggedIn()) {
					this.myDemandCount = 0
					return
				}
				try {
					const data = await getMyDemands({ page: 1, pageSize: 1 })
					this.myDemandCount = data.total || 0
				} catch (e) {
					console.error('[mine] loadMyDemandCount failed:', e)
					this.myDemandCount = 0
				}
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
			onAuthSubmit() {
				const phone = (this.authForm.phone || '').trim()
				const password = (this.authForm.password || '').trim()
				const res = this.authMode === 'register'
					? registerAccount(phone, password)
					: loginAccount(phone, password)
				if (!res.ok) {
					const msg = res.message || '操作失败'
					uni.showToast({ title: msg, icon: 'none', duration: 2500 })
					// 如果是存储异常，自动弹出诊断结果
					if (msg.includes('存储') || msg.includes('缓存')) {
						setTimeout(() => { this.onCheckStorage() }, 2600)
					}
					return
				}
				this.authForm.password = ''
				this.editing = false
				uni.showToast({
					title: this.authMode === 'register' ? '注册成功' : '登录成功',
					icon: 'success'
				})
				this.refresh()
			},
			onCheckStorage() {
				const report = checkStorageHealth()
				const lines = []
				if (report.storageAvailable) {
					lines.push('存储状态：正常')
				} else {
					lines.push('存储状态：异常')
				}
				lines.push('已存账号：' + report.accountsCount + ' 个')
				lines.push('当前会话：' + (report.session || '无'))
				if (report.errors.length > 0) {
					lines.push('故障原因：' + report.errors.join('；'))
				}
				if (!report.storageAvailable) {
					lines.push('建议：请在微信中清除小程序缓存后重新进入')
				}
				const content = lines.join('\n')
				uni.showModal({
					title: '存储诊断',
					content: content,
					showCancel: true,
					cancelText: '关闭',
					confirmText: report.storageAvailable ? '知道了' : '去清除缓存',
					success: (res) => {
						if (res.confirm && !report.storageAvailable) {
							// 引导用户手动清除缓存
							uni.showToast({
								title: '请前往微信「设置→通用→存储空间」清理小程序缓存后重试',
								icon: 'none',
								duration: 4000
							})
						}
					}
				})
			},
			fillForm(profile) {
				this.form = {
					avatar: profile.avatar || '/static/logo.png',
					nickname: profile.nickname || '',
					company: profile.company || '',
					identity: profile.identity || 'demand',
					phone: profile.phone || getSessionPhone() || '',
					email: profile.email || '',
					wechat: profile.wechat || ''
				}
			},
			setIdentity(identity) {
				this.form.identity = identity
			},
			onFieldInput(key, e) {
				this.form[key] = e.detail.value
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
			onSaveProfile() {
				const nickname = (this.form.nickname || '').trim()
				const company = (this.form.company || '').trim()
				const email = (this.form.email || '').trim()
				const wechat = (this.form.wechat || '').trim()
				if (!nickname) {
					uni.showToast({ title: '请填写昵称', icon: 'none' })
					return
				}
				if (!company) {
					uni.showToast({ title: '请填写公司', icon: 'none' })
					return
				}
				if (!email) {
					uni.showToast({ title: '请填写邮箱', icon: 'none' })
					return
				}
				if (!wechat) {
					uni.showToast({ title: '请填写微信号', icon: 'none' })
					return
				}
				this.form.nickname = nickname
				this.form.company = company
				this.form.email = email
				this.form.wechat = wechat
				this.form.phone = getSessionPhone()
				const wasEditing = this.editing
				this.profile = saveUserProfile(this.form)
				this.editing = false
				uni.showToast({ title: wasEditing ? '保存成功' : '资料已完善', icon: 'success' })
				this.refresh()
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
					content: '退出后账号仍会缓存在本机，可再次登录切换',
					success: (res) => {
						if (!res.confirm) return
						logout()
						this.editing = false
						this.authForm.password = ''
						this.form = {
							avatar: '/static/logo.png',
							nickname: '',
							company: '',
							identity: 'demand',
							phone: '',
							email: '',
							wechat: ''
						}
						this.refresh()
					}
				})
			},
			goMyList(type) {
				uni.navigateTo({
					url: '/packageA/my-list/my-list?type=' + type
				})
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

	.diag-row {
		display: flex;
		justify-content: flex-end;
		margin-top: 20rpx;
	}

	.diag-link {
		font-size: 24rpx;
		color: #999999;
		text-decoration: underline;
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

	.avatar-col {
		display: flex;
		flex-direction: column;
		align-items: center;
		flex-shrink: 0;
	}

	.profile-info {
		flex: 1 1 auto;
		margin-left: 20rpx;
		max-width: 280rpx;
		min-width: 0;
		display: flex;
		flex-direction: column;
		justify-content: center;
	}

	.nickname {
		display: block;
		width: 100%;
		font-size: 30rpx;
		font-weight: 600;
		color: #1a1a1a;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.identity-tag {
		align-self: flex-start;
		margin-top: 10rpx;
		font-size: 22rpx;
		color: #2b73f8;
		background: rgba(43, 115, 248, 0.1);
		padding: 4rpx 12rpx;
		border-radius: 8rpx;
	}

	.profile-divider {
		width: 6rpx;
		align-self: stretch;
		margin: 8rpx 16rpx;
		background: #d0d5de;
		border-radius: 3rpx;
		flex-shrink: 0;
	}

	.contact-side {
		flex: 1;
		min-width: 0;
	}

	.side-line {
		display: block;
		font-size: 24rpx;
		color: #444444;
		line-height: 1.7;
		word-break: break-all;
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

	.identity-row {
		display: flex;
		flex-direction: row;
	}

	.identity-btn {
		flex: 1;
		height: 72rpx;
		line-height: 72rpx;
		text-align: center;
		background: #f7f9fc;
		border-radius: 12rpx;
		margin-right: 16rpx;
		font-size: 28rpx;
		color: #666666;
	}

	.identity-btn:last-child {
		margin-right: 0;
	}

	.identity-btn.active {
		background: rgba(43, 115, 248, 0.12);
		color: #2b73f8;
		font-weight: 600;
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

	.profile-top {
		display: flex;
		flex-direction: row;
		align-items: center;
	}

	.company-row {
		margin-top: 24rpx;
		padding-top: 20rpx;
		border-top: 1rpx solid #eef0f4;
	}

	.company {
		display: block;
		font-size: 28rpx;
		color: #666666;
		line-height: 1.5;
		word-break: break-all;
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
		height: 220rpx;
		background: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		margin-bottom: 20rpx;
		padding: 24rpx 12rpx;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		box-sizing: border-box;
	}

	.module-icon {
		width: 72rpx;
		height: 72rpx;
		border-radius: 36rpx;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 30rpx;
		font-weight: 600;
		margin-bottom: 16rpx;
	}

	.demand-icon {
		color: #2b73f8;
		background: rgba(43, 115, 248, 0.12);
	}

	.result-icon {
		color: #0f9d58;
		background: rgba(15, 157, 88, 0.12);
	}

	.fav-icon {
		color: #e67e22;
		background: rgba(230, 126, 34, 0.12);
	}

	.intent-icon {
		color: #8e44ad;
		background: rgba(142, 68, 173, 0.12);
	}

	.module-title {
		font-size: 24rpx;
		color: #222222;
		text-align: center;
		line-height: 1.3;
	}

	.module-count {
		margin-top: 8rpx;
		font-size: 22rpx;
		color: #999999;
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
