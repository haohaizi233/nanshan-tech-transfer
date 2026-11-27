/**
 * 卡片富文本节点生成器
 * 专为各类卡片展示（成果、需求、收藏、检索、专利、资本等）提供富文本支持：
 * 1. 自动分段并添加首行缩进（text-indent: 2em）与两端对齐（text-align: justify）
 * 2. 支持常见轻量 Markdown：加粗（**bold**）、行内代码/高亮（`code`）、列表项、标题、引用
 * 3. 结构化构建微信小程序/H5 原生 <rich-text> 节点树，天然免疫 XSS 风险
 */

export function formatCardRichNodes(value, options = {}) {
  const raw = String(value ?? '').trim()
  if (!raw) return []

  const {
    lineHeight = '1.75',
    color = '#334155',
    marginBottom = '12rpx',
    codeBg = '#f1f5f9',
    codeColor = '#2563eb',
    quoteBorder = '#3b82f6',
    defaultIndent = '2em',
  } = options

  return raw
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => {
      const heading = line.match(/^#{1,6}\s+(.+)$/)
      const list = /^(?:[-*+]\s+|\d+[.、)]\s*)/.test(line)
      const quote = /^>\s?/.test(line)
      const content = heading ? heading[1] : quote ? line.replace(/^>\s?/, '') : line

      const children = content
        .split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
        .filter(Boolean)
        .map(part => {
          if (part.startsWith('**') && part.endsWith('**')) {
            return {
              name: 'strong',
              attrs: { style: 'font-weight:600;color:#0f172a;' },
              children: [{ type: 'text', text: part.slice(2, -2) }],
            }
          }
          if (part.startsWith('`') && part.endsWith('`')) {
            return {
              name: 'code',
              attrs: {
                style: `background:${codeBg};color:${codeColor};padding:2rpx 8rpx;border-radius:6rpx;font-family:monospace;font-size:0.92em;margin:0 4rpx;`,
              },
              children: [{ type: 'text', text: part.slice(1, -1) }],
            }
          }
          return { type: 'text', text: part }
        })

      let style = `margin:0 0 ${marginBottom};line-height:${lineHeight};color:${color};word-break:break-word;text-align:justify;`
      if (heading) {
        style += 'font-weight:600;font-size:1.06em;color:#0f172a;text-indent:0;'
      } else if (list) {
        style += 'padding-left:1.2em;text-indent:0;'
      } else if (quote) {
        style += `border-left:6rpx solid ${quoteBorder};padding-left:16rpx;background:rgba(59,130,246,0.04);border-radius:4rpx;color:#475569;text-indent:0;`
      } else {
        style += `text-indent:${defaultIndent};`
      }

      return { name: 'div', attrs: { style }, children }
    })
}
