/**
 * 用户账号 / 登录 / 个人资料（本地多账号演示）
 * - 账号库：手机号 + 密码（可缓存多个账号）
 * - 会话：当前登录手机号
 * - 资料：挂在对应账号下，登录后完善
 */

const ACCOUNTS_KEY = 'ns_user_accounts'
const SESSION_KEY = 'ns_user_session'
const PROFILE_KEY_LEGACY = 'ns_user_profile'

function getStore(key) {
	try {
		return uni.getStorageSync(key)
	} catch (e) {
		console.error('[user] getStore 读取失败:', key, e)
		return ''
	}
}

function setStore(key, val) {
	try {
		uni.setStorageSync(key, val)
		return true
	} catch (e) {
		console.error('[user] setStore 写入失败:', key, e)
		return false
	}
}

function removeStore(key) {
	try {
		uni.removeStorageSync(key)
		return true
	} catch (e) {
		console.error('[user] removeStore 删除失败:', key, e)
		return false
	}
}

function getAccountsMap() {
	const map = getStore(ACCOUNTS_KEY)
	return map && typeof map === 'object' && !Array.isArray(map) ? map : {}
}

function saveAccountsMap(map) {
	return setStore(ACCOUNTS_KEY, map)
}

function migrateLegacyProfile() {
	try {
		const legacy = getStore(PROFILE_KEY_LEGACY)
		if (!legacy || typeof legacy !== 'object' || !legacy.phone) return
		const map = getAccountsMap()
		const phone = String(legacy.phone).trim()
		if (!/^\d{11}$/.test(phone)) return
		if (!map[phone]) {
			map[phone] = {
				phone,
				password: '',
				profile: { ...legacy, phone },
				createdAt: Date.now()
			}
			saveAccountsMap(map)
			if (!getStore(SESSION_KEY)) setStore(SESSION_KEY, phone)
		}
		removeStore(PROFILE_KEY_LEGACY)
	} catch (e) {
		console.error('[user] 迁移旧版资料失败:', e)
	}
}

migrateLegacyProfile()

export function getSessionPhone() {
	const phone = getStore(SESSION_KEY)
	return phone ? String(phone).trim() : ''
}

/** 已缓存的账号列表（不含密码明文展示需求时由页面自行处理） */
export function listCachedAccounts() {
	const map = getAccountsMap()
	return Object.keys(map)
		.map((phone) => {
			const acc = map[phone]
			const profile = acc && acc.profile ? acc.profile : null
			return {
				phone,
				hasPassword: !!(acc && acc.password),
				nickname: profile && profile.nickname ? profile.nickname : '',
				company: profile && profile.company ? profile.company : '',
				profileComplete: isProfileComplete(profile)
			}
		})
		.sort((a, b) => a.phone.localeCompare(b.phone))
}

export function getUserProfile() {
	const phone = getSessionPhone()
	if (!phone) return null
	const map = getAccountsMap()
	const acc = map[phone]
	if (!acc || !acc.profile) return null
	return { ...acc.profile, phone }
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

/** 已登录且资料齐全（可对接） */
export function isLoggedIn() {
	return !!getSessionPhone() && isProfileComplete(getUserProfile())
}

/** 仅完成手机号密码登录（可能尚未填资料） */
export function isAuthenticated() {
	return !!getSessionPhone()
}

/** 已登录但资料未完善 */
export function needsProfile() {
	return isAuthenticated() && !isProfileComplete(getUserProfile())
}

/** 当前身份：demand | supply */
export function getUserIdentity() {
	const profile = getUserProfile()
	return profile && profile.identity === 'supply' ? 'supply' : 'demand'
}

/**
 * 供应方只能对接需求；需求方只能对接成果。
 * 未登录时返回 true（交由登录流程处理）。
 */
export function canDockContentType(type) {
	if (!getSessionPhone() || !getUserProfile()) return true
	const t = type === 'result' ? 'result' : 'demand'
	const identity = getUserIdentity()
	if (identity === 'supply') return t === 'demand'
	return t === 'result'
}

/** 是否可发起对接意向（收藏/意向数据已在后端，本地仅做身份与归属判断） */
export function canProposeDock(type, detail) {
	if (!detail) return false
	if (type === 'demand' && detail.isMine) return false
	return canDockContentType(type)
}

export function getDockBlockMessage(type, detail) {
	if (type === 'demand' && detail && detail.isMine) {
		return '这是您自己发布的需求，无法申请对接'
	}
	if (!canDockContentType(type)) {
		return getUserIdentity() === 'supply'
			? '供应方仅可向需求方发起对接'
			: '需求方仅可向供应方发起对接'
	}
	return ''
}

/**
 * 注册：手机号 + 密码（一次设置）
 * @returns {{ ok: boolean, message?: string }}
 */
export function registerAccount(phone, password) {
	const p = (phone || '').trim()
	const pwd = (password || '').trim()
	if (!/^\d{11}$/.test(p)) return { ok: false, message: '请输入11位手机号' }
	if (pwd.length < 6) return { ok: false, message: '密码至少6位' }
	const map = getAccountsMap()
	if (map[p]) return { ok: false, message: '该手机号已注册，请直接登录' }
	map[p] = {
		phone: p,
		password: pwd,
		profile: {
			avatar: '/static/logo.png',
			nickname: '',
			company: '',
			identity: 'demand',
			phone: p,
			email: '',
			wechat: ''
		},
		createdAt: Date.now()
	}
	if (!saveAccountsMap(map)) {
		return { ok: false, message: '注册失败：存储写入异常，请清理微信缓存后重试' }
	}
	if (!setStore(SESSION_KEY, p)) {
		return { ok: false, message: '注册失败：会话保存异常，请清理微信缓存后重试' }
	}
	return { ok: true }
}

/**
 * 登录
 * @returns {{ ok: boolean, message?: string, needProfile?: boolean }}
 */
export function loginAccount(phone, password) {
	const p = (phone || '').trim()
	const pwd = (password || '').trim()
	if (!/^\d{11}$/.test(p)) return { ok: false, message: '请输入11位手机号' }
	if (!pwd) return { ok: false, message: '请输入密码' }
	const map = getAccountsMap()
	const acc = map[p]
	if (!acc) return { ok: false, message: '账号不存在，请先注册' }
	if (!acc.password) {
		// 兼容迁移账号：首次用输入密码设为正式密码
		if (pwd.length < 6) return { ok: false, message: '请设置至少6位密码' }
		acc.password = pwd
		if (!saveAccountsMap(map)) {
			return { ok: false, message: '登录失败：存储写入异常，请清理微信缓存后重试' }
		}
	} else if (acc.password !== pwd) {
		return { ok: false, message: '密码错误' }
	}
	if (!setStore(SESSION_KEY, p)) {
		return { ok: false, message: '登录失败：会话保存异常，请清理微信缓存后重试' }
	}
	return { ok: true, needProfile: !isProfileComplete(acc.profile) }
}

export function saveUserProfile(profile) {
	const phone = getSessionPhone()
	if (!phone) return null
	const map = getAccountsMap()
	const acc = map[phone]
	if (!acc) return null
	const data = {
		avatar: profile.avatar || '/static/logo.png',
		nickname: (profile.nickname || '').trim(),
		company: (profile.company || '').trim(),
		identity: profile.identity === 'supply' ? 'supply' : 'demand',
		phone,
		email: (profile.email || '').trim(),
		wechat: (profile.wechat || '').trim(),
		updatedAt: Date.now()
	}
	acc.profile = data
	map[phone] = acc
	if (!saveAccountsMap(map)) {
		uni.showToast({ title: '保存失败：存储写入异常', icon: 'none' })
		return null
	}
	return data
}

/** 退出当前会话，账号缓存保留 */
export function logout() {
	return removeStore(SESSION_KEY)
}

export function getIdentityLabel(identity) {
	return identity === 'supply' ? '供给方' : '需求方'
}

/**
 * 存储健康检查：诊断本地存储是否正常工作
 * 在控制台调用 checkStorageHealth() 即可快速排查问题
 */
export function checkStorageHealth() {
	const report = {
		storageAvailable: false,
		canRead: false,
		canWrite: false,
		accountsCount: 0,
		session: null,
		errors: []
	}

	// 1. 测试写入
	try {
		uni.setStorageSync('_health_check', Date.now())
		report.canWrite = true
	} catch (e) {
		report.errors.push('写入失败: ' + (e.message || e))
	}

	// 2. 测试读取
	try {
		const val = uni.getStorageSync('_health_check')
		report.canRead = !!val
		if (!val) report.errors.push('读取返回空值，存储可能已被清空')
	} catch (e) {
		report.errors.push('读取失败: ' + (e.message || e))
	}

	// 3. 清理测试数据
	try {
		uni.removeStorageSync('_health_check')
	} catch (e) {}

	// 4. 检查有效状态
	report.storageAvailable = report.canRead && report.canWrite

	// 5. 检查账号数据
	const map = getAccountsMap()
	report.accountsCount = Object.keys(map).length

	// 6. 检查会话
	report.session = getSessionPhone() || null

	if (!report.storageAvailable && report.errors.length === 0) {
		report.errors.push('存储不可用，可能是微信缓存被清理或版本更新导致')
	}
	if (report.storageAvailable && report.accountsCount === 0) {
		report.errors.push('存储正常但无账号数据，之前注册的账号可能已被清除')
	}

	console.log('[user] 存储健康检查报告:', JSON.stringify(report, null, 2))
	return report
}

export function ensureLoginForDock() {
	if (isLoggedIn()) return true
	uni.showToast({
		title: needsProfile() ? '请先完善个人资料' : '请先登录后再对接',
		icon: 'none'
	})
	setTimeout(() => {
		uni.switchTab({
			url: '/pages/mine/mine'
		})
	}, 400)
	return false
}
