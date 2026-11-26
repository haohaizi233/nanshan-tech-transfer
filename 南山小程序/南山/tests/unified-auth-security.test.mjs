import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import {
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
	createSecurityIdempotencyKey,
	shouldReuseSecurityIdempotencyKey
} from '../subpackages/tech-transfer/api/user.js'

test('changePassword validates new password length', async () => {
	await assert.rejects(
		async () => {
			await changePassword('OldPassword123!', 'short')
		},
		{
			message: '密码长度须为8—128位'
		}
	)
})

test('completePasswordRecovery validates new password length', async () => {
	await assert.rejects(
		async () => {
			await completePasswordRecovery('test-grant', '123')
		},
		{
			message: '新密码长度须为8—128位'
		}
	)
})

test('user.js exports all required security APIs', () => {
	assert.equal(typeof setInitialPassword, 'function')
	assert.equal(typeof changePassword, 'function')
	assert.equal(typeof getSecurityInfo, 'function')
	assert.equal(typeof getRecoveryCapabilities, 'function')
	assert.equal(typeof startSecurityStepUpChallenge, 'function')
	assert.equal(typeof verifySecurityStepUp, 'function')
	assert.equal(typeof sendSecurityContactChallenge, 'function')
	assert.equal(typeof verifySecurityContact, 'function')
	assert.equal(typeof revokeAllUserSessions, 'function')
	assert.equal(typeof startPasswordRecovery, 'function')
	assert.equal(typeof verifyPasswordRecovery, 'function')
	assert.equal(typeof completePasswordRecovery, 'function')
})

test('mine.vue contains forgot password entry and unified account security settings', () => {
	const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
	assert.match(source, /忘记密码？/)
	assert.match(source, /openRecoveryModal/)
	assert.match(source, /账号与安全/)
	assert.match(source, /安全手机/)
	assert.match(source, /安全邮箱/)
	assert.match(source, /退出其他设备登录/)
	assert.match(source, /showContactModal/)
	assert.match(source, /showPasswordModal/)
	assert.match(source, /showRecoveryModal/)
})

test('mine.vue uses email_otp recovery channel, capabilities gate, and stepUpGrant rebinding', () => {
	const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
	assert.match(source, /selectRecoveryChannel\('email_otp'\)/)
	assert.doesNotMatch(source, /recoveryChannel\s*=\s*'email'[^_]/)
	assert.doesNotMatch(source, /recoveryChannel\s*===?\s*'email'[^_]/)
	assert.match(source, /getRecoveryCapabilities/)
	assert.match(source, /startSecurityStepUpChallenge/)
	assert.match(source, /verifySecurityStepUp/)
	assert.match(source, /contactStepUpGrant/)
	assert.match(source, /stepUpMethodLabel/)
})

test('createSecurityIdempotencyKey and transient reuse helpers enforce Phase R idempotency policy', () => {
	const k1 = createSecurityIdempotencyKey('su')
	const k2 = createSecurityIdempotencyKey('su')
	assert.notEqual(k1, k2)
	assert.match(k1, /^su-[A-Za-z0-9_.:-]{12,120}$/)
	assert.equal(shouldReuseSecurityIdempotencyKey(new Error('network timeout')), true)
	assert.equal(shouldReuseSecurityIdempotencyKey({ code: 'TT_COMMON_50301', status: 503 }), true)
	assert.equal(shouldReuseSecurityIdempotencyKey({ code: 'TT_COMMON_40901', status: 409 }), false)
})

test('mine.vue enforces Step-up and target email binding on initial email bind as well as rebind', () => {
	const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
	assert.match(source, /const needStepUp = type === 'email'/)
	assert.match(source, /bind_email/)
	assert.match(source, /rebind_email/)
	assert.match(source, /targetContact:\s*targetEmail/)
	assert.match(source, /createSecurityIdempotencyKey/)
})

test('profile email shortcut prefills the existing verification dialog without saving the form', () => {
	const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
	const start = source.indexOf('openContactModal(type')
	const end = source.indexOf('onTargetEmailInput(e)', start)
	const { openContactModal } = vm.runInNewContext(`({${source.slice(start, end)}})`)
	const state = {
		emailFeatureEnabled: true,
		securityInfo: { stepUpMethods: ['recent_auth'] },
		form: { email: ' name@example.com ', company: '未保存的公司' },
	}

	openContactModal.call(state, 'email', state.form.email)
	assert.equal(state.showContactModal, true)
	assert.equal(state.contactModalStep, 'stepUp')
	assert.equal(state.contactModalValue, 'name@example.com')
	assert.equal(state.contactStepUpMethod, 'recent_auth')
	assert.deepEqual(state.form, { email: ' name@example.com ', company: '未保存的公司' })
})

test('changing accounts clears old security info and ignores its pending response', async () => {
	const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
	const start = source.indexOf('async loadSecurityInfo() {')
	const end = source.indexOf('clearSecurityTimers() {', start)
	let scope = 'account-a'
	const pending = []
	const methods = vm.runInNewContext(`({${source.slice(start, end)}})`, {
		isLoggedIn: () => Boolean(scope),
		getPageStateScope: () => scope,
		getSecurityInfo: () => new Promise(resolve => pending.push(resolve)),
	})
	const original = { email: { verified: true } }
	const state = { ...methods, securityInfo: original, securityInfoScope: scope, securityInfoRequestId: 0 }
	const a = state.loadSecurityInfo()
	scope = 'account-b'
	const b = state.loadSecurityInfo()
	assert.equal(state.securityInfo, null)
	const current = { email: null, stepUpMethods: ['recent_auth'] }
	pending[1](current)
	await b
	pending[0](original)
	await a
	assert.equal(state.securityInfo, current)
	scope = null
	await state.loadSecurityInfo()
	assert.equal(state.securityInfo, null)
})
test('forgot-current-password uses fresh recovery options for the signed-in account', async () => {
	const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
	const start = source.indexOf('openPasswordRecovery() {')
	const end = source.indexOf('selectRecoveryChannel(ch) {', start)
	const methods = vm.runInNewContext(`({${source.slice(start, end)}})`, {
		isLoggedIn: () => true,
		getPageStateScope: () => 'account-a',
		getSecurityInfo: async () => ({
			passwordRecovery: { account: 'verified-owner', sms: false, emailOtp: true },
			email: { value: 'a***@example.test' },
		}),
	})
	const state = {
		...methods, authForm: { phone: 'stale-login-form' }, recoveryRequestSeq: 0,
		showPasswordModal: true, pwdModalCurrent: 'old-input',
		closePasswordModal() { this.showPasswordModal = false },
	}
	await state.openPasswordRecovery()
	assert.equal(state.showPasswordModal, false)
	assert.equal(state.pwdModalCurrent, '')
	assert.equal(state.showRecoveryModal, true)
	assert.equal(state.recoveryAccount, 'verified-owner')
	assert.equal(state.recoveryChannel, 'email_otp')
	assert.equal(state.recoveryCapabilities.sms, false)
	assert.equal(state.recoveryContacts.email_otp, 'a***@example.test')
})

test('rejected recovery code stays in the dialog with an inline error until edited', async () => {
	const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
	const inputStart = source.indexOf('onRecoveryCodeInput(e) {')
	const inputEnd = source.indexOf('closeRecoveryModal() {', inputStart)
	const verifyStart = source.indexOf('async verifyRecoveryCode() {')
	const verifyEnd = source.indexOf('async submitRecoveryNewPassword()', verifyStart)
	const toasts = []
	const state = {
		...vm.runInNewContext(`({${source.slice(inputStart, inputEnd)}${source.slice(verifyStart, verifyEnd)}})`, {
			verifyPasswordRecovery: async () => {
				throw Object.assign(new Error('验证凭据无效'), { code: 'TT_AUTH_RECOVERY_INVALID' })
			},
			uni: { showToast: payload => toasts.push(payload) },
		}),
		recoveryRequestSeq: 0,
		recoveryChallengeId: 'active-challenge',
		recoveryCode: '012345',
		recoveryStep: 2,
		isCurrentRecovery: () => true,
	}

	await state.verifyRecoveryCode()
	assert.equal(state.recoveryStep, 2)
	assert.match(state.recoveryError, /验证码.*重新获取/)
	assert.equal(state.recoveryCode, '012345')
	assert.equal(state.recoveryBusy, false)
	assert.deepEqual(toasts, [])

	state.onRecoveryCodeInput({ detail: { value: '01234' } })
	assert.equal(state.recoveryError, '')
})
