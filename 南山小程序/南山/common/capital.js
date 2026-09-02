/**
 * 资本对接：子模块配置 + 列表数据
 * - USE_CAPITAL_DEMO=true：读本地写死演示数据（真机演示无需 API）
 * - USE_CAPITAL_DEMO=false：请求 API_BASE
 */

import { API_BASE, USE_CAPITAL_DEMO } from './config.js'
import {
	DEMO_POC_LIST,
	DEMO_PILOT_LIST,
	DEMO_BANK_LIST,
	DEMO_INVEST_LIST
} from './capital-demo-data.js'

/** @typedef {'poc'|'pilot'|'patent'|'bank'|'invest'} CapitalModuleKey */

export const CAPITAL_MODULES = [
	{
		key: 'poc',
		name: '概念验证中心',
		desc: '服务早期技术商业化验证',
		cardHint: '平台名称 / 依托单位 / 平台功能 / 联系方式',
		source: 'platform',
		sourceLabel: '验证与中试资源',
		pending: false,
		iconText: '验'
	},
	{
		key: 'pilot',
		name: '中小试基地',
		desc: '对接工程化 / 产业化中试资源',
		cardHint: '平台名称 / 依托单位 / 平台功能 / 联系方式',
		source: 'platform',
		sourceLabel: '验证与中试资源',
		pending: false,
		iconText: '试'
	},
	{
		key: 'bank',
		name: '银行融资',
		desc: '知识产权融资专业服务机构',
		cardHint: '机构名称 / 简介 / Logo',
		source: 'finance',
		sourceLabel: '投融资对接',
		pending: false,
		iconText: '银'
	},
	{
		key: 'invest',
		name: '投资机构',
		desc: '特色投资机构一览',
		cardHint: '机构名称 / 简介 / Logo',
		source: 'finance',
		sourceLabel: '投融资对接',
		pending: false,
		iconText: '投'
	},
	{
		key: 'patent',
		name: '专利价值评估',
		desc: '转让 / 许可 / 质押 / 作价入股定价参考',
		cardHint: 'AI初评 + 专家评估 / 参考价值区间',
		source: 'eval',
		sourceLabel: '评估服务',
		pending: true,
		iconText: '评'
	}
]

export function getCapitalModule(key) {
	return CAPITAL_MODULES.find((item) => item.key === key) || null
}

export function getCapitalGroups() {
	const map = {}
	CAPITAL_MODULES.forEach((mod) => {
		if (!map[mod.source]) {
			map[mod.source] = {
				source: mod.source,
				label: mod.sourceLabel,
				modules: []
			}
		}
		map[mod.source].modules.push(mod)
	})
	return ['platform', 'finance', 'eval']
		.map((key) => map[key])
		.filter(Boolean)
}

export function listCapitalItems(key) {
	if (key === 'patent') return []
	return []
}

function paginateList(all, keyword, page, pageSize, matchFn) {
	const kw = (keyword && String(keyword).trim()) || ''
	let filtered = all.slice()
	if (kw) {
		const lower = kw.toLowerCase()
		filtered = all.filter((item) => matchFn(item, lower, kw))
	}
	const p = Math.max(1, Number(page) || 1)
	const size = Math.max(1, Math.min(50, Number(pageSize) || 10))
	const total = filtered.length
	const totalPages = total ? Math.ceil(total / size) : 0
	const start = (p - 1) * size
	return {
		list: filtered.slice(start, start + size),
		total,
		page: p,
		pageSize: size,
		totalPages
	}
}

function getDemoPlatformSource(type) {
	if (type === 'poc') return DEMO_POC_LIST
	if (type === 'pilot') return DEMO_PILOT_LIST
	return DEMO_POC_LIST.concat(DEMO_PILOT_LIST)
}

function fetchPlatformListDemo(type, keyword, page, pageSize) {
	const all = getDemoPlatformSource(type)
	return Promise.resolve(
		paginateList(all, keyword, page, pageSize, (item, lower, kw) => {
			const blob = [
				item.name,
				item.unit,
				item.functionText,
				item.contact,
				item.phone,
				item.platformType
			]
				.join(' ')
				.toLowerCase()
			return blob.indexOf(lower) >= 0 || blob.indexOf(kw) >= 0
		})
	)
}

function fetchOrgListDemo(kind, keyword, page, pageSize) {
	const all = kind === 'bank' ? DEMO_BANK_LIST : DEMO_INVEST_LIST
	return Promise.resolve(
		paginateList(all, keyword, page, pageSize, (item, lower, kw) => {
			const blob = [item.name, item.intro, item.label].join(' ').toLowerCase()
			return blob.indexOf(lower) >= 0 || blob.indexOf(kw) >= 0
		})
	)
}

function getRequestApi() {
	if (typeof uni !== 'undefined' && uni.request) return uni
	try {
		// eslint-disable-next-line
		const vendor = typeof require !== 'undefined' ? require('./vendor.js') : null
		if (vendor && vendor.index && vendor.index.request) return vendor.index
	} catch (e) {}
	return null
}

function requestJson(pathWithQuery) {
	const url = API_BASE + pathWithQuery
	const api = getRequestApi()
	return new Promise((resolve, reject) => {
		if (!api || !api.request) {
			reject(new Error('请求能力不可用'))
			return
		}
		api.request({
			url,
			method: 'GET',
			timeout: 15000,
			success(res) {
				const body = res.data || {}
				if (res.statusCode !== 200 || body.code !== 0) {
					reject(new Error((body && body.msg) || '接口返回异常'))
					return
				}
				const data = body.data || {}
				const list = (Array.isArray(data.list) ? data.list : []).map((item) => {
					const logoUrl = item.logoUrl || ''
					return Object.assign({}, item, {
						logoUrl: logoUrl
							? (logoUrl.indexOf('http') === 0 ? logoUrl : API_BASE + logoUrl)
							: ''
					})
				})
				resolve({
					list,
					total: Number(data.total) || 0,
					page: Number(data.page) || 1,
					pageSize: Number(data.pageSize) || 10,
					totalPages: Number(data.totalPages) || 0
				})
			},
			fail(err) {
				reject(new Error((err && err.errMsg) || '网络请求失败，请确认本地 API 已启动'))
			}
		})
	})
}

export function fetchPlatformList(type, keyword, page, pageSize) {
	if (USE_CAPITAL_DEMO) {
		return fetchPlatformListDemo(type, keyword, page, pageSize)
	}
	const q = []
	q.push('type=' + encodeURIComponent(type || 'all'))
	if (keyword && String(keyword).trim()) {
		q.push('keyword=' + encodeURIComponent(String(keyword).trim()))
	}
	q.push('page=' + encodeURIComponent(String(page || 1)))
	q.push('pageSize=' + encodeURIComponent(String(pageSize || 10)))
	return requestJson('/api/platform-base?' + q.join('&'))
}

export function fetchOrgList(kind, keyword, page, pageSize) {
	if (USE_CAPITAL_DEMO) {
		return fetchOrgListDemo(kind, keyword, page, pageSize)
	}
	const path = kind === 'bank' ? '/api/service-orgs' : '/api/invest-orgs'
	const q = []
	if (keyword && String(keyword).trim()) {
		q.push('keyword=' + encodeURIComponent(String(keyword).trim()))
	}
	q.push('page=' + encodeURIComponent(String(page || 1)))
	q.push('pageSize=' + encodeURIComponent(String(pageSize || 10)))
	return requestJson(path + '?' + q.join('&'))
}

export function getPlatformTypeLabel(type) {
	if (!type) return '平台'
	if (type === 'poc' || String(type).indexOf('概念验证') >= 0) return '概念验证中心'
	if (type === 'pilot' || String(type).indexOf('中小试') >= 0 || String(type).indexOf('中试') >= 0) {
		return String(type).indexOf('概念') >= 0 ? '概念验证中心' : (String(type) === 'pilot' ? '中小试基地' : String(type))
	}
	return String(type)
}
