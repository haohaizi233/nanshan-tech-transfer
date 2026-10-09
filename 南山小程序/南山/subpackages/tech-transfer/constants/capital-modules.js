/**
 * 资本对接子模块纯配置（展示层常量，无请求逻辑）
 * 列表数据经 api/capital.js 走统一机构接口 /institutions。
 */

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
	return ['platform', 'finance']
		.map((key) => map[key])
		.filter(Boolean)
}
