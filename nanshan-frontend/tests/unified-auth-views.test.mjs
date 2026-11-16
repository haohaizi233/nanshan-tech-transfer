import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('LoginView.vue contains forgot-password navigation and wechat login mode toggle', () => {
	const source = readFileSync(new URL('../src/views/auth/LoginView.vue', import.meta.url), 'utf8')
	assert.match(source, /\/forgot-password/)
	assert.match(source, /忘记密码？/)
	assert.match(source, /activeTab === 'wechat'/)
	assert.match(source, /activeTab === 'password'/)
	assert.match(source, /\/auth\/wechat\/web\/config/)
	assert.match(source, /\/auth\/wechat\/web\/callback/)
})

test('ForgotPasswordView.vue implements 4-step wizard', () => {
	const source = readFileSync(new URL('../src/views/auth/ForgotPasswordView.vue', import.meta.url), 'utf8')
	assert.match(source, /step === 1/)
	assert.match(source, /step === 2/)
	assert.match(source, /step === 3/)
	assert.match(source, /step === 4/)
	assert.match(source, /\/auth\/recovery\/start/)
	assert.match(source, /\/auth\/recovery\/verify/)
	assert.match(source, /\/auth\/recovery\/complete/)
})

test('ResetPasswordView.vue safely handles reset link tokens', () => {
	const source = readFileSync(new URL('../src/views/auth/ResetPasswordView.vue', import.meta.url), 'utf8')
	assert.match(source, /replaceState/)
	assert.match(source, /\/auth\/recovery\/verify/)
	assert.match(source, /\/auth\/recovery\/complete/)
})

test('AccountSecurityView.vue provides unified security center', () => {
	const source = readFileSync(new URL('../src/views/admin/AccountSecurityView.vue', import.meta.url), 'utf8')
	assert.match(source, /\/me\/security/)
	assert.match(source, /\/me\/security\/contact\/challenge/)
	assert.match(source, /\/me\/security\/contact\/verify/)
	assert.match(source, /\/me\/security\/revoke-sessions/)
})
