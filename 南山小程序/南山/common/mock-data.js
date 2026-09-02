/**
 * 首页与对接详情页共用演示数据
 * 成果数据已迁移至后端 API，resultList Mock 已移除
 */

import { isDemandSuccessfullyMatched } from './user.js'

export const demandList = [
	{
		id: 'd1',
		company: '深圳智造装备有限公司',
		location: '广东 · 深圳南山',
		budget: '80–120 万',
		demandDesc: '寻求高精度视觉检测算法合作，用于产线缺陷识别与实时质检，期望 3 个月内完成样机验证。',
		companyIntro: '专注智能制造装备与工业视觉系统，服务电子、汽车零部件等行业客户。',
		cooperationType: '技术合作 / 联合开发',
		deadline: '期望 3 个月内完成样机',
		industry: '智能制造 · 工业视觉',
		contactName: '王工',
		contactTitle: '技术负责人',
		phone: '13800001111',
		email: 'wangong@sz-smart.cn',
		wechat: 'sz_smart_wang'
	},
	{
		id: 'd2',
		company: '江门绿能新材料科技',
		location: '广东 · 江门',
		budget: '50 万以内',
		demandDesc: '需要可量产的生物基可降解材料配方与中试工艺支持，重点关注成本可控与环保认证。',
		companyIntro: '新材料研发与应用企业，产品覆盖包装、日化等领域。',
		cooperationType: '成果转化 / 工艺授权',
		deadline: '本年度内完成中试',
		industry: '新材料 · 绿色包装',
		contactName: '李经理',
		contactTitle: '研发总监',
		phone: '13900002222',
		email: 'li@jm-green.com',
		wechat: 'jm_green_li'
	},
	{
		id: 'd3',
		company: '南山数科医疗科技',
		location: '广东 · 深圳南山',
		budget: '面议',
		demandDesc: '引进医学影像 AI 辅助诊断相关成果，需具备临床验证基础，并支持私有化部署。',
		companyIntro: '深耕智慧医疗与影像信息化，面向医院与体检机构提供解决方案。',
		cooperationType: '技术引进 / 产品合作',
		deadline: '尽快启动对接评估',
		industry: '智慧医疗 · 医学影像',
		contactName: '陈医生',
		contactTitle: '产品合作负责人',
		phone: '13700003333',
		email: 'chen@ns-medtech.com',
		wechat: 'ns_med_chen'
	}
]

const DEMAND_STORAGE_KEY = 'ns_user_demands'
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

export function getUserDemands() {
	try {
		const flag = 'ns_cleared_user_demands_20260722'
		if (!uni.getStorageSync(flag)) {
			uni.removeStorageSync(DEMAND_STORAGE_KEY)
			uni.setStorageSync(flag, 1)
		}
	} catch (e) {}
	return readStorageList(DEMAND_STORAGE_KEY)
}

export function getUserResults() {
	return readStorageList(RESULT_STORAGE_KEY)
}

/** 当前账号发布的需求（按联系人手机号 / 归属手机号匹配） */
export function getMyDemands(phone) {
	const p = (phone || '').trim()
	if (!p) return []
	return getUserDemands().filter((item) => {
		const contact = (item.phone || '').trim()
		const owner = (item.ownerPhone || '').trim()
		return contact === p || owner === p
	})
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

/** 用户提交 + 演示数据，用户数据在前；已成功对接的需求不出现在公开列表 */
export function getAllDemands() {
	return getUserDemands()
		.concat(demandList)
		.filter((item) => !isDemandSuccessfullyMatched(item.id))
}

export function getAllResults() {
	return getUserResults()
}

export function addDemand(item) {
	const list = getUserDemands()
	list.unshift(item)
	writeStorageList(DEMAND_STORAGE_KEY, list)
	return item
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

function getRawDemands() {
	return getUserDemands().concat(demandList)
}

function getRawResults() {
	return getUserResults()
}

export function getDemandById(id) {
	return getRawDemands().find((item) => item.id === id) || null
}

export function getResultById(id) {
	return getRawResults().find((item) => item.id === id) || null
}
