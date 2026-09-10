/**
 * 用户账号 / 登录 / 个人资料（基于后端真实认证）
 *
 * 认证：调用后端 /auth/login、/auth/register，token 由 client.js 管理
 * 资料：调用后端 /me/profile，本地缓存当前用户信息
 * 历史账号：仅缓存手机号列表用于快速填入，不存密码
 *
 * 身份柔性化业务规则（冻结）：
 * 任何用户都可以同时发布需求、发布成果、对接需求、对接成果；
 * 资料中的「主体类型」与「合作方向」仅用于画像和推荐，不作为对接权限限制；
 * 每次对接的合作方式由用户当次选择的合作意向决定（intentType），与账号属性解耦。
 */

import {
	authLogin,
	authRegister,
	authLogout,
	getCurrentUser,
	setCurrentUser
} from './client.js'
import { apiRequest } from './client.js'
import HostBridge from '../../../host/host-bridge.js'
import { validateEmail, validatePhone } from './contact-validation.mjs'

const HISTORY_PHONES_KEY = 'ns_user_history_phones'

/** 主体类型：相对稳定的属性，与后端 user_profile.subject_type 枚举一致 */
export const SUBJECT_TYPE_OPTIONS = [
	{ label: '企业', value: 'enterprise' },
	{ label: '高校', value: 'university' },
	{ label: '科研院所', value: 'research_institute' },
	{ label: '科研团队', value: 'team' },
	{ label: '技术服务机构', value: 'service_org' },
	{ label: '投资机构', value: 'investment_org' },
	{ label: '个人', value: 'individual' },
	{ label: '其他', value: 'other' }
]

/** 合作方向：可多选的画像标签，与后端 user_profile.business_capabilities 枚举一致，仅用于推荐 */
export const CAPABILITY_OPTIONS = [
	{ label: '寻找技术成果', value: 'seek_technology' },
	{ label: '发布技术需求', value: 'publish_demand' },
	{ label: '提供技术成果', value: 'provide_achievement' },
	{ label: '联合研发', value: 'joint_rnd' },
	{ label: '提供技术服务', value: 'provide_service' },
	{ label: '投融资合作', value: 'investment' }
]

const SUBJECT_TYPE_VALUES = SUBJECT_TYPE_OPTIONS.map((o) => o.value)
const CAPABILITY_VALUES = CAPABILITY_OPTIONS.map((o) => o.value)

export function getSubjectTypeLabel(value) {
	const found = SUBJECT_TYPE_OPTIONS.find((o) => o.value === value)
	return found ? found.label : ''
}

export function getCapabilityLabels(caps) {
	if (!Array.isArray(caps)) return []
	return caps
		.filter((v) => CAPABILITY_VALUES.indexOf(v) >= 0)
		.map((v) => {
			const found = CAPABILITY_OPTIONS.find((o) => o.value === v)
			return found ? found.label : ''
		})
		.filter(Boolean)
}

/** 清洗合作方向多选值：去非法项、去重 */
export function normalizeCapabilities(caps) {
	if (!Array.isArray(caps)) return []
	const out = []
	caps.forEach((v) => {
		if (CAPABILITY_VALUES.indexOf(v) >= 0 && out.indexOf(v) < 0) out.push(v)
	})
	return out
}

function getHistoryPhones() {
	try {
		const list = uni.getStorageSync(HISTORY_PHONES_KEY)
		return Array.isArray(list) ? list : []
	} catch (e) {
		return []
	}
}

function pushHistoryPhone(phone) {
	if (!phone) return
	try {
		const list = getHistoryPhones().filter((p) => p !== phone)
		list.unshift(phone)
		uni.setStorageSync(HISTORY_PHONES_KEY, list.slice(0, 10))
	} catch (e) {
		console.error('[user] 历史账号缓存失败:', e)
	}
}

/** 当前登录手机号（来自后端用户信息缓存） */
export function getSessionPhone() {
	const user = getCurrentUser()
	return user && user.phone ? String(user.phone).trim() : ''
}

function getActiveMemberships(user) {
	const list = (user && user.organizationMemberships) || []
	return Array.isArray(list) ? list.filter((item) => item && item.status === 'active') : []
}

function resolveCompanyName(user) {
	const memberships = getActiveMemberships(user)
	if (memberships.length && memberships[0].orgName) return memberships[0].orgName
	return String((user && (user.companyText || user.orgTitle)) || '').trim()
}

/** 历史登录过的手机号列表（仅用于登录页快速填入） */
export function listCachedAccounts() {
	const currentPhone = getSessionPhone()
	const currentUser = getCurrentUser()
	return getHistoryPhones()
		.map((phone) => ({
			phone,
			hasPassword: true,
			nickname: phone === currentPhone ? (currentUser && currentUser.displayName) || '' : '',
			company: phone === currentPhone ? resolveCompanyName(currentUser) : '',
			profileComplete: phone === currentPhone ? isProfileComplete(getUserProfile()) : false
		}))
		.sort((a, b) => a.phone.localeCompare(b.phone))
}

/** 当前用户资料（后端字段 → 前端友好命名） */
export function getUserProfile() {
	const user = getCurrentUser()
	if (!user) return null
	return {
		avatar: user.avatar || '/static/logo.png',
		nickname: user.displayName || '',
		company: resolveCompanyName(user),
		subjectType: user.subjectType || '',
		businessCapabilities: user.businessCapabilities || [],
		phone: user.phone || '',
		email: user.email || '',
		wechat: user.wechat || '',
		version: user.version || 1,
		userId: user.userId,
		userNo: user.userNo
	}
}

function isProfileComplete(profile) {
	return !!(
		profile &&
		profile.nickname &&
		profile.phone &&
		profile.email &&
		profile.wechat &&
		profile.company
	)
}

/** 已登录（后端用户信息缓存有效） */
export function isLoggedIn() {
	const user = getCurrentUser()
	return !!(user && user.userId)
}

/** 已登录（同 isLoggedIn，保持旧 API 兼容） */
export function isAuthenticated() {
	return isLoggedIn()
}

/** 已登录但资料未完善 */
export function needsProfile() {
	return isLoggedIn() && !isProfileComplete(getUserProfile())
}

/**
 * 是否可发起对接意向。
 * 只检查真正的业务约束：自己发布的内容不可对接；
 * 其余约束（登录/资料、目标是否发布、是否已有活跃意向）由登录流程与后端强校验，
 * 与账号主体类型/合作方向画像无关。
 */
export function canProposeDock(type, detail) {
	return !!detail && !detail.isMine
}

export function getDockBlockMessage(type, detail) {
	if (detail && detail.isMine) {
		return '这是您自己发布的内容，无法申请对接'
	}
	return ''
}

/**
 * 注册（后端 /auth/register：创建用户 + 直接签发会话）
 * @returns {Promise<{ ok: boolean, message?: string }>}
 */
export async function registerAccount(phone, password) {
	const p = (phone || '').trim()
	const pwd = (password || '').trim()
	const phoneCheck = validatePhone(p, { required: true })
	if (!phoneCheck.ok) return { ok: false, message: phoneCheck.message }
	if (pwd.length < 6) return { ok: false, message: '密码至少6位' }
	try {
		await authRegister(p, pwd)
		pushHistoryPhone(p)
		return { ok: true }
	} catch (e) {
		return { ok: false, message: e.message || '注册失败' }
	}
}

/**
 * 登录（后端 /auth/login 按 user_credential.phone 校验手机号+密码）
 * @returns {Promise<{ ok: boolean, message?: string, needProfile?: boolean }>}
 */
export async function loginAccount(phone, password) {
	const p = (phone || '').trim()
	const pwd = (password || '').trim()
	const phoneCheck = validatePhone(p, { required: true })
	if (!phoneCheck.ok) return { ok: false, message: phoneCheck.message }
	if (!pwd) return { ok: false, message: '请输入密码' }
	try {
		await authLogin(p, pwd)
		pushHistoryPhone(p)
		return { ok: true, needProfile: !isProfileComplete(getUserProfile()) }
	} catch (e) {
		return { ok: false, message: e.message || '登录失败' }
	}
}

/**
 * 保存/更新个人资料（后端 PATCH /me/profile，乐观锁 version）
 * @returns {Promise<object|null>} 更新后的前端资料模型
 */
export async function saveUserProfile(profile) {
	if (!isLoggedIn()) return null

	const subjectType = SUBJECT_TYPE_VALUES.indexOf(profile.subjectType) >= 0
		? profile.subjectType
		: ''
	const current = getCurrentUser() || {}
	const emailCheck = validateEmail(profile.email, { required: false })
	if (!emailCheck.ok) {
		uni.showToast({ title: emailCheck.message, icon: 'none' })
		return null
	}
	const phoneCheck = validatePhone(profile.phone, { required: false })
	if (!phoneCheck.ok) {
		uni.showToast({ title: phoneCheck.message, icon: 'none' })
		return null
	}
	const body = {
		version: current.version || 1,
		displayName: (profile.nickname || '').trim() || undefined,
		subjectType: subjectType || undefined,
		businessCapabilities: normalizeCapabilities(profile.businessCapabilities),
		phone: phoneCheck.value || undefined,
		email: emailCheck.value || undefined,
		wechat: (profile.wechat || '').trim() || undefined,
	}
	if (!getActiveMemberships(current).length) {
		const company = (profile.company || '').trim()
		if (company) {
			body.companyText = company
			body.orgTitle = company
		}
	}

	try {
		const updated = await apiRequest('PATCH', '/me/profile', null, body)
		setCurrentUser(updated)
		return getUserProfile()
	} catch (e) {
		uni.showToast({ title: e.message || '保存失败', icon: 'none' })
		return null
	}
}

/** 退出登录（吊销后端会话 + 清除本地缓存） */
export async function logout() {
	try {
		await authLogout()
	} catch (e) {
		console.error('[user] logout 失败:', e)
	}
}

export function ensureLoginForDock() {
	if (isLoggedIn()) return true
	uni.showToast({
		title: needsProfile() ? '请先完善个人资料' : '请先登录后再对接',
		icon: 'none'
	})
	setTimeout(() => {
		HostBridge.navigate('pages/mine/mine')
	}, 400)
	return false
}
