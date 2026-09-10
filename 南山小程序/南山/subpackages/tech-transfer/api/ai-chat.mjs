/**
 * AI 匹配对话面板：欢迎语、演示回复、斜杠技能。
 * 需求匹配走 /匹配 技能，接入真实 match-tasks；其余自由问答仍为演示回复。
 */

export const WELCOME =
  '你好，我是南山科转通 AI 助手。本页回答由人工智能生成，仅供参考。\n\n可以直接描述你想找的技术方向，或输入 / 调用技能。当前支持技能：/匹配（按我的需求推荐技术成果）。'

export const SUGGESTIONS = [
  '/匹配',
  '我想找医疗影像相关成果',
  '有没有工业视觉检测方向？',
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
