/**
 * AI 匹配对话面板：欢迎语、演示回复、斜杠技能。
 * 需求匹配走 /匹配 技能；自由问答由真实 agent 返回介绍、推荐与平台操作指导。
 */

export const WELCOME =
  '你好，我是南山科转通 AI 助手。本页回答由人工智能生成，仅供参考。\n\n我可以查找和介绍成果、结合场景推荐并说明依据，也能介绍平台功能、指导发布、收藏、认证和对接操作。你可以问「介绍机器视觉成果」「推荐用于工业质检的成果」「怎么发布需求」。信息不足时我会追问，不会编造成果或效果。也可输入 / 调用技能：/匹配（按我的已发布需求推荐技术成果）。'

export const SUGGESTIONS = [
  '/匹配',
  '帮我找机器学习用于生态环境遥感监测的科技成果',
  '有哪些企业需要机器视觉的技术需求？',
  '推荐适合工业质检的机器视觉成果',
  '怎么发布成果并申请对接？',
]

export const SKILLS = [
  {
    id: 'match',
    cmd: '/匹配',
    aliases: ['/需求匹配', '/match', '/ai匹配'],
    label: 'AI 需求匹配',
    desc: '选择我的需求，推荐合适的技术成果',
  },
]

export function createWelcomeMessage() {
  return createMessage('assistant', WELCOME, { id: 'welcome' })
}

export function getChatSuggestions() {
  return SUGGESTIONS.slice()
}

export function createMessage(role, content, extra = {}) {
  return {
    id: extra.id || ('m_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)),
    role: role === 'user' ? 'user' : 'assistant',
    type: extra.type || 'text',
    content: String(content || ''),
    time: Date.now(),
    payload: extra.payload || null,
  }
}

export function buildDemoReply(userText) {
  const text = (userText || '').trim()
  if (!text) return '请先输入你想了解的方向或问题。'
  return (
    '已收到：「' +
    (text.length > 40 ? text.slice(0, 40) + '…' : text) +
    '」。\n\n' +
    '自由问答仍在演示中。若要按已发布需求匹配成果，请输入 / 选择「AI 需求匹配」。'
  )
}

/**
 * 将 nanshan-ai-agent 的回包整理为对话消息内容。
 * @param {object} res {success, intent, message, data:[card]}
 * @returns {{content:string, type:string, payload:{cards:Array}}}
 */
export function formatAgentReply(res) {
  if (!res || typeof res !== 'object') {
    return { content: 'AI 助手返回异常，请稍后重试。', type: 'text', payload: { cards: [] } }
  }
  const message = String(res.message || '').trim()
  const cards = Array.isArray(res.data) ? res.data.filter(Boolean) : []
  if (!cards.length) {
    return { content: message || '暂未找到匹配内容。', type: 'text', payload: { cards: [] } }
  }
  return {
    content: message,
    type: 'agent-cards',
    payload: { cards },
  }
}

/**
 * 卡片点击跳转：
 * achievement -> pages/achievement-detail/achievement-detail?id=
 * demand      -> pages/dock-detail/dock-detail?type=demand&id=
 */
export function cardNavigateTarget(card) {
  if (!card || !card.id) return null
  if (card.card_type === 'achievement') {
    return { path: 'pages/achievement-detail/achievement-detail', query: { id: card.id } }
  }
  if (card.card_type === 'demand') {
    return { path: 'pages/dock-detail/dock-detail', query: { type: 'demand', id: card.id } }
  }
  return null
}

export function isSlashDraft(text) {
  return String(text || '').startsWith('/')
}

export function filterSkills(input) {
  const raw = String(input || '')
  if (!raw.startsWith('/')) return []
  const q = raw.slice(1).trim().toLowerCase()
  if (!q) return SKILLS.slice()
  return SKILLS.filter((skill) => {
    const hay = (skill.cmd + ' ' + skill.label + ' ' + (skill.aliases || []).join(' ')).toLowerCase()
    return hay.indexOf(q) >= 0 || skill.cmd.slice(1).toLowerCase().indexOf(q) >= 0
  })
}

export function resolveSkillCommand(text) {
  const t = String(text || '').trim()
  if (!t.startsWith('/')) return null
  const token = t.split(/\s+/)[0]
  return SKILLS.find((skill) => skill.cmd === token || (skill.aliases || []).indexOf(token) >= 0) || null
}

export function formatMatchProgress(status, failReason) {
  if (status === 'queued') return '匹配任务已排队，AI 服务接入后会在这里返回推荐成果。'
  if (status === 'running') return 'AI 正在按该需求匹配技术成果，请稍候…'
  if (status === 'failed') return '匹配失败：' + (failReason || '未知原因，请稍后重试')
  if (status === 'succeeded') return '匹配完成，可点击成果查看详情。'
  return '任务状态：' + (status || '未知')
}
