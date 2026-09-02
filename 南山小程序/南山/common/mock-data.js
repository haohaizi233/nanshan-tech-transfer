/**
 * 首页与对接详情页共用演示数据
 * 后续对接接口时，可替换为 uni.request 结果
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

export const resultList = [
	{
		id: 'r1',
		title: '二维黑磷半导体材料制备技术',
		source: '中国科学院深圳先进技术研究院',
		techIntro: '面向光电与传感应用的二维黑磷制备与稳定化工艺，具备较好的迁移率与可加工性，适合中小试放大。',
		price: '洽谈 / 技术许可',
		purpose: '可用于光电探测器、柔性传感器、高性能晶体管等器件制备，服务半导体与传感产业升级。',
		techPath: '原材料纯化 → 液相剥离/化学气相沉积制备 → 表面钝化与封装稳定化 → 器件级验证与工艺放大。',
		patentHolder: '中国科学院深圳先进技术研究院',
		patentNo: '演示专利号 ZL2023XXXXXXX.1',
		maturity: '实验室验证完成，可进入中试',
		contactName: '赵老师',
		contactTitle: '成果转化联系人',
		phone: '13600004444',
		email: 'zhao@siat.ac.cn',
		wechat: 'siat_zhao'
	},
	{
		id: 'r2',
		title: '工业机器人柔顺力控算法包',
		source: '南方科技大学 · 机器人研究所',
		techIntro: '适用于装配、打磨等接触式作业场景，可降低碰撞风险并提升装配一次成功率，支持主流工业控制器对接。',
		price: '期望 60–90 万',
		purpose: '面向 3C、汽车零部件等精密装配与打磨产线，提升人机协作安全性与装配良率。',
		techPath: '力/力矩传感采集 → 阻抗/导纳控制建模 → 在线柔顺策略优化 → 工业控制器二次开发与现场标定。',
		patentHolder: '南方科技大学',
		patentNo: '演示专利号 ZL2022XXXXXXX.8',
		maturity: '已完成产线试点验证',
		contactName: '周老师',
		contactTitle: '技术成果联系人',
		phone: '13500005555',
		email: 'zhou@sustech.edu.cn',
		wechat: 'sustech_zhou'
	},
	{
		id: 'r3',
		title: '低成本海水淡化膜材料与组件',
		source: '中山大学 · 材料科学与工程学院',
		techIntro: '提升抗污染与使用寿命，降低运维成本，已完成实验室验证，可提供样品与工艺指导。',
		price: '期望 40 万起',
		purpose: '用于沿海工业用水、海岛供水等场景，降低淡化系统膜更换频率与整体运维成本。',
		techPath: '膜基材改性 → 抗污染功能层构建 → 组件封装与通量测试 → 中试线工艺参数固化。',
		patentHolder: '中山大学',
		patentNo: '演示专利号 ZL2021XXXXXXX.3',
		maturity: '实验室验证完成，可提供样品',
		contactName: '吴老师',
		contactTitle: '专利转化联系人',
		phone: '13400006666',
		email: 'wu@mail.sysu.edu.cn',
		wechat: 'sysu_wu'
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
	return getUserResults().concat(resultList)
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
	return getUserResults().concat(resultList)
}

export function getDemandById(id) {
	return getRawDemands().find((item) => item.id === id) || null
}

export function getResultById(id) {
	return getRawResults().find((item) => item.id === id) || null
}
