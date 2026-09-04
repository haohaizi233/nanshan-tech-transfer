/**
 * 用户账号 / 登录 / 个人资料（本地多账号演示）
 * - 账号库：手机号 + 密码（可缓存多个账号）
 * - 会话：当前登录手机号
 * - 资料：挂在对应账号下，登录后完善
 *
 * 身份柔性化业务规则（冻结）：
 * 任何用户都可以同时发布需求、发布成果、对接需求、对接成果；
 * 资料中的「主体类型」与「合作方向」仅用于画像和推荐，不作为对接权限限制；
 * 每次对接的合作方式由用户当次选择的合作意向决定（intentType），与账号属性解耦。
 */

const ACCOUNTS_KEY = 'ns_user_accounts'
const SESSION_KEY = 'ns_user_session'
const PROFILE_KEY_LEGACY = 'ns_user_profile'

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

/**
 * 老资料结构升级：identity(demand/supply) → businessCapabilities 画像标签
 * demand → 寻找技术成果；supply → 提供技术成果
 * 仅在读取到旧结构时补默认值，不改写原存储（下次保存时自然落新结构）
 */
function upgradeLegacyProfile(profile) {
	if (!profile || typeof profile !== 'object') return profile
	if (profile.businessCapabilities === undefined) {
		profile.businessCapabilities =
			profile.identity === 'supply' ? ['provide_achievement'] : ['seek_technology']
	}
	if (profile.subjectType === undefined) {
		profile.subjectType = ''
	}
	delete profile.identity
	return profile
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
				profile: upgradeLegacyProfile({ ...legacy, phone }),
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
			const profile = acc && acc.profile ? upgradeLegacyProfile({ ...acc.profile }) : null
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
	const profile = upgradeLegacyProfile({ ...acc.profile })
	return { ...profile, phone }
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
			subjectType: '',
			businessCapabilities: [],
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
	const subjectType = SUBJECT_TYPE_VALUES.indexOf(profile.subjectType) >= 0
		? profile.subjectType
		: ''
	const data = {
		avatar: profile.avatar || '/static/logo.png',
		nickname: (profile.nickname || '').trim(),
		company: (profile.company || '').trim(),
		subjectType,
		businessCapabilities: normalizeCapabilities(profile.businessCapabilities),
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
