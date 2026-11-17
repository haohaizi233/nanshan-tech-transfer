import test from 'node:test'
import assert from 'node:assert/strict'
import { formatReplyNodes } from '../subpackages/tech-transfer/api/ai-chat.mjs'

test('回复保留分段、首行缩进和 Markdown 层次', () => {
  const nodes = formatReplyNodes('## 推荐成果\n第一段 **重点**\n第二段\n\n1. 成果一\n2. 成果二')
  assert.equal(nodes.length, 5)
  assert.match(nodes[0].attrs.style, /font-weight:600/)
  assert.match(nodes[1].attrs.style, /text-indent:2em/)
  assert.equal(nodes[1].children[1].name, 'strong')
  assert.doesNotMatch(nodes[3].attrs.style, /text-indent:2em/)
  assert.equal(nodes[4].children[0].text, '2. 成果二')
})

test('模型输出中的 HTML 只能作为文字展示', () => {
  const nodes = formatReplyNodes('<img src=x onerror=alert(1)>')
  assert.equal(nodes[0].children[0].type, 'text')
  assert.equal(nodes[0].children[0].text, '<img src=x onerror=alert(1)>')
  assert.deepEqual(formatReplyNodes(null), [])
})
