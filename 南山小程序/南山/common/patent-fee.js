/**
 * 专利年费监控：费率表、演示数据、检索与计算
 * 后续专利类型、缴费年度等可由接口替换
 */

/** @typedef {'invention'|'utility'|'design'} PatentType */

const FEE_TABLE = {
	invention: [
		{ min: 1, max: 3, standard: 900, reduce70: 270, reduce85: 135 },
		{ min: 4, max: 6, standard: 1200, reduce70: 360, reduce85: 180 },
		{ min: 7, max: 9, standard: 2000, reduce70: 600, reduce85: 300 },
		{ min: 10, max: 12, standard: 4000, reduce70: 1200, reduce85: 600 },
		{ min: 13, max: 15, standard: 6000, reduce70: 1800, reduce85: 900 },
		{ min: 16, max: 20, standard: 8000, reduce70: 2400, reduce85: 1200 }
	],
	utility: [
		{ min: 1, max: 3, standard: 600, reduce70: 180, reduce85: 90 },
		{ min: 4, max: 5, standard: 900, reduce70: 270, reduce85: 135 },
		{ min: 6, max: 8, standard: 1200, reduce70: 360, reduce85: 180 },
		{ min: 9, max: 10, standard: 2000, reduce70: 600, reduce85: 300 }
	],
	design: [
		{ min: 1, max: 3, standard: 600, reduce70: 180, reduce85: 90 },
		{ min: 4, max: 5, standard: 900, reduce70: 270, reduce85: 135 },
		{ min: 6, max: 8, standard: 1200, reduce70: 360, reduce85: 180 },
		{ min: 9, max: 10, standard: 2000, reduce70: 600, reduce85: 300 },
		{ min: 11, max: 15, standard: 3000, reduce70: 900, reduce85: 450 }
	]
}

const TYPE_LABEL = {
	invention: '发明专利',
	utility: '实用新型专利',
	design: '外观设计专利'
}

/** 演示专利数据（后续由数据库替换） */
export const patentDemoList = [
	{
		id: 'p1',
		name: '一种高精度工业视觉缺陷检测系统',
		patentNo: 'ZL202110123456.7',
		type: 'invention',
		applyDate: '2021-03-15',
		feeYear: 5,
		unitName: '深圳智造装备有限公司',
		holder: '深圳智造装备有限公司'
	},
	{
		id: 'p2',
		name: '生物基可降解包装材料及其制备方法',
		patentNo: 'ZL202210987654.3',
		type: 'invention',
		applyDate: '2022-06-20',
		feeYear: 4,
		unitName: '江门绿能新材料科技',
		holder: '江门绿能新材料科技'
	},
	{
		id: 'p3',
		name: '协作机器人柔性力控夹具',
		patentNo: 'ZL202320111222.X',
		type: 'utility',
		applyDate: '2023-01-08',
		feeYear: 3,
		unitName: '南山先进制造研究院',
		holder: '南山先进制造研究院'
	},
	{
		id: 'p4',
		name: '便携式医学影像辅助诊断终端外观',
		patentNo: 'ZL202330555666.8',
		type: 'design',
		applyDate: '2023-09-01',
		feeYear: 2,
		unitName: '南山数科医疗科技',
		holder: '南山数科医疗科技'
	},
	{
		id: 'p5',
		name: '多模态医学影像融合分析方法',
		patentNo: 'ZL201910888999.1',
		type: 'invention',
		applyDate: '2019-11-12',
		feeYear: 7,
		unitName: '南方科技大学附属医院',
		holder: '南方科技大学附属医院'
	},
	{
		id: 'p6',
		name: '智能仓储分拣装置',
		patentNo: 'ZL202121333444.5',
		type: 'utility',
		applyDate: '2021-08-18',
		feeYear: 5,
		unitName: '深圳物流装备研究所',
		holder: '深圳物流装备研究所'
	}
]

export function getPatentTypeLabel(type) {
	return TYPE_LABEL[type] || '专利'
}

export function getPatentById(id) {
	return patentDemoList.find((item) => item.id === id) || null
}

/**
 * 按专利名称、专利号或单位名称检索
 * 无关键词时返回全部（列表不展示技术名称，仅单位/专利号等）
 * @param {string} keyword
 */
export function searchPatents(keyword) {
	const kw = (keyword || '').trim().toLowerCase()
	if (!kw) return patentDemoList.slice()
	return patentDemoList.filter((item) => {
		const name = (item.name || '').toLowerCase()
		const no = (item.patentNo || '').toLowerCase().replace(/\s/g, '')
		const unit = (item.unitName || item.holder || '').toLowerCase()
		const kw2 = kw.replace(/\s/g, '')
		return name.indexOf(kw) >= 0 || no.indexOf(kw2) >= 0 || unit.indexOf(kw) >= 0
	})
}

/**
 * 解析 YYYY-MM-DD
 * @param {string} dateStr
 */
function parseDateParts(dateStr) {
	const parts = String(dateStr || '').split('-').map((n) => parseInt(n, 10))
	if (parts.length < 3 || parts.some((n) => !n && n !== 0)) return null
	return { y: parts[0], m: parts[1], d: parts[2] }
}

function pad2(n) {
	return n < 10 ? '0' + n : String(n)
}

/**
 * 申请日 + N 年 的前一天 = 最晚缴费时间
 * 例：申请日 2021-03-15，第 1 年 → 2022-03-14
 * @param {string} applyDate
 * @param {number} feeYear 当前缴费年度（第几年）
 */
export function calcLatestPayDate(applyDate, feeYear) {
	const parts = parseDateParts(applyDate)
	const year = Math.max(1, parseInt(feeYear, 10) || 1)
	if (!parts) return '—'
	let y = parts.y + year
	let m = parts.m
	let d = parts.d - 1
	if (d < 1) {
		m -= 1
		if (m < 1) {
			m = 12
			y -= 1
		}
		const daysInMonth = new Date(y, m, 0).getDate()
		d = daysInMonth
	}
	return y + '-' + pad2(m) + '-' + pad2(d)
}

/**
 * 根据专利类型与缴费年度取应缴年费三档
 * @param {PatentType} type
 * @param {number} feeYear
 */
export function getAnnualFees(type, feeYear) {
	const table = FEE_TABLE[type] || FEE_TABLE.invention
	const year = Math.max(1, parseInt(feeYear, 10) || 1)
	const row = table.find((item) => year >= item.min && year <= item.max)
	if (!row) {
		return {
			ok: false,
			message: '当前年度超出该专利类型年费表范围',
			standard: null,
			reduce70: null,
			reduce85: null,
			yearRange: ''
		}
	}
	return {
		ok: true,
		message: '',
		standard: row.standard,
		reduce70: row.reduce70,
		reduce85: row.reduce85,
		yearRange: '第 ' + row.min + (row.min === row.max ? '' : '-' + row.max) + ' 年'
	}
}

/** 组装详情展示数据 */
export function buildPatentFeeDetail(patent) {
	if (!patent) return null
	const fees = getAnnualFees(patent.type, patent.feeYear)
	return {
		...patent,
		typeLabel: getPatentTypeLabel(patent.type),
		latestPayDate: calcLatestPayDate(patent.applyDate, patent.feeYear),
		fees
	}
}
