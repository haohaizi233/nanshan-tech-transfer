/**
 * 专利检索命中词高亮切分。
 *
 * 后端在 title / snippet / assignee 里用 <b> 标出命中词，
 * 清洗标签后单独以 `highlights` 字段回传（见 tech-transfer-service
 * 的 modules/patent/normalize.py）。前端按这些命中词把文本切成
 * 普通段与命中段，交替渲染。
 */

/**
 * 把文本按命中词切成片段数组。
 *
 * @param {string} text 原始文本
 * @param {string[]} highlights 命中词列表
 * @returns {Array<{text: string, hit: boolean}>}
 */
export function splitHighlightSegments(text, highlights) {
  const source = typeof text === 'string' ? text : ''
  if (!source) return []
  const words = (Array.isArray(highlights) ? highlights : [])
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter((item) => item.length > 0)
  if (!words.length) return [{ text: source, hit: false }]

  // 长词优先，避免短词先切碎长词
  const sorted = [...new Set(words)].sort((a, b) => b.length - a.length)

  const segments = []
  let rest = source
  let guard = 0
  while (rest && guard < 200) {
    guard += 1
    let bestIndex = -1
    let bestWord = ''
    for (const word of sorted) {
      const index = rest.indexOf(word)
      if (index === -1) continue
      if (bestIndex === -1 || index < bestIndex || (index === bestIndex && word.length > bestWord.length)) {
        bestIndex = index
        bestWord = word
      }
    }
    if (bestIndex === -1) {
      segments.push({ text: rest, hit: false })
      break
    }
    if (bestIndex > 0) segments.push({ text: rest.slice(0, bestIndex), hit: false })
    segments.push({ text: bestWord, hit: true })
    rest = rest.slice(bestIndex + bestWord.length)
  }
  if (!segments.length) return [{ text: source, hit: false }]
  return segments
}

/**
 * 判断一行是否含有命中词（用于结果摘要的标记）。
 *
 * @param {object} item 列表项
 * @returns {boolean}
 */
export function hasPatentHighlight(item) {
  if (!item || typeof item !== 'object') return false
  const list = Array.isArray(item.highlights) ? item.highlights : []
  return list.some((word) => typeof word === 'string' && word.trim().length > 0)
}
