import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
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
