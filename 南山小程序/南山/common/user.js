/**
 * 用户账号 / 登录 / 个人资料（本地多账号演示）
 * - 账号库：手机号 + 密码（可缓存多个账号）
 * - 会话：当前登录手机号
 * - 资料：挂在对应账号下，登录后完善
 */

const ACCOUNTS_KEY = 'ns_user_accounts'
const SESSION_KEY = 'ns_user_session'
const PROFILE_KEY_LEGACY = 'ns_user_profile'
const FAVORITE_KEY = 'ns_user_favorites'
const INTENTION_KEY = 'ns_user_intentions'

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

/** 是否为自己发布的内容（按登录手机号 / 归属手机号） */
export function isOwnPublishedContent(detail) {
	if (!detail) return false
	const phone = getSessionPhone()
	if (!phone) return false
	const contact = (detail.phone || '').trim()
	const owner = (detail.ownerPhone || '').trim()
	return contact === phone || owner === phone
}

/** 是否可发起对接意向 */
export function canProposeDock(type, detail) {
	if (!detail) return false
	if (type === 'demand' && isDemandSuccessfullyMatched(detail.id)) return false
	return canDockContentType(type) && !isOwnPublishedContent(detail)
}

export function getDockBlockMessage(type, detail) {
	if (type === 'demand' && detail && isDemandSuccessfullyMatched(detail.id)) {
		return '该需求已对接成功，不再接受新的对接'
	}
	if (isOwnPublishedContent(detail)) {
		return '这是您自己发布的内容，无法申请对接'
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

function favoriteStorageKey() {
	const phone = getSessionPhone()
	return phone ? FAVORITE_KEY + '_' + phone : FAVORITE_KEY
}

/** 收藏：按当前账号隔离 */
export function getFavorites() {
	const list = getStore(favoriteStorageKey())
	return Array.isArray(list) ? list : []
}

export function isFavorite(type, id) {
	return getFavorites().some((item) => item.type === type && item.id === id)
}

export function toggleFavorite(type, id) {
	let list = getFavorites()
	const index = list.findIndex((item) => item.type === type && item.id === id)
	if (index >= 0) {
		list.splice(index, 1)
	} else {
		list.unshift({ type, id, createdAt: Date.now() })
	}
	setStore(favoriteStorageKey(), list)
	return index < 0
}

/** 意向请求（全局共享，按手机号区分提出/收到）
 * status: pending 待定 | accepted 同意(接收方已同意) | rejected 拒绝 | success 对接成功(双方都同意)
 */
export function getIntentions() {
	const list = getStore(INTENTION_KEY)
	if (!Array.isArray(list)) return []
	let changed = false
	const next = list.map((item) => {
		const row = { ...item }
		if (!row.intentId) {
			row.intentId =
				'intent_legacy_' +
				(row.createdAt || Date.now()) +
				'_' +
				(row.fromPhone || '') +
				'_' +
				row.type +
				'_' +
				row.id
			changed = true
		}
		if (!row.status) {
			row.status = 'pending'
			changed = true
		}
		return row
	})
	if (changed) setStore(INTENTION_KEY, next)
	return next
}

export function getIntentionById(intentId) {
	if (!intentId) return null
	return getIntentions().find((item) => item.intentId === intentId) || null
}

export function getIntentionStatusLabel(status) {
	const map = {
		pending: '待定',
		accepted: '同意',
		rejected: '拒绝',
		success: '对接成功'
	}
	return map[status] || '待定'
}

export function getSentIntentions(phone) {
	const p = (phone || '').trim()
	if (!p) return []
	return getIntentions().filter((item) => item.fromPhone === p)
}

export function getReceivedIntentions(phone) {
	const p = (phone || '').trim()
	if (!p) return []
	return getIntentions().filter((item) => item.toPhone === p)
}

/** 当前用户对该条目是否有未拒绝的提出意向 */
export function hasIntention(type, id) {
	return !!getMySentIntention(type, id)
}

export function getMySentIntention(type, id) {
	const profile = getUserProfile()
	if (!profile || !profile.phone) return null
	const t = type === 'result' ? 'result' : 'demand'
	return (
		getSentIntentions(profile.phone).find(
			(item) => item.type === t && item.id === id && item.status !== 'rejected'
		) || null
	)
}

function saveIntentionList(list) {
	setStore(INTENTION_KEY, list)
}

function updateIntention(intentId, patch) {
	const list = getIntentions()
	const index = list.findIndex((item) => item.intentId === intentId)
	if (index < 0) return null
	list[index] = { ...list[index], ...patch, updatedAt: Date.now() }
	saveIntentionList(list)
	return list[index]
}

/** 对接成功后的竞争意向处理：
 * - 需求只能对接一次：同目标需求的其它意向一律拒绝
 * - 成果可对接多个需求：同目标成果不自动拒绝
 * - 发起方若携带的是「需求」内容，该需求用过后锁定；成果内容不锁定
 */
function autoRejectCompetitors(winner) {
	const list = getIntentions()
	let changed = false
	list.forEach((item, index) => {
		if (item.intentId === winner.intentId) return
		if (item.status === 'rejected' || item.status === 'success') return

		const sameDemandTarget =
			winner.type === 'demand' && item.type === 'demand' && item.id === winner.id
		const sameDemandFromSide =
			winner.fromSideType === 'demand' &&
			winner.fromSideId &&
			item.fromSideType === 'demand' &&
			item.fromSideId === winner.fromSideId

		if (sameDemandTarget || sameDemandFromSide) {
			list[index] = {
				...item,
				status: 'rejected',
				rejectReason: 'other_matched',
				updatedAt: Date.now()
			}
			changed = true
		}
	})
	if (changed) saveIntentionList(list)
}

/** 需求是否已成功对接（应在需求列表中隐藏） */
export function isDemandSuccessfullyMatched(demandId) {
	if (!demandId) return false
	return getIntentions().some((item) => {
		if (item.status !== 'success') return false
		if (item.type === 'demand' && item.id === demandId) return true
		if (item.fromSideType === 'demand' && item.fromSideId === demandId) return true
		return false
	})
}

export function addIntention(payload) {
	const profile = getUserProfile()
	if (!profile || !profile.phone) return { ok: false, reason: 'not_login' }

	const type = payload.type === 'result' ? 'result' : 'demand'
	const id = payload.id
	const toPhone = (payload.toPhone || '').trim()
	if (!id || !toPhone) return { ok: false, reason: 'invalid' }

	if (!canDockContentType(type)) {
		return {
			ok: false,
			reason: 'identity',
			message: getDockBlockMessage(type, null)
		}
	}
	if (toPhone === profile.phone) {
		return { ok: false, reason: 'self', message: '不能对接自己发布的内容' }
	}

	let list = getIntentions()
	const exists = list.some(
		(item) =>
			item.type === type &&
			item.id === id &&
			item.fromPhone === profile.phone &&
			item.status !== 'rejected'
	)
	if (exists) {
		return { ok: true, duplicated: true }
	}

	const row = {
		intentId: 'intent_' + Date.now() + '_' + Math.floor(Math.random() * 10000),
		type,
		id,
		title: payload.title || '',
		desc: payload.desc || '',
		status: 'pending',
		fromPhone: profile.phone,
		fromNickname: profile.nickname || '',
		fromCompany: profile.company || '',
		fromIdentity: profile.identity || 'demand',
		fromSideType: payload.fromSideType || '',
		fromSideId: payload.fromSideId || '',
		fromSideTitle: payload.fromSideTitle || '',
		fromSideDesc: payload.fromSideDesc || '',
		toPhone,
		toName: payload.toName || '',
		createdAt: Date.now()
	}
	list.unshift(row)
	saveIntentionList(list)
	return { ok: true, duplicated: false, intention: row }
}

/** 发起方取消（仅待定可取消） */
export function removeIntention(type, id) {
	const profile = getUserProfile()
	if (!profile || !profile.phone) return false
	const t = type === 'result' ? 'result' : 'demand'
	const list = getIntentions()
	const index = list.findIndex(
		(item) =>
			item.type === t &&
			item.id === id &&
			item.fromPhone === profile.phone &&
			item.status === 'pending'
	)
	if (index < 0) return false
	list.splice(index, 1)
	saveIntentionList(list)
	return true
}

/**
 * 接收方：同意 / 拒绝（不可撤销）
 * @param {'accept'|'reject'} action
 */
export function receiverRespondIntention(intentId, action) {
	const profile = getUserProfile()
	const row = getIntentionById(intentId)
	if (!profile || !row) return { ok: false, message: '意向不存在' }
	if (row.toPhone !== profile.phone) return { ok: false, message: '无权操作' }
	if (row.status !== 'pending') return { ok: false, message: '该意向已处理，不可修改' }
	if (action === 'reject') {
		return { ok: true, intention: updateIntention(intentId, { status: 'rejected', decidedBy: 'receiver' }) }
	}
	return { ok: true, intention: updateIntention(intentId, { status: 'accepted', decidedBy: 'receiver' }) }
}

/**
 * 发起方最终确认（接收方已同意后）
 * @param {'accept'|'reject'} action
 */
export function initiatorFinalizeIntention(intentId, action) {
	const profile = getUserProfile()
	const row = getIntentionById(intentId)
	if (!profile || !row) return { ok: false, message: '意向不存在' }
	if (row.fromPhone !== profile.phone) return { ok: false, message: '无权操作' }
	if (row.status !== 'accepted') return { ok: false, message: '当前状态不可最终确认' }
	if (action === 'reject') {
		return { ok: true, intention: updateIntention(intentId, { status: 'rejected', decidedBy: 'initiator' }) }
	}
	const next = updateIntention(intentId, { status: 'success', decidedBy: 'initiator' })
	if (next) autoRejectCompetitors(next)
	return { ok: true, intention: next }
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
