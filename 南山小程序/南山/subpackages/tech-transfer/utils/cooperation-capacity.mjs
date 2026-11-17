export const MAX_COOPERATION_CAPACITY = 9999

export function normalizeCooperationCapacity(value) {
  if (typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value) && value > MAX_COOPERATION_CAPACITY) return null
  const text = String(value ?? '').trim()
  if (!text) return null
  if (!/^\d+$/.test(text)) throw new Error('可对接名额须为正整数')
  const number = Number(text)
  if (number < 1) throw new Error('可对接名额须为正整数')
  return number > MAX_COOPERATION_CAPACITY ? null : number
}
