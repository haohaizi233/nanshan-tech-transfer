/**
 * ai-match.vue 对话轮次与卡片状态纯逻辑辅助函数（双端 H5 / 微信小程序通用）。
 */

export function createTurnId() {
  return 'ai_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 12)
}

export function isActiveRequestContext({
  alive = true,
  visible = true,
  scope = '',
  currentScope = '',
  generation = 0,
  currentGeneration = 0,
} = {}) {
  return Boolean(alive && visible && scope === currentScope && generation === currentGeneration)
}

export function mapCardList(cards, mapCardFn) {
  if (!Array.isArray(cards)) return []
  return cards.map((card) => (typeof mapCardFn === 'function' ? mapCardFn(card) : { ...card }))
}

export function normalizeHistoryMessages(messages, mapCardFn) {
  if (!Array.isArray(messages)) return []
  return messages.map((msg) => {
    const cards = Array.isArray(msg.cards) ? mapCardList(msg.cards, mapCardFn) : null
    return {
      ...msg,
      cards,
    }
  })
}
