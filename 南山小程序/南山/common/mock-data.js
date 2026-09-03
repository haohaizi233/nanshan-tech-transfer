/**
 * 演示数据（过渡期仅剩成果部分）
 * 需求数据已迁移至后端 API（demand-api.js），需求 Mock 已移除
 * 成果数据已迁移列表/搜索至后端 API，此处仅保留发布成果（本地存储）与详情兜底
 */

const RESULT_STORAGE_KEY = 'ns_user_results'

function readStorageList(key) {
	try {
		const list = uni.getStorageSync(key)
		return Array.isArray(list) ? list : []
	} catch (e) {
		return []
	}
}

function writeStorageList(key, list) {
	uni.setStorageSync(key, list)
}

export function getUserResults() {
	return readStorageList(RESULT_STORAGE_KEY)
}

/** 当前账号发布的成果 */
export function getMyResults(phone) {
	const p = (phone || '').trim()
	if (!p) return []
	return getUserResults().filter((item) => {
		const contact = (item.phone || '').trim()
		const owner = (item.ownerPhone || '').trim()
		return contact === p || owner === p
	})
}

export function getAllResults() {
	return getUserResults()
}

export function addResult(item) {
	const list = getUserResults()
	list.unshift(item)
	writeStorageList(RESULT_STORAGE_KEY, list)
	return item
}

export function createId(prefix) {
	return prefix + '_' + Date.now() + '_' + Math.floor(Math.random() * 1000)
}

export function getResultById(id) {
	return getUserResults().find((item) => item.id === id) || null
}
