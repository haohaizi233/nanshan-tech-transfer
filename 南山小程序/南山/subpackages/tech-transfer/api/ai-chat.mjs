/**
 * AI 匹配对话面板：欢迎语、演示回复、斜杠技能。
 * 需求匹配走 /匹配 技能；自由问答由真实 agent 返回介绍、推荐与平台操作指导。
 */

export const WELCOME =
  '你好，我是南山科转通 AI 助手。本页回答由人工智能生成，仅供参考。\n\n我可以查找和介绍成果、结合场景推荐并说明依据，也能介绍平台功能、指导发布、收藏、认证和对接操作。你可以问「介绍机器视觉成果」「推荐用于工业质检的成果」「怎么发布需求」。信息不足时我会追问，不会编造成果或效果。也可输入 / 调用命令：/评估（AI 评估成果）、/搜索（找成果或需求）、/匹配（按我的已发布需求推荐技术成果）、/帮助（查看全部命令）。'

export const SUGGESTIONS = [
  '/匹配',
  '帮我找机器学习用于生态环境遥感监测的科技成果',
  '有哪些企业需要机器视觉的技术需求？',
  '推荐适合工业质检的机器视觉成果',
  '怎么发布成果并申请对接？',
]

export const SKILLS = [
  {
    id: 'evaluate',
    cmd: '/评估',
    aliases: ['/评估成果', '/evaluate', '/ai评估'],
    icon: '📊',
    label: 'AI 成果评估',
    desc: '对指定成果发起 AI 多维度评估',
    usage: '/评估 [成果ID/名称]',
    takesArgs: true,
  },
  {
    id: 'search',
    cmd: '/搜索',
    aliases: ['/查找', '/search'],
    icon: '🔍',
    label: '搜索成果/需求',
    desc: '按关键词搜索科技成果或技术需求',
    usage: '/搜索 [关键词]',
    takesArgs: true,
  },
  {
    id: 'help',
    cmd: '/帮助',
    aliases: ['/help', '/指令'],
    icon: '💡',
    label: '命令帮助',
    desc: '查看全部可用命令与用法',
    usage: '/帮助',
    takesArgs: false,
  },
  {
    id: 'match',
    cmd: '/匹配',
    aliases: ['/需求匹配', '/match', '/ai匹配'],
    icon: '🎯',
    label: 'AI 需求匹配',
    desc: '选择我的需求，推荐合适的技术成果',
    usage: '/匹配',
    takesArgs: false,
  },
]

export function createWelcomeMessage() {
  return createMessage('assistant', WELCOME, { id: 'welcome' })
}

export function getChatSuggestions() {
  return SUGGESTIONS.slice()
}

export function createMessage(role, content, extra = {}) {
  const text = String(content || '')
  const isUser = role === 'user'
  // 斜杠命令消息带视觉区分标记：气泡用 ⚡ 命令样式渲染（见 ai-match.vue）。
  const slashCommand = isUser && text.trim().startsWith('/')
  return {
    id: extra.id || ('m_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)),
    role: isUser ? 'user' : 'assistant',
    type: extra.type || 'text',
    content: text,
    time: Date.now(),
    payload: extra.payload || null,
    serverMessageId: extra.serverMessageId || null,
    serverTurnId: extra.serverTurnId || null,
    serverGeneration: Number.isSafeInteger(extra.serverGeneration) ? extra.serverGeneration : null,
    isCommand: isUser && (extra.isCommand === true || slashCommand),
    commandText: isUser ? (extra.commandText || (slashCommand ? text.trim() : null)) : null,
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

/**
 * 将斜杠命令草稿改写为 agent 意图路由可识别的自然语言。
 * 例：/评估 3 → 评估成果3（target_id）；/评估 仿生灵巧手 → 评估一下仿生灵巧手（target_name）。
 */
export function buildSkillMessage(skill, text) {
  const t = String(text || '').trim()
  if (!skill) return t
  const token = t.split(/\s+/)[0]
  const args = t.slice(token.length).trim()
  if (skill.id === 'evaluate') {
    if (!args) return '评估成果'
    return /^\d+$/.test(args) ? '评估成果' + args : '评估一下' + args
  }
  if (skill.id === 'search') {
    return args ? '帮我找' + args + '相关的科技成果或技术需求' : '帮我找相关的科技成果或技术需求'
  }
  return t
}

/** /帮助 命令的本地回复：列出全部可用命令与用法。 */
export function buildHelpText() {
  return {
    type: 'help-commands',
    content: '📋 可用命令',
    commands: SKILLS.map(s => ({
      id: s.id,
      icon: s.icon || '⚡',
      cmd: s.cmd,
      label: s.label || s.cmd,
      usage: s.usage || s.cmd,
      desc: s.desc || '',
      sample: s.id === 'evaluate' ? '/评估 成果3' : s.id === 'search' ? '/搜索 人工智能' : s.cmd
    }))
  }
}

export function formatMatchProgress(status, failReason) {
  if (status === 'queued') return '匹配任务已排队，AI 服务接入后会在这里返回推荐成果。'
  if (status === 'running') return 'AI 正在按该需求匹配技术成果，请稍候…'
  if (status === 'failed') return '匹配失败：' + (failReason || '未知原因，请稍后重试')
  if (status === 'succeeded') return '匹配完成，可点击成果查看详情。'
  return '任务状态：' + (status || '未知')
}
