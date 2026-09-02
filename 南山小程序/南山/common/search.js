/**
 * 搜索匹配与历史记录
 * 需求仅匹配：公司名称、需求说明
 * 成果仅匹配：成果标题、技术简介、来源
 * 需求/成果历史分开保存，各最多 10 条
 */

const DEMAND_HISTORY_KEY = 'ns_search_history_demand'
const RESULT_HISTORY_KEY = 'ns_search_history_result'
const HISTORY_MAX = 10

const DEMAND_SEARCH_FIELDS = ['company', 'demandDesc']
const RESULT_SEARCH_FIELDS = ['title', 'techIntro', 'source']

function readHistory(key) {
	try {
		const list = uni.getStorageSync(key)
		return Array.isArray(list) ? list : []
	} catch (e) {
		return []
	}
}

function writeHistory(key, list) {
	uni.setStorageSync(key, list)
}

export function getDemandSearchHistory() {
	return readHistory(DEMAND_HISTORY_KEY)
}

export function getResultSearchHistory() {
	return readHistory(RESULT_HISTORY_KEY)
}

export function addDemandSearchHistory(keyword) {
	return addHistory(DEMAND_HISTORY_KEY, keyword)
}

export function addResultSearchHistory(keyword) {
	return addHistory(RESULT_HISTORY_KEY, keyword)
}

function addHistory(key, keyword) {
	const kw = (keyword || '').trim()
	if (!kw) return readHistory(key)
	let list = readHistory(key).filter((item) => item !== kw)
	list.unshift(kw)
	if (list.length > HISTORY_MAX) {
		list = list.slice(0, HISTORY_MAX)
	}
	writeHistory(key, list)
	return list
}

export function clearDemandSearchHistory() {
	uni.removeStorageSync(DEMAND_HISTORY_KEY)
	return []
}

export function clearResultSearchHistory() {
	uni.removeStorageSync(RESULT_HISTORY_KEY)
	return []
}

export function matchByKeyword(item, keyword, fields) {
	const kw = keyword.toLowerCase()
	for (let i = 0; i < fields.length; i++) {
		const value = item[fields[i]]
		if (value && String(value).toLowerCase().indexOf(kw) !== -1) {
			return true
		}
	}
	return false
}

export function filterDemands(list, keyword) {
	const kw = (keyword || '').trim()
	if (!kw) return list.slice()
	return list.filter((item) => matchByKeyword(item, kw, DEMAND_SEARCH_FIELDS))
}

export function filterResults(list, keyword) {
	const kw = (keyword || '').trim()
	if (!kw) return list.slice()
	return list.filter((item) => matchByKeyword(item, kw, RESULT_SEARCH_FIELDS))
}
