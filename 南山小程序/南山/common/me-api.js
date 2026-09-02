/**
 * 用户/认证 API（主包轻量版）
 *
 * 与 common/achievement-api.js 同模式：直接 uni.request + storage token，
 * 绕过 HostBridge / client.js，避免跨包模块实例问题。
 */

import { API_BASE } from './config.js'
import { getMockTicket } from '../host/mock-identity.js'

const API_PREFIX = '/api/tech-transfer/v1'
const ACCESS_TOKEN_KEY = 'tt_access_token'
const REFRESH_TOKEN_KEY = 'tt_refresh_token'
const USER_KEY = 'tt_current_user'
const TOKEN_EXPIRES_KEY = 'tt_token_expires_at'

function buildURL(path, query) {
	let url = API_BASE + API_PREFIX + path
	if (query && Object.keys(query).length > 0) {
		const qs = Object.entries(query)
			.filter(([, v]) => v !== undefined && v !== null)
			.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
			.join('&')
		if (qs) url += '?' + qs
	}
	return url
}

function getToken() {
	try {
		const expiresAt = uni.getStorageSync(TOKEN_EXPIRES_KEY)
		if (!expiresAt || Date.now() >= expiresAt) return null
		return uni.getStorageSync(ACCESS_TOKEN_KEY) || null
	} catch (e) {
		return null
	}
}

async function ensureToken() {
	let token = getToken()
	if (token) return token
	const res = await new Promise((resolve, reject) => {
		uni.request({
			url: buildURL('/auth/bootstrap', null),
			method: 'POST',
			data: { hostCredential: getMockTicket() },
			header: { 'Content-Type': 'application/json' },
			timeout: 30000,
			success: (res) => resolve(res.data),
			fail: (err) => reject(err),
		})
	})
	if (res.code === 0 && res.data) {
		uni.setStorageSync(ACCESS_TOKEN_KEY, res.data.accessToken)
		uni.setStorageSync(REFRESH_TOKEN_KEY, res.data.refreshToken)
		uni.setStorageSync(USER_KEY, res.data.user)
		uni.setStorageSync(TOKEN_EXPIRES_KEY, Date.now() + (res.data.expiresIn || 7200) * 1000)
		return res.data.accessToken
	}
	throw new Error('Bootstrap failed: ' + (res.message || 'unknown'))
}

async function apiRequest(method, path, body) {
	const token = await ensureToken()
	const res = await new Promise((resolve, reject) => {
		uni.request({
			url: buildURL(path, null),
			method: method.toUpperCase(),
			data: body,
			header: {
				'Content-Type': 'application/json',
				'Authorization': 'Bearer ' + token,
			},
			timeout: 30000,
			success: (res) => resolve(res.data),
			fail: (err) => reject(err),
		})
	})
	if (res.code === 0) return res.data
	throw new Error(res.message || 'Request failed')
}

export function getCachedUser() {
	try {
		return uni.getStorageSync(USER_KEY) || null
	} catch (e) {
		return null
	}
}

export async function getCurrentUser() {
	return apiRequest('GET', '/me')
}

export async function updateMyProfile(updates) {
	return apiRequest('PATCH', '/me/profile', updates)
}

export async function logout() {
	try {
		const refreshToken = uni.getStorageSync(REFRESH_TOKEN_KEY)
		if (refreshToken) {
			await new Promise((resolve) => {
				uni.request({
					url: buildURL('/auth/logout', null),
					method: 'POST',
					data: { refreshToken },
					header: {
						'Content-Type': 'application/json',
						'Authorization': 'Bearer ' + (getToken() || ''),
					},
					timeout: 5000,
					success: () => resolve(),
					fail: () => resolve(),
				})
			})
		}
	} finally {
		uni.removeStorageSync(ACCESS_TOKEN_KEY)
		uni.removeStorageSync(REFRESH_TOKEN_KEY)
		uni.removeStorageSync(USER_KEY)
		uni.removeStorageSync(TOKEN_EXPIRES_KEY)
	}
}
