/**
 * AI 匹配对话（前端演示）
 * 大模型未接入：本地生成引导回复；后续替换 replyWithAi 即可
 */

const WELCOME =
	'你好，我是南山科转通 AI 匹配助手。你可以描述需求方向、行业场景或关注的单位，我来帮你匹配合适的成果与对接建议。\n\n（当前为界面演示，大模型接入后将支持真实智能问答）'

const SUGGESTIONS = [
	'我想找医疗影像相关成果',
	'有没有工业视觉检测方向？',
	'帮我匹配可落地的包装材料技术'
]

/**
 * @returns {{ id: string, role: 'assistant'|'user', content: string, time: number }}
 */
export function createWelcomeMessage() {
	return {
		id: 'welcome',
		role: 'assistant',
		content: WELCOME,
		time: Date.now()
	}
}

export function getChatSuggestions() {
	return SUGGESTIONS.slice()
}

/**
 * 本地演示回复（不调用大模型）
 * @param {string} userText
 */
export function buildDemoReply(userText) {
	const text = (userText || '').trim()
	if (!text) {
		return '请先输入你想了解的方向或问题。'
	}
	return (
		'已收到你的问题：「' +
		(text.length > 40 ? text.slice(0, 40) + '…' : text) +
		'」。\n\n' +
		'当前尚未接入大模型，暂不能返回真实匹配结果。接入后将在此给出推荐成果与对接建议，且不会在对话前主动罗列技术清单。'
	)
}

export function createMessage(role, content) {
	return {
		id: 'm_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8),
		role: role === 'user' ? 'user' : 'assistant',
		content: String(content || ''),
		time: Date.now()
	}
}
