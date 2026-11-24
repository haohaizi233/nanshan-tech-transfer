<template>
	<view class="page">
		<!-- 步骤1：手机号 + 密码 登录/注册 -->
		<view v-if="viewMode === 'auth'" class="login-wrap">
			<view class="login-card">
				<text class="login-title">{{ authMode === 'register' ? '注册账号' : '登录账号' }}</text>
				<text class="login-desc">使用手机号注册登录，账号数据云端同步，小程序与 H5 通用</text>
				<!-- #ifdef MP-WEIXIN -->
				<view v-if="wechatLoginEnabled" class="wechat-login">
					<button v-if="!wechatPhoneRequired" class="wechat-btn" :disabled="wechatBusy" @click="onWechatLogin">微信快捷登录</button>
					<WechatPrivacyGate v-else-if="privacyAuthorizationNeeded" :contract-name="privacyContractName" @agree="onPrivacyAuthorized" />
					<button v-else class="wechat-btn" open-type="getPhoneNumber" :disabled="wechatBusy" @getphonenumber="onWechatPhone">授权手机号并登录</button>
					<text class="login-desc">首次需授权手机号；已有账号请先用原密码登录后绑定微信</text>
				</view>
				<!-- #endif -->

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
						maxlength="128"
						:value="authForm.password"
						:placeholder="authMode === 'register' ? '设置密码（至少8位）' : '请输入密码'"
						@input="onAuthInput('password', $event)"
					/>
					<text v-if="authMode === 'register'" class="password-hint">密码长度为8–128位，建议组合使用字母、数字和符号。</text>
					<text v-if="authMode === 'register' && authForm.password && authForm.password.trim().length < 8" class="password-error">密码太短，还需输入{{ 8 - authForm.password.trim().length }}位（首尾空格不计入）。</text>
				</view>

				<button class="login-btn" type="primary" @click="onAuthSubmit">
					{{ authMode === 'register' ? '注册并继续' : '登录' }}
				</button>
				<view class="auth-helper-row">
					<text class="switch-auth" @click="toggleAuthMode">
						{{ authMode === 'register' ? '已有账号？去登录' : '没有账号？去注册' }}
					</text>
					<text v-if="authMode === 'login'" class="forgot-pwd-link" @click="openRecoveryModal">
						忘记密码？
					</text>
				</view>

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
					<image class="avatar" :src="avatarDisplayUrl(form.avatar)" mode="aspectFill"></image>
				</view>

				<view v-if="showAvatarSheet" class="sheet-mask" @click="closeAvatarSheet">
					<view class="sheet-panel" @click.stop>
						<!-- #ifdef MP-WEIXIN -->
						<WechatPrivacyGate v-if="privacyAuthorizationNeeded" :contract-name="privacyContractName" @agree="onPrivacyAuthorized" />
						<button v-if="!privacyAuthorizationNeeded" class="sheet-item sheet-btn" open-type="chooseAvatar" @chooseavatar="onWxAvatar">使用微信头像</button>
						<!-- #endif -->
						<button v-if="!privacyAuthorizationNeeded" class="sheet-item sheet-btn" @click="onChooseAlbum">从相册选择</button>
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
					<image class="avatar lg" :src="avatarDisplayUrl(profile.avatar)" mode="aspectFill"></image>
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
      <image class="org-card-bg" src="/static/images/mine/org-certification-bg.jpg" mode="aspectFill"></image>
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

			<button @click="openNotifications">消息通知</button>
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

		<!-- 账号与安全设置卡片（全端统一） -->
		<view v-if="viewMode !== 'auth' && profile" class="login-card account-settings">
			<text class="login-title">账号与安全</text>
			<text class="login-desc">多端统一身份认证、安全联系方式与会话管理</text>

			<view class="security-item">
				<view class="security-meta">
					<text class="security-title">安全手机</text>
					<text class="security-sub">{{ (securityInfo && securityInfo.phone && (securityInfo.phone.value || securityInfo.phone.masked)) ? (securityInfo.phone.value || securityInfo.phone.masked) : '未绑定有效手机号' }}</text>
				</view>
				<button class="security-btn" size="mini" :disabled="!smsFeatureEnabled" @click="openContactModal('phone')">
					{{ !smsFeatureEnabled ? '未启用' : (securityInfo && securityInfo.phone ? '更换' : '绑定') }}
				</button>
			</view>

			<view class="security-item">
				<view class="security-meta">
					<text class="security-title">安全邮箱</text>
					<text class="security-sub">{{ (securityInfo && securityInfo.email && (securityInfo.email.value || securityInfo.email.masked)) ? (securityInfo.email.value || securityInfo.email.masked) : '未绑定有效邮箱' }}</text>
				</view>
				<button class="security-btn" size="mini" :disabled="!emailFeatureEnabled" @click="openContactModal('email')">
					{{ !emailFeatureEnabled ? '未启用' : (securityInfo && securityInfo.email ? '更换' : '绑定') }}
				</button>
			</view>

			<view class="security-item">
				<view class="security-meta">
					<text class="security-title">登录密码</text>
					<text class="security-sub">{{ profile.passwordLoginEnabled !== false ? '已设置（用于全端密码登录）' : '未设置' }}</text>
				</view>
				<button v-if="profile.passwordLoginEnabled !== false" class="security-btn" size="mini" @click="openPasswordModal">修改</button>
				<button v-else class="security-btn primary" size="mini" @click="openSetInitialPasswordModal">设置密码</button>
			</view>

			<!-- #ifdef MP-WEIXIN -->
			<view v-if="wechatLoginEnabled" class="security-item">
				<view class="security-meta">
					<text class="security-title">微信账号</text>
					<text class="security-sub">{{ profile.wechatBound ? '已绑定（支持快捷登录）' : '未绑定微信身份' }}</text>
				</view>
				<WechatPrivacyGate v-if="!profile.wechatBound && privacyAuthorizationNeeded" :contract-name="privacyContractName" @agree="onPrivacyAuthorized" />
				<button v-else-if="!profile.wechatBound" class="security-btn wechat" size="mini" open-type="getPhoneNumber" :disabled="wechatBusy" @getphonenumber="onWechatPhone">授权绑定</button>
				<text v-else class="security-tag-bound">已绑定</text>
			</view>
			<!-- #endif -->

			<view class="security-session-box">
				<button class="revoke-sessions-btn" :disabled="sessionRevokeBusy" @click="onRevokeAllSessions">退出其他设备登录（吊销其他会话）</button>
			</view>
		</view>

		<!-- 弹窗 1：安全联系方式（手机/邮箱）绑定与换绑（含二次认证） -->
		<view v-if="showContactModal" class="dialog-mask" @click="closeContactModal">
			<view class="dialog-panel" @click.stop>
				<view class="dialog-header">
					<text class="dialog-title">
						{{ contactModalStep === 'stepUp' ? '换绑二次身份认证' : (contactModalType === 'phone' ? '绑定安全手机' : (securityInfo && securityInfo.email && securityInfo.email.verified ? '更换安全邮箱' : '绑定安全邮箱')) }}
					</text>
					<text class="dialog-close" @click="closeContactModal">×</text>
				</view>
				<view v-if="contactModalStep === 'stepUp'" class="dialog-body">
					<text class="dialog-desc">更换已确权安全邮箱前，需先完成一次身份复核验证。</text>
					<view v-if="(securityInfo.stepUpMethods || []).length > 1" class="form-item">
						<text class="label">验证方式</text>
						<view class="channel-picker">
							<view
								v-for="m in (securityInfo.stepUpMethods || [])"
								:key="m"
								:class="['channel-tab', contactStepUpMethod === m ? 'active' : '']"
								@click="contactStepUpMethod = m"
							>
								{{ stepUpMethodLabel(m) }}
							</view>
						</view>
					</view>
					<view v-if="contactStepUpMethod === 'password'" class="form-item">
						<text class="label">当前密码</text>
						<input class="input" password maxlength="128" v-model="contactStepUpPassword" placeholder="请输入当前登录密码" />
					</view>
					<view v-else-if="contactStepUpMethod === 'old_email_otp' || contactStepUpMethod === 'old_phone_otp'" class="form-item">
						<text class="label">原安全{{ contactStepUpMethod === 'old_email_otp' ? '邮箱' : '手机' }}验证码</text>
						<view class="code-input-row">
							<input class="input code-input" type="text" maxlength="6" :value="contactStepUpCode" @input="onContactStepUpCodeInput" placeholder="6位数字验证码" />
							<button class="send-code-btn" size="mini" :disabled="contactStepUpCountdown > 0 || contactModalBusy" @click="sendStepUpChallenge">
								{{ contactStepUpCountdown > 0 ? contactStepUpCountdown + 's' : '获取验证码' }}
							</button>
						</view>
					</view>
					<button class="primary-action-btn" :disabled="contactModalBusy" @click="submitStepUpVerify">验证并继续</button>
				</view>
				<view v-else class="dialog-body">
					<text class="dialog-desc">绑定并通过验证后，该联系方式可用于找回密码与安全通知</text>
					<view class="form-item">
						<text class="label">{{ contactModalType === 'phone' ? '手机号' : '新邮箱地址' }}</text>
						<input class="input" :type="contactModalType === 'phone' ? 'number' : 'text'" v-model="contactModalValue" :placeholder="contactModalType === 'phone' ? '请输入11位手机号' : '请输入邮箱地址'" />
					</view>
					<view class="form-item">
						<text class="label">验证码</text>
						<view class="code-input-row">
							<input class="input code-input" type="text" maxlength="6" :value="contactModalCode" @input="onContactCodeInput" placeholder="6位数字验证码" />
							<button class="send-code-btn" size="mini" :disabled="contactModalCountdown > 0 || contactModalBusy" @click="sendContactChallenge">
								{{ contactModalCountdown > 0 ? contactModalCountdown + 's' : '获取验证码' }}
							</button>
						</view>
					</view>
					<button class="primary-action-btn" :disabled="contactModalBusy" @click="submitContactVerify">确认绑定</button>
				</view>
			</view>
		</view>

		<!-- 弹窗 2：密码修改 / 设置初始密码 -->
		<view v-if="showPasswordModal" class="dialog-mask" @click="closePasswordModal">
			<view class="dialog-panel" @click.stop>
				<view class="dialog-header">
					<text class="dialog-title">{{ isSettingInitial ? '设置登录密码' : '修改登录密码' }}</text>
					<text class="dialog-close" @click="closePasswordModal">×</text>
				</view>
				<view class="dialog-body">
					<view v-if="!isSettingInitial" class="form-item">
						<text class="label">当前密码</text>
						<input class="input" password maxlength="128" v-model="pwdModalCurrent" placeholder="请输入当前密码" />
					</view>
					<view class="form-item">
						<text class="label">新密码</text>
						<input class="input" password maxlength="128" v-model="pwdModalNew" placeholder="设置8—128位新密码" />
					</view>
					<view class="form-item">
						<text class="label">确认新密码</text>
						<input class="input" password maxlength="128" v-model="pwdModalConfirm" placeholder="请再次输入新密码" />
					</view>
					<text v-if="passwordError" class="password-feedback-error" role="alert">{{ passwordError }}</text>
					<button class="primary-action-btn" :loading="passwordBusy" :disabled="passwordBusy" @click="submitChangePassword">{{ passwordBusy ? '正在保存，请稍候…' : (isSettingInitial ? '确认设置密码' : '确认修改密码') }}</button>
				</view>
			</view>
		</view>

		<!-- 弹窗 3：找回密码 -->
		<view v-if="showRecoveryModal" class="dialog-mask" @click="closeRecoveryModal">
			<view class="dialog-panel" @click.stop>
				<view class="dialog-header">
					<text class="dialog-title">找回密码</text>
					<text class="dialog-close" @click="closeRecoveryModal">×</text>
				</view>
				<view v-if="recoveryStep === 1" class="dialog-body">
					<text class="dialog-desc">请输入注册账号、安全手机号或安全邮箱，并通过已确权方式完成身份验证</text>
					<view class="form-item">
						<text class="label">账号 / 手机号 / 邮箱</text>
						<input class="input" :value="recoveryAccount" @input="onRecoveryAccountInput" placeholder="请输入用户名、手机号或邮箱" />
					</view>
					<view class="form-item">
						<text class="label">接收通道</text>
						<view class="channel-picker">
							<view :class="['channel-tab', recoveryChannel === 'sms' ? 'active' : '', !recoveryCapabilities.sms ? 'disabled' : '']" @click="selectRecoveryChannel('sms')">
								短信验证码{{ !recoveryCapabilities.sms ? '（未启用）' : '' }}
							</view>
							<view :class="['channel-tab', recoveryChannel === 'email_otp' ? 'active' : '', !recoveryCapabilities.emailOtp ? 'disabled' : '']" @click="selectRecoveryChannel('email_otp')">
								邮箱验证码{{ !recoveryCapabilities.emailOtp ? '（未启用）' : '' }}
							</view>
						</view>
					</view>
					<button class="primary-action-btn" :disabled="recoveryBusy || (!recoveryCapabilities.sms && !recoveryCapabilities.emailOtp)" @click="sendRecoveryChallenge">获取验证码</button>
				</view>
				<view v-else-if="recoveryStep === 2" class="dialog-body">
					<text class="dialog-desc">验证请求已受理。如果账号存在且绑定了可用的安全联系方式，验证码将发送至对应地址。请检查短信或邮箱；若未收到，可稍后重试或切换方式。</text>
					<view class="form-item">
						<text class="label">6位数字验证码</text>
						<input class="input" type="text" maxlength="6" :value="recoveryCode" @input="onRecoveryCodeInput" placeholder="请输入6位验证码" />
					</view>
					<button class="primary-action-btn" :disabled="recoveryBusy" @click="verifyRecoveryCode">验证并下一步</button>
					<view class="countdown-row">
						<text v-if="recoveryCountdown > 0" class="countdown-text">{{ recoveryCountdown }}秒后可重新提交请求</text>
						<text v-else class="resend-text" @click="sendRecoveryChallenge">重新获取验证码</text>
					</view>
				</view>
				<view v-else-if="recoveryStep === 3" class="dialog-body">
					<text class="dialog-desc">身份验证通过，请设置新密码</text>
					<view class="form-item">
						<text class="label">新密码</text>
						<input class="input" password maxlength="128" v-model="recoveryNewPassword" placeholder="设置8—128位新密码" />
					</view>
					<view class="form-item">
						<text class="label">确认新密码</text>
						<input class="input" password maxlength="128" v-model="recoveryConfirmPassword" placeholder="请再次输入新密码" />
					</view>
					<button class="primary-action-btn" :disabled="recoveryBusy" @click="submitRecoveryNewPassword">完成并使用新密码登录</button>
				</view>
			</view>
		</view>
		<!-- 底部导航（分包业务壳统一 tab：首页 / AI匹配 / 我的） -->
		<AppTabbar active="mine" />
	</view>
</template>

<script>
	import AppTabbar from '../../components/app-tabbar.vue'
	import WechatPrivacyGate from '../../components/wechat-privacy-gate.vue'
	import {
			getUserProfile,
			isLoggedIn,
			isAuthenticated,
			needsProfile,
			saveUserProfile,
			logout,
			registerAccount,
			loginAccount,
			loginWithWechat,
			getWechatLoginConfig,
			setInitialPassword,
			changePassword,
			getSecurityInfo,
			getRecoveryCapabilities,
			startSecurityStepUpChallenge,
			verifySecurityStepUp,
			sendSecurityContactChallenge,
			verifySecurityContact,
			revokeAllUserSessions,
			startPasswordRecovery,
			verifyPasswordRecovery,
			completePasswordRecovery,
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
		cacheOrganizationCertification,
		clearCachedOrganizationCertification,
		searchInstitutions,
	} from '../../api/membership.js'
	import { validateEmail, validatePhone } from '../../api/contact-validation.mjs'
	import { mediaDisplayUrl } from '../../api/media-url.mjs'
	import { chooseAvatarImage } from '../../api/avatar-picker.mjs'
	import HostBridge from '../../../../host/host-bridge.js'
	import { createPageStateMixin, getPageStateScope } from '../../api/page-state-cache.mjs'

	export default {
		components: {
			AppTabbar,
			WechatPrivacyGate,
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
				wechatLoginEnabled: false,
				privacyAuthorizationNeeded: false,
				privacyContractName: '',
				wechatPhoneRequired: false,
				wechatBusy: false,
				initialPassword: '',
				passwordBusy: false,
				passwordError: '',
				securityInfo: {
					phone: null,
					email: null,
					wechatBound: false,
					passwordConfigured: true,
					capabilities: { smsEnabled: true, emailEnabled: true },
					stepUpMethods: ['password'],
					sessionVersion: 1
				},
				sessionRevokeBusy: false,
				showContactModal: false,
				contactModalType: 'phone',
				contactModalStep: 'bind',
				contactStepUpMethod: 'password',
				contactStepUpPassword: '',
				contactStepUpChallengeId: null,
				contactStepUpCode: '',
				contactStepUpCountdown: 0,
				contactStepUpTimer: null,
				contactStepUpGrant: null,
				contactModalValue: '',
				contactModalCode: '',
				contactModalChallengeId: null,
				contactModalCountdown: 0,
				contactModalTimer: null,
				contactModalBusy: false,
				showPasswordModal: false,
				isSettingInitial: false,
				pwdModalCurrent: '',
				pwdModalNew: '',
				pwdModalConfirm: '',
				showRecoveryModal: false,
				recoveryStep: 1,
				recoveryAccount: '',
				recoveryChannel: 'sms',
				recoveryCapabilities: { sms: true, emailOtp: false, emailLink: false, cooldownSeconds: 60 },
				recoveryCode: '',
				recoveryChallengeId: null,
				recoveryDestinationMasked: '',
				recoveryGrant: null,
				recoveryNewPassword: '',
				recoveryConfirmPassword: '',
				recoveryCountdown: 0,
				recoveryTimer: null,
				recoveryBusy: false,
				recoveryRequestSeq: 0,
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
					avatarFileId: null,
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
			},
			emailFeatureEnabled() {
				if (!this.securityInfo || !this.securityInfo.capabilities) return true
				return this.securityInfo.capabilities.emailEnabled !== false
			},
			smsFeatureEnabled() {
				if (!this.securityInfo || !this.securityInfo.capabilities) return true
				return this.securityInfo.capabilities.smsEnabled !== false
			}
		},
		onShow() {
			// #ifdef MP-WEIXIN
			this.loadWechatConfig()
			this.loadPrivacySetting()
			// #endif
			return this.refresh()
		},
		onUnload() {
			this.clearSecurityTimers()
		},
		beforeUnmount() {
			this.clearSecurityTimers()
		},
		methods: {
            openNotifications() { uni.navigateTo({url:'/subpackages/tech-transfer/pages/notifications/notifications'}) },
			loadPrivacySetting() {
				// #ifdef MP-WEIXIN
				if (typeof wx !== 'undefined' && typeof wx.getPrivacySetting === 'function') {
					this.privacyAuthorizationNeeded = true
					wx.getPrivacySetting({
						success: result => {
							this.privacyAuthorizationNeeded = !!result.needAuthorization
							this.privacyContractName = result.privacyContractName || ''
						},
						fail: () => uni.showToast({ title: '微信隐私设置读取失败，请重新进入本页', icon: 'none' }),
					})
				}
				// #endif
			},
			onPrivacyAuthorized() {
				this.privacyAuthorizationNeeded = false
			},
			async loadWechatConfig() {
				try {
					const config = await getWechatLoginConfig()
					this.wechatLoginEnabled = config.enabled === true
				} catch {
					this.wechatLoginEnabled = false
				}
			},
			async onWechatLogin(phoneCode) {
				if (this.wechatBusy) return
				this.wechatBusy = true
				const bind = isLoggedIn()
				try {
					const result = await loginWithWechat(typeof phoneCode === 'string' ? phoneCode : undefined, bind)
					if (!result.ok) {
						if (result.code === 'TT_AUTH_40902') this.wechatPhoneRequired = true
						uni.showToast({ title: result.message || '微信登录失败', icon: 'none', duration: 3000 })
						return
					}
					this.wechatPhoneRequired = false
					this.authForm.password = ''
					this.editing = false
					uni.showToast({ title: bind ? '微信绑定成功' : '登录成功', icon: 'success' })
					await this.refresh()
					if (!result.needProfile) this.resumePublishDraftAfterLogin()
				} finally {
					this.wechatBusy = false
				}
			},
			onWechatPhone(event) {
				const code = event.detail && event.detail.code
				if (!code) {
					uni.showToast({ title: '未授权手机号，可使用手机号密码登录', icon: 'none' })
					return
				}
				return this.onWechatLogin(code)
			},
			async loadSecurityInfo() {
				if (!isLoggedIn()) return
				try {
					const info = await getSecurityInfo()
					if (info) this.securityInfo = info
				} catch (e) {
					console.error('[mine] loadSecurityInfo error:', e)
				}
			},
			clearSecurityTimers() {
				if (this.contactModalTimer) {
					clearInterval(this.contactModalTimer)
					this.contactModalTimer = null
				}
				if (this.contactStepUpTimer) {
					clearInterval(this.contactStepUpTimer)
					this.contactStepUpTimer = null
				}
				if (this.recoveryTimer) {
					clearInterval(this.recoveryTimer)
					this.recoveryTimer = null
				}
			},
			stepUpMethodLabel(method) {
				const labels = {
					password: '验证登录密码',
					old_email_otp: '原邮箱验证码',
					old_phone_otp: '原手机验证码',
					recent_auth: '近期安全会话'
				}
				return labels[method] || method
			},
			onContactStepUpCodeInput(e) {
				this.contactStepUpCode = String((e && e.detail && e.detail.value) || '').replace(/\D/g, '').slice(0, 6)
			},
			onContactCodeInput(e) {
				this.contactModalCode = String((e && e.detail && e.detail.value) || '').replace(/\D/g, '').slice(0, 6)
			},
			openContactModal(type) {
				if (type === 'email' && !this.emailFeatureEnabled) {
					uni.showToast({ title: '安全邮箱功能当前未启用', icon: 'none' })
					return
				}
				if (type === 'phone' && !this.smsFeatureEnabled) {
					uni.showToast({ title: '短信验证码功能当前未启用', icon: 'none' })
					return
				}
				this.contactModalType = type
				this.contactModalValue = ''
				this.contactModalCode = ''
				this.contactModalChallengeId = null
				this.contactModalCountdown = 0
				this.contactStepUpPassword = ''
				this.contactStepUpChallengeId = null
				this.contactStepUpCode = ''
				this.contactStepUpCountdown = 0
				this.contactStepUpGrant = null
				if (this.contactModalTimer) {
					clearInterval(this.contactModalTimer)
					this.contactModalTimer = null
				}
				if (this.contactStepUpTimer) {
					clearInterval(this.contactStepUpTimer)
					this.contactStepUpTimer = null
				}
				const needStepUp = type === 'email' && Boolean(this.securityInfo && this.securityInfo.email && this.securityInfo.email.verified)
				if (needStepUp) {
					const methods = (this.securityInfo && Array.isArray(this.securityInfo.stepUpMethods) && this.securityInfo.stepUpMethods.length > 0)
						? this.securityInfo.stepUpMethods
						: ['password']
					this.contactStepUpMethod = methods[0]
					this.contactModalStep = 'stepUp'
				} else {
					this.contactModalStep = 'bind'
				}
				this.showContactModal = true
			},
			closeContactModal() {
				this.showContactModal = false
				this.contactStepUpPassword = ''
				this.contactStepUpCode = ''
				this.contactStepUpGrant = null
				this.contactModalCode = ''
				if (this.contactModalTimer) {
					clearInterval(this.contactModalTimer)
					this.contactModalTimer = null
				}
				if (this.contactStepUpTimer) {
					clearInterval(this.contactStepUpTimer)
					this.contactStepUpTimer = null
				}
			},
			async sendStepUpChallenge() {
				if (this.contactModalBusy) return
				this.contactModalBusy = true
				try {
					const res = await startSecurityStepUpChallenge('rebind_email', this.contactStepUpMethod)
					this.contactStepUpChallengeId = res.challengeId
					uni.showToast({ title: '二次认证验证码已发送', icon: 'success' })
					this.contactStepUpCountdown = 60
					if (this.contactStepUpTimer) clearInterval(this.contactStepUpTimer)
					this.contactStepUpTimer = setInterval(() => {
						if (this.contactStepUpCountdown <= 1) {
							clearInterval(this.contactStepUpTimer)
							this.contactStepUpTimer = null
							this.contactStepUpCountdown = 0
						} else {
							this.contactStepUpCountdown -= 1
						}
					}, 1000)
				} catch (e) {
					if (e && e.retryAfter > 0) {
						this.contactStepUpCountdown = Math.min(3600, Number(e.retryAfter) || 60)
						if (this.contactStepUpTimer) clearInterval(this.contactStepUpTimer)
						this.contactStepUpTimer = setInterval(() => {
							if (this.contactStepUpCountdown <= 1) {
								clearInterval(this.contactStepUpTimer)
								this.contactStepUpTimer = null
								this.contactStepUpCountdown = 0
							} else {
								this.contactStepUpCountdown -= 1
							}
						}, 1000)
					}
					uni.showToast({ title: e.message || '发送失败', icon: 'none' })
				} finally {
					this.contactModalBusy = false
				}
			},
			async submitStepUpVerify() {
				if (this.contactModalBusy) return
				const method = this.contactStepUpMethod
				if (method === 'password' && !this.contactStepUpPassword) {
					uni.showToast({ title: '请输入当前登录密码', icon: 'none' })
					return
				}
				if (method === 'old_email_otp' || method === 'old_phone_otp') {
					if (!this.contactStepUpChallengeId) {
						uni.showToast({ title: '请先获取二次认证验证码', icon: 'none' })
						return
					}
					if ((this.contactStepUpCode || '').trim().length !== 6) {
						uni.showToast({ title: '请输入6位数字验证码', icon: 'none' })
						return
					}
				}
				this.contactModalBusy = true
				try {
					const res = await verifySecurityStepUp({
						purpose: 'rebind_email',
						method,
						currentPassword: method === 'password' ? this.contactStepUpPassword : null,
						challengeId: (method === 'old_email_otp' || method === 'old_phone_otp') ? this.contactStepUpChallengeId : null,
						code: (method === 'old_email_otp' || method === 'old_phone_otp') ? this.contactStepUpCode : null
					})
					if (!res || !res.stepUpGrant) {
						uni.showToast({ title: '二次认证未返回有效凭据', icon: 'none' })
						return
					}
					this.contactStepUpGrant = res.stepUpGrant
					this.contactStepUpPassword = ''
					this.contactStepUpCode = ''
					this.contactModalStep = 'bind'
					uni.showToast({ title: '身份复核通过，请输入新邮箱', icon: 'none' })
				} catch (e) {
					uni.showToast({ title: e.message || '二次身份认证失败', icon: 'none' })
				} finally {
					this.contactModalBusy = false
				}
			},
			async sendContactChallenge() {
				const val = (this.contactModalValue || '').trim()
				if (!val) {
					uni.showToast({ title: this.contactModalType === 'phone' ? '请输入手机号' : '请输入邮箱', icon: 'none' })
					return
				}
				this.contactModalBusy = true
				try {
					const res = await sendSecurityContactChallenge(this.contactModalType, val, this.contactStepUpGrant)
					this.contactModalChallengeId = res.challengeId
					uni.showToast({ title: '验证码已发送', icon: 'success' })
					this.contactModalCountdown = 60
					if (this.contactModalTimer) clearInterval(this.contactModalTimer)
					this.contactModalTimer = setInterval(() => {
						if (this.contactModalCountdown <= 1) {
							clearInterval(this.contactModalTimer)
							this.contactModalTimer = null
							this.contactModalCountdown = 0
						} else {
							this.contactModalCountdown -= 1
						}
					}, 1000)
				} catch (e) {
					if (e && e.retryAfter > 0) {
						this.contactModalCountdown = Math.min(3600, Number(e.retryAfter) || 60)
						if (this.contactModalTimer) clearInterval(this.contactModalTimer)
						this.contactModalTimer = setInterval(() => {
							if (this.contactModalCountdown <= 1) {
								clearInterval(this.contactModalTimer)
								this.contactModalTimer = null
								this.contactModalCountdown = 0
							} else {
								this.contactModalCountdown -= 1
							}
						}, 1000)
					}
					uni.showToast({ title: e.message || '发送失败', icon: 'none' })
				} finally {
					this.contactModalBusy = false
				}
			},
			async submitContactVerify() {
				const val = (this.contactModalValue || '').trim()
				const code = (this.contactModalCode || '').trim()
				if (!val) {
					uni.showToast({ title: '请输入' + (this.contactModalType === 'phone' ? '手机号' : '邮箱'), icon: 'none' })
					return
				}
				if (!this.contactModalChallengeId) {
					uni.showToast({ title: '请先获取验证码', icon: 'none' })
					return
				}
				if (code.length !== 6) {
					uni.showToast({ title: '请输入6位验证码', icon: 'none' })
					return
				}
				this.contactModalBusy = true
				try {
					await verifySecurityContact(this.contactModalChallengeId, code, val, this.contactStepUpGrant)
					uni.showToast({ title: '绑定成功', icon: 'success' })
					this.closeContactModal()
					await this.loadSecurityInfo()
				} catch (e) {
					uni.showToast({ title: e.message || '验证失败', icon: 'none' })
				} finally {
					this.contactModalBusy = false
				}
			},
			openPasswordModal() {
				this.passwordError = ''
				this.isSettingInitial = false
				this.pwdModalCurrent = ''
				this.pwdModalNew = ''
				this.pwdModalConfirm = ''
				this.showPasswordModal = true
			},
			openSetInitialPasswordModal() {
				this.passwordError = ''
				this.isSettingInitial = true
				this.pwdModalCurrent = ''
				this.pwdModalNew = ''
				this.pwdModalConfirm = ''
				this.showPasswordModal = true
			},
			closePasswordModal() {
				if (this.passwordBusy) return
				this.showPasswordModal = false
			},
			async submitChangePassword() {
				if (this.passwordBusy) return
				this.passwordError = ''
				const current = this.pwdModalCurrent.trim()
				const next = this.pwdModalNew.trim()
				const confirm = this.pwdModalConfirm.trim()
				if (!this.isSettingInitial && !current) {
					this.passwordError = '请输入当前密码'
					uni.showToast({ title: '请输入当前密码', icon: 'none' })
					return
				}
				if (next.length < 8 || next.length > 128) {
					this.passwordError = '新密码长度须为8—128位'
					uni.showToast({ title: '新密码长度须为8—128位', icon: 'none' })
					return
				}
				if (next !== confirm) {
					this.passwordError = '两次输入的新密码不一致'
					uni.showToast({ title: '两次输入的新密码不一致', icon: 'none' })
					return
				}
				this.passwordBusy = true
				try {
					if (this.isSettingInitial) {
						await setInitialPassword(next)
					} else {
						await changePassword(current, next)
					}
					this.passwordBusy = false
					this.closePasswordModal()
					this.pwdModalCurrent = ''
					this.pwdModalNew = ''
					this.pwdModalConfirm = ''
					const signingOut = logout().catch(() => {})
					uni.showModal({
						title: this.isSettingInitial ? '密码设置成功' : '密码修改成功',
						content: '登录密码已更新。为保障账号安全，请使用新密码重新登录。',
						showCancel: false,
						confirmText: '重新登录',
						success: async () => {
							await signingOut
							this.profile = null
							this.viewMode = 'auth'
							this.authMode = 'login'
							this.authForm.password = ''
						}
					})
				} catch (e) {
					this.passwordError = e.message || '密码保存失败，请稍后重试'
					uni.showToast({ title: e.message || '密码保存失败', icon: 'none' })
				} finally {
					this.passwordBusy = false
				}
			},
			async onRevokeAllSessions() {
				uni.showModal({
					title: '确认退出所有设备',
					content: '此操作将立即吊销除当前操作外所有设备的登录会话，确定继续吗？',
					success: async (res) => {
						if (res.confirm) {
							this.sessionRevokeBusy = true
							try {
								await revokeAllUserSessions()
								uni.showToast({ title: '其他会话已全部吊销', icon: 'success' })
								await this.loadSecurityInfo()
							} catch (e) {
								uni.showToast({ title: e.message || '操作失败', icon: 'none' })
							} finally {
								this.sessionRevokeBusy = false
							}
						}
					}
				})
			},
			openRecoveryModal() {
				this.recoveryStep = 1
				this.recoveryAccount = this.authForm.phone || ''
				this.recoveryChannel = this.recoveryCapabilities.sms ? 'sms' : (this.recoveryCapabilities.emailOtp ? 'email_otp' : 'sms')
				this.recoveryCode = ''
				this.recoveryChallengeId = null
				this.recoveryDestinationMasked = ''
				this.recoveryGrant = null
				this.recoveryNewPassword = ''
				this.recoveryConfirmPassword = ''
				this.recoveryCountdown = 0
				if (this.recoveryTimer) {
					clearInterval(this.recoveryTimer)
					this.recoveryTimer = null
				}
				this.showRecoveryModal = true
				this.loadRecoveryCapabilities()
			},
			async loadRecoveryCapabilities() {
				const seq = ++this.recoveryRequestSeq
				try {
					const caps = await getRecoveryCapabilities()
					if (seq !== this.recoveryRequestSeq || !caps) return
					const normalized = {
						sms: Boolean(caps.sms),
						emailOtp: Boolean(caps.emailOtp),
						emailLink: Boolean(caps.emailLink),
						cooldownSeconds: Number(caps.cooldownSeconds) > 0 ? Number(caps.cooldownSeconds) : 60
					}
					this.recoveryCapabilities = normalized
					if (this.recoveryChannel === 'sms' && !normalized.sms && normalized.emailOtp) {
						this.recoveryChannel = 'email_otp'
					} else if (this.recoveryChannel === 'email_otp' && !normalized.emailOtp && normalized.sms) {
						this.recoveryChannel = 'sms'
					}
				} catch {
					// Keep safe fallback capabilities if public capability query fails transiently
				}
			},
			selectRecoveryChannel(ch) {
				if (ch === 'sms' && !this.recoveryCapabilities.sms) {
					uni.showToast({ title: '短信找回通道当前未启用', icon: 'none' })
					return
				}
				if (ch === 'email_otp' && !this.recoveryCapabilities.emailOtp) {
					uni.showToast({ title: '邮箱验证码找回通道当前未启用', icon: 'none' })
					return
				}
				if (this.recoveryChannel !== ch) {
					this.recoveryChannel = ch
					this.recoveryChallengeId = null
					this.recoveryCode = ''
					this.recoveryGrant = null
					this.recoveryDestinationMasked = ''
				}
			},
			onRecoveryAccountInput(e) {
				this.recoveryAccount = String((e && e.detail && e.detail.value) || '')
				this.recoveryChallengeId = null
				this.recoveryCode = ''
				this.recoveryGrant = null
				this.recoveryDestinationMasked = ''
			},
			onRecoveryCodeInput(e) {
				this.recoveryCode = String((e && e.detail && e.detail.value) || '').replace(/\D/g, '').slice(0, 6)
			},
			closeRecoveryModal() {
				this.showRecoveryModal = false
				this.recoveryRequestSeq += 1
				this.recoveryNewPassword = ''
				this.recoveryConfirmPassword = ''
				this.recoveryCode = ''
				this.recoveryGrant = null
				if (this.recoveryTimer) {
					clearInterval(this.recoveryTimer)
					this.recoveryTimer = null
				}
			},
			startRecoveryCountdown(seconds) {
				const secs = Math.max(1, Math.min(3600, Number(seconds) || 60))
				this.recoveryCountdown = secs
				if (this.recoveryTimer) clearInterval(this.recoveryTimer)
				this.recoveryTimer = setInterval(() => {
					if (this.recoveryCountdown <= 1) {
						clearInterval(this.recoveryTimer)
						this.recoveryTimer = null
						this.recoveryCountdown = 0
					} else {
						this.recoveryCountdown -= 1
					}
				}, 1000)
			},
			async sendRecoveryChallenge() {
				if (this.recoveryBusy) return
				const acc = (this.recoveryAccount || '').trim()
				if (!acc) {
					uni.showToast({ title: '请输入账号、手机号或邮箱', icon: 'none' })
					return
				}
				if (this.recoveryChannel === 'sms' && !this.recoveryCapabilities.sms) {
					uni.showToast({ title: '短信找回通道当前未启用', icon: 'none' })
					return
				}
				if (this.recoveryChannel === 'email_otp' && !this.recoveryCapabilities.emailOtp) {
					uni.showToast({ title: '邮箱验证码找回通道当前未启用', icon: 'none' })
					return
				}
				const seq = ++this.recoveryRequestSeq
				this.recoveryBusy = true
				try {
					const res = await startPasswordRecovery(acc, this.recoveryChannel)
					if (seq !== this.recoveryRequestSeq || !this.showRecoveryModal) return
					this.recoveryChallengeId = res.challengeId
					this.recoveryDestinationMasked = res.destinationMasked || ''
					this.recoveryCode = ''
					this.recoveryGrant = null
					uni.showToast({ title: '验证请求已提交；如果账号存在且绑定了可用安全联系方式，验证码将发送', icon: 'none', duration: 2500 })
					this.recoveryStep = 2
					this.startRecoveryCountdown((this.recoveryCapabilities && this.recoveryCapabilities.cooldownSeconds) || 60)
				} catch (e) {
					if (e && e.retryAfter > 0) {
						this.startRecoveryCountdown(e.retryAfter)
					}
					uni.showToast({ title: e.message || '发送失败', icon: 'none' })
				} finally {
					this.recoveryBusy = false
				}
			},
			async verifyRecoveryCode() {
				if (this.recoveryBusy) return
				const code = (this.recoveryCode || '').trim()
				if (!this.recoveryChallengeId) {
					uni.showToast({ title: '请先获取验证码', icon: 'none' })
					return
				}
				if (code.length !== 6) {
					uni.showToast({ title: '请输入6位验证码', icon: 'none' })
					return
				}
				const seq = ++this.recoveryRequestSeq
				this.recoveryBusy = true
				try {
					const res = await verifyPasswordRecovery(this.recoveryChallengeId, code)
					if (seq !== this.recoveryRequestSeq || !this.showRecoveryModal) return
					if (res && res.recoveryGrant) {
						this.recoveryGrant = res.recoveryGrant
						this.recoveryStep = 3
					} else {
						uni.showToast({ title: '验证失败', icon: 'none' })
					}
				} catch (e) {
					uni.showToast({ title: e.message || '验证码错误或已失效', icon: 'none' })
				} finally {
					this.recoveryBusy = false
				}
			},
			async submitRecoveryNewPassword() {
				if (this.recoveryBusy) return
				const next = this.recoveryNewPassword.trim()
				const confirm = this.recoveryConfirmPassword.trim()
				if (next.length < 8 || next.length > 128) {
					uni.showToast({ title: '新密码长度须为8—128位', icon: 'none' })
					return
				}
				if (next !== confirm) {
					uni.showToast({ title: '两次输入的新密码不一致', icon: 'none' })
					return
				}
				this.recoveryBusy = true
				try {
					await completePasswordRecovery(this.recoveryGrant, next)
					uni.showToast({ title: '密码已重置，请登录', icon: 'success' })
					this.closeRecoveryModal()
					this.authMode = 'login'
					this.authForm.password = ''
				} catch (e) {
					uni.showToast({ title: e.message || '重置失败，可能凭证已过期', icon: 'none' })
				} finally {
					this.recoveryBusy = false
				}
			},
			async onSetInitialPassword() {
				if (this.passwordBusy) return
				const password = this.initialPassword.trim()
				if (password.length < 8 || password.length > 128) {
					uni.showToast({ title: '密码长度须为8—128位', icon: 'none' })
					return
				}
				this.passwordBusy = true
				try {
					await setInitialPassword(password)
					this.initialPassword = ''
					await this.refresh()
					uni.showToast({ title: '登录密码已设置', icon: 'success' })
				} catch (error) {
					uni.showToast({ title: error.message || '设置失败', icon: 'none' })
				} finally {
					this.passwordBusy = false
				}
			},
			avatarDisplayUrl(url) {
				if (!url || url === '/static/logo.png') return '/static/logo.png'
				return mediaDisplayUrl({ url }, HostBridge.getEnvironment() || {}, HostBridge.getStorage('tt_access_token') || '')
			},
			async refresh() {
				const requestId = (this._dashboardRequestId || 0) + 1
				this._dashboardRequestId = requestId
				const scope = getPageStateScope()
				this.cachedAccounts = listCachedAccounts()
				this.authPhone = getSessionPhone()
				this.profile = getUserProfile()
				if (isLoggedIn()) {
					this.loadSecurityInfo()
				}

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
				const requestId = this._dashboardRequestId
				const scope = getPageStateScope()
				try {
					// 认证状态由后台审核决定，每次进入页面都以接口为准；
					// 本地快照（tt_org_certification）只用于首屏渲染与接口失败兜底。
					const [certification] = await Promise.all([
						getMyOrganizationCertification(),
						fetchCurrentUser()
					])
					if (this._dashboardRequestId !== requestId || getPageStateScope() !== scope) return false
					this.certification = certification
					this.memberships = certification.memberships
					cacheOrganizationCertification(certification)
					this.profile = getUserProfile()
					return true
				} catch (e) {
					console.error('[mine] loadMemberships failed:', e)
					const cachedCertification = getCachedOrganizationCertification()
					if (cachedCertification && this._dashboardRequestId === requestId && getPageStateScope() === scope) {
						this.certification = cachedCertification.certification
						this.memberships = cachedCertification.certification.memberships || []
					}
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
			if (!phone) {
				uni.showToast({ title: '请输入手机号', icon: 'none' })
				return
			}
			if (!password) {
				uni.showToast({ title: '请输入密码', icon: 'none' })
				return
			}
			if (this.authMode === 'register' && (password.length < 8 || password.length > 128)) {
				uni.showToast({ title: '请设置8–128位密码，首尾空格不计入', icon: 'none', duration: 3000 })
				return
			}
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
					avatarFileId: profile.avatarFileId || null,
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
					this.form.avatarFileId = null
					uni.showToast({ title: '头像已选择，请保存资料', icon: 'none' })
				}
				this.closeAvatarSheet()
			},
			openAvatarSheet() {
				this.showAvatarSheet = true
			},
			closeAvatarSheet() {
				this.showAvatarSheet = false
			},
			async onChooseAlbum() {
				const scope = getPageStateScope()
				this.closeAvatarSheet()
				let picker = { chooseImage: options => uni.chooseImage(options) }
				// #ifdef MP-WEIXIN
				if (typeof wx !== 'undefined') picker = wx
				// #endif
				try {
					const path = await chooseAvatarImage(picker)
					if (scope !== getPageStateScope()) return
					this.form.avatar = path
					this.form.avatarFileId = null
					uni.showToast({ title: '头像已选择，请保存资料', icon: 'none' })
				} catch (error) {
					if (error.cancelled || scope !== getPageStateScope()) return
					uni.showModal({
						title: '无法打开相册',
						content: error.privacyRequired
							? '微信隐私授权未完成。请检查小程序后台的用户隐私保护指引和相册选择声明，并重新编译体验版。'
							: '请检查微信及系统相册权限后重试。错误信息：' + error.message.slice(0, 120),
						showCancel: false,
					})
				}
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
						this.initialPassword = ''
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
.login-card .password-hint, .login-card .password-error { display: block; margin-top: 12rpx; font-size: 24rpx; line-height: 1.6; }
.login-card .password-hint { color: #64748b; }
.login-card .password-error { color: #c53030; }
	.wechat-login, .account-settings {
		margin-top: 24rpx;
		margin-bottom: 24rpx;
	}
	.wechat-btn {
		background: #07c160;
		color: #ffffff;
		font-size: 28rpx;
		margin-bottom: 16rpx;
	}
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
		left: var(--window-left, 0px);
		right: var(--window-right, 0px);
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
  left: 0;
  right: 0;
  top: 0;
  bottom: 0;
  width: 100%;
  height: 100%;
  opacity: 0.92;
  mix-blend-mode: multiply;
  -webkit-mask-image: linear-gradient(to right, transparent 0%, transparent 22%, #000000 68%);
  mask-image: linear-gradient(to right, transparent 0%, transparent 22%, #000000 68%);
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

	.auth-helper-row {
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: center;
		margin-top: 24rpx;
	}
	.forgot-pwd-link {
		font-size: 26rpx;
		color: #64748b;
	}
	.account-security-card {
		margin-top: 24rpx;
		margin-bottom: 24rpx;
	}
	.security-item {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		padding: 24rpx 0;
		border-bottom: 1rpx solid #f1f5f9;
	}
	.security-meta {
		display: flex;
		flex-direction: column;
	}
	.security-title {
		font-size: 28rpx;
		font-weight: 600;
		color: #1e293b;
	}
	.security-sub {
		font-size: 24rpx;
		color: #64748b;
		margin-top: 4rpx;
	}
	.security-btn {
		font-size: 24rpx;
		padding: 8rpx 20rpx;
		background: #f1f5f9;
		color: #2563eb;
		border-radius: 8rpx;
		margin: 0;
	}
	.security-btn.primary {
		background: #2563eb;
		color: #ffffff;
	}
	.security-btn.wechat {
		background: #07c160;
		color: #ffffff;
	}
	.security-tag-bound {
		font-size: 24rpx;
		color: #16a34a;
		font-weight: 600;
	}
	.security-session-box {
		margin-top: 24rpx;
	}
	.revoke-sessions-btn {
		background: #fff1f2;
		color: #e11d48;
		font-size: 26rpx;
		border-radius: 10rpx;
		border: 1rpx solid #fecdd3;
	}
	.dialog-mask {
		position: fixed;
		left: var(--window-left, 0px);
		right: var(--window-right, 0px);
		top: 0;
		bottom: 0;
		background: rgba(0, 0, 0, 0.5);
		z-index: 1000;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 32rpx;
		box-sizing: border-box;
	}
	.dialog-panel {
		width: 100%;
		max-width: 620rpx;
		background: #ffffff;
		border-radius: 20rpx;
		padding: 32rpx;
		box-sizing: border-box;
	}
	.dialog-header {
		display: flex;
		flex-direction: row;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 20rpx;
	}
	.dialog-title {
		font-size: 32rpx;
		font-weight: 600;
		color: #0f172a;
	}
	.dialog-close {
		font-size: 40rpx;
		color: #94a3b8;
		line-height: 1;
		padding: 8rpx;
	}
	.password-feedback-error {
		display: block;
		margin: 16rpx 0;
		padding: 18rpx 20rpx;
		border-radius: 10rpx;
		background: #fff1f0;
		color: #b42318;
		font-size: 26rpx;
		line-height: 1.6;
	}
	.dialog-desc {
		font-size: 24rpx;
		color: #64748b;
		margin-bottom: 20rpx;
		line-height: 1.5;
	}
	.channel-picker {
		display: flex;
		flex-direction: row;
		gap: 16rpx;
	}
	.channel-tab {
		flex: 1;
		text-align: center;
		padding: 14rpx;
		background: #f1f5f9;
		color: #475569;
		border-radius: 8rpx;
		font-size: 26rpx;
	}
	.channel-tab.active {
		background: #eff6ff;
		color: #2563eb;
		font-weight: 600;
		border: 1rpx solid #bfdbfe;
	}
	.channel-tab.disabled {
		opacity: 0.5;
	}
	.security-btn[disabled] {
		opacity: 0.55;
	}
	.primary-action-btn {
		margin-top: 24rpx;
		background: #2563eb;
		color: #ffffff;
		font-size: 28rpx;
		border-radius: 10rpx;
	}
	.code-input-row {
		display: flex;
		flex-direction: row;
		gap: 16rpx;
		align-items: center;
	}
	.code-input {
		flex: 1;
	}
	.send-code-btn {
		white-space: nowrap;
		font-size: 24rpx;
		background: #eff6ff;
		color: #2563eb;
		margin: 0;
	}
	.countdown-row {
		text-align: center;
		margin-top: 20rpx;
	}
	.countdown-text {
		font-size: 24rpx;
		color: #94a3b8;
	}
	.resend-text {
		font-size: 24rpx;
		color: #2563eb;
	}
</style>
