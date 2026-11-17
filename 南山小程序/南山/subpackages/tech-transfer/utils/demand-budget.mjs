// Amounts are in 万元. Negotiability never removes an amount constraint.
function amount(value) {
  if (typeof value !== 'number' && typeof value !== 'string') return null
  if (typeof value === 'string' && !/^\d+(?:\.\d+)?$/.test(value.trim())) return null
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 ? n : null
}

export function formatDemandBudget(demand = {}) {
  const min = amount(demand.budgetMinWan)
  const max = amount(demand.budgetMaxWan)
  const negotiable = demand.budgetNegotiable === true
  if (min !== null && max !== null && min > max) return '预算数据异常'
  // Avoid exponent notation so every finite amount can be parsed back.
  const display = n => {
    const [coefficient, exponent] = String(n).split('e')
    if (exponent === undefined) return coefficient
    const digits = coefficient.replace('.', '')
    const point = (coefficient.indexOf('.') < 0 ? coefficient.length : coefficient.indexOf('.')) + Number(exponent)
    if (point <= 0) return '0.' + '0'.repeat(-point) + digits
    if (point >= digits.length) return digits + '0'.repeat(point - digits.length)
    return digits.slice(0, point) + '.' + digits.slice(point)
  }
  let text
  if (min !== null && max !== null) text = min === max ? `${display(min)} 万元` : `${display(min)}–${display(max)} 万元`
  else if (min !== null) text = `${display(min)} 万元以上`
  else if (max !== null) text = `${display(max)} 万元以内`
  else return negotiable ? '面议' : '未提供预算'
  return text + (negotiable ? '（可议）' : '')
}

// Empty input is optional; read-only placeholders and invalid text are rejected.
export function parseDemandBudget(text) {
  const raw = String(text ?? '').trim()
  if (!raw) return {}
  const error = () => { throw new Error('预算格式不正确，请填写如100万元以内或80–120万元（可议）') }
  const compact = raw.replace(/\s+/g, '')
  const marker = compact.match(/^(.*?)(?:[，,、]?面议|[，,、]?可议|[（(](?:可议|面议)[）)])$/)
  const negotiable = Boolean(marker)
  const value = marker ? marker[1] : compact
  if (!value) return { budgetNegotiable: true }
  const number = '(\\d+(?:\\.\\d+)?)'
  let result
  let m = value.match(new RegExp(`^${number}(?:万元|万)?[–~至-]${number}(?:万元|万)?$`))
  if (m) {
    result = { budgetMinWan: Number(m[1]), budgetMaxWan: Number(m[2]) }
    if (result.budgetMinWan > result.budgetMaxWan) throw new Error('预算下限不能大于上限，请修正')
  } else {
    m = value.match(new RegExp(`^${number}(?:万元|万)?(以内|以上)?$`))
    if (!m) return error()
    const n = Number(m[1])
    result = m[2] === '以内' ? { budgetMaxWan: n } : m[2] === '以上' ? { budgetMinWan: n } : { budgetMinWan: n, budgetMaxWan: n }
  }
  if (Object.values(result).some(n => !Number.isFinite(n))) return error()
  return { ...result, ...(negotiable ? { budgetNegotiable: true } : {}) }
}
