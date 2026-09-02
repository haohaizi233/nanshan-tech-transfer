/**
 * 成果 AI 评估（第一期：四维评分 + 结果展示）
 * 当前为演示假数据；后续替换为真实 AI / 接口即可
 */

import { getAllResults, getResultById } from './mock-data.js'

/** 四维评分维度定义 */
export const AI_SCORE_DIMENSIONS = [
	{ key: 'techFeature', label: '技术特点' },
	{ key: 'applyScope', label: '应用范围' },
	{ key: 'maturity', label: '成熟度' },
	{ key: 'cooperation', label: '合作可行性' }
]

/**
 * 演示评估数据（按成果 id）
 * scores: 0-100
 */
const DEMO_EVAL_MAP = {
	r1: {
		scores: { techFeature: 88, applyScope: 82, maturity: 76, cooperation: 80 },
		conclusion: '材料制备路径清晰，光电/传感应用空间较大，适合以技术许可或联合中试推进转化。',
		highlights: ['二维材料制备与稳定化工艺较完整', '面向器件级验证，转化路径明确', '适合半导体与传感场景落地']
	},
	r2: {
		scores: { techFeature: 91, applyScope: 86, maturity: 88, cooperation: 84 },
		conclusion: '算法包已有产线试点基础，装配/打磨场景匹配度高，合作落地可行性较强。',
		highlights: ['力控算法贴近产线刚需', '已完成试点验证，成熟度较高', '便于与现有工业控制器对接']
	},
	r3: {
		scores: { techFeature: 79, applyScope: 85, maturity: 72, cooperation: 78 },
		conclusion: '抗污染与寿命优势明显，应用场景清晰；建议优先样品验证后推进中试合作。',
		highlights: ['聚焦运维成本痛点', '沿海/海岛供水等场景明确', '可提供样品与工艺指导']
	}
}

function clampScore(n) {
	const v = Math.round(Number(n) || 0)
	if (v < 0) return 0
	if (v > 100) return 100
	return v
}

function calcTotal(scores) {
	const vals = AI_SCORE_DIMENSIONS.map((d) => clampScore(scores[d.key]))
	const sum = vals.reduce((a, b) => a + b, 0)
	return Math.round(sum / vals.length)
}

/**
 * 为未配置假数据的成果生成稳定演示评分（后续可删）
 */
function buildFallbackEval(result) {
	const seed = String(result.id || '').split('').reduce((s, ch) => s + ch.charCodeAt(0), 0)
	const base = 70 + (seed % 18)
	const scores = {
		techFeature: clampScore(base + (seed % 7)),
		applyScope: clampScore(base - 2 + (seed % 5)),
		maturity: clampScore(base - 4 + ((seed * 3) % 9)),
		cooperation: clampScore(base + ((seed * 2) % 6))
	}
	return {
		scores,
		conclusion: '该成果具备一定转化潜力，建议结合具体需求进一步沟通技术边界与合作方式。',
		highlights: ['已完成基础技术梳理', '可对接相关产业需求', '适合作为初步筛选参考']
	}
}

/**
 * 获取成果 AI 评估详情（含四维分、总分、结论、亮点）
 * @returns {null|{ resultId, totalScore, scores, dimensions, conclusion, highlights, source: 'demo'|'fallback' }}
 */
export function getAiEvalByResultId(resultId) {
	const result = getResultById(resultId)
	if (!result) return null

	const raw = DEMO_EVAL_MAP[resultId] || buildFallbackEval(result)
	const scores = {
		techFeature: clampScore(raw.scores.techFeature),
		applyScope: clampScore(raw.scores.applyScope),
		maturity: clampScore(raw.scores.maturity),
		cooperation: clampScore(raw.scores.cooperation)
	}
	const totalScore = calcTotal(scores)
	const dimensions = AI_SCORE_DIMENSIONS.map((d) => ({
		key: d.key,
		label: d.label,
		score: scores[d.key]
	}))

	return {
		resultId,
		title: result.title,
		source: result.source,
		techIntro: result.techIntro,
		maturityText: result.maturity,
		totalScore,
		scores,
		dimensions,
		conclusion: raw.conclusion || '',
		highlights: Array.isArray(raw.highlights) ? raw.highlights : [],
		dataSource: DEMO_EVAL_MAP[resultId] ? 'demo' : 'fallback'
	}
}

/** AI 匹配列表：全部成果 + 评估摘要，按总分降序 */
export function listAiEvalSummaries() {
	return getAllResults()
		.map((item) => {
			const evalData = getAiEvalByResultId(item.id)
			if (!evalData) return null
			return {
				id: item.id,
				title: item.title,
				source: item.source,
				techIntro: item.techIntro,
				totalScore: evalData.totalScore,
				dimensions: evalData.dimensions,
				conclusion: evalData.conclusion
			}
		})
		.filter(Boolean)
		.sort((a, b) => b.totalScore - a.totalScore)
}
