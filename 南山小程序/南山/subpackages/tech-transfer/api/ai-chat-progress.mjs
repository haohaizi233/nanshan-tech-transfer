const STAGE_TEXT = {
  queued: '问题已受理，正在排队…',
  context: '正在整理本轮会话…',
  routing: '正在理解你的问题…',
  retrieving: '正在查找相关资料…',
  reranking: '正在筛选推荐内容…',
  formatting: '正在整理回答…',
  succeeded: '回答已完成',
  failed: '本轮未完成',
}

export function createChatProgress({ scope, turnId, generation = null, stage = '', stageSeq = -1 }) {
  return {
    scope: String(scope), turnId, generation, status: 'running',
    stage: Object.hasOwn(STAGE_TEXT, stage) ? stage : '',
    stageSeq: Number.isSafeInteger(stageSeq) ? stageSeq : -1,
  }
}

export function mergeChatProgress(current, response, scope) {
  if (!current || !response || String(scope) !== current.scope) return current
  if (response.turnId !== undefined && response.turnId !== current.turnId) return current
  if (current.generation !== null && response.generation !== undefined && response.generation !== current.generation) return current
  if (['succeeded', 'failed'].includes(current.status)) return current
  const sequence = Number.isSafeInteger(response.stageSeq) && response.stageSeq >= 0 ? response.stageSeq : current.stageSeq
  if (sequence < current.stageSeq) return current
  const legacy = response.status === undefined && typeof response.success === 'boolean'
  const status = legacy ? (response.success ? 'succeeded' : 'failed') : response.status
  if (!['running', 'succeeded', 'failed'].includes(status)) return current
  return {
    ...current,
    generation: response.generation ?? current.generation,
    status,
    stage: Object.hasOwn(STAGE_TEXT, response.stage) ? response.stage : current.stage,
    stageSeq: sequence,
  }
}

export function chatProgressText(progress) {
  return STAGE_TEXT[progress?.stage] || '人工智能正在生成…'
}

export function cardReference(message, card) {
  if (message?.role !== 'assistant' || !message.serverTurnId || !Number.isSafeInteger(message.serverGeneration)) return null
  const messageId = Number(message?.serverMessageId)
  const cardId = Number(card?.id)
  if (!Number.isSafeInteger(messageId) || messageId <= 0 || !Number.isSafeInteger(cardId) || cardId <= 0) return null
  if (!['achievement', 'demand'].includes(card.card_type)) return null
  if (!message.payload?.cards?.some(item => item.card_type === card.card_type && Number(item.id) === cardId)) return null
  return { messageId, cardType: card.card_type, cardId }
}
