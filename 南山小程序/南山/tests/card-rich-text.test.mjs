import test from 'node:test'
import assert from 'node:assert/strict'
import { formatCardRichNodes } from '../subpackages/tech-transfer/utils/card-rich-text.mjs'

test('formatCardRichNodes 空值安全返回空数组', () => {
  assert.deepEqual(formatCardRichNodes(null), [])
  assert.deepEqual(formatCardRichNodes(''), [])
  assert.deepEqual(formatCardRichNodes(undefined), [])
  assert.deepEqual(formatCardRichNodes('   '), [])
})

test('普通文本自动分段并采用两端对齐、舒适行高和 2em 首行缩进', () => {
  const text = '第一段科技成果描述。\n第二段包含更多技术细节。'
  const nodes = formatCardRichNodes(text)
  assert.equal(nodes.length, 2)
  assert.equal(nodes[0].name, 'div')
  assert.match(nodes[0].attrs.style, /text-indent:\s*2em/)
  assert.match(nodes[0].attrs.style, /line-height:\s*1\.[78]/)
  assert.match(nodes[0].attrs.style, /text-align:\s*justify/)
  assert.equal(nodes[0].children[0].text, '第一段科技成果描述。')
  assert.match(nodes[1].attrs.style, /text-indent:\s*2em/)
  assert.equal(nodes[1].children[0].text, '第二段包含更多技术细节。')
})

test('支持 Markdown 加粗 **文本**', () => {
  const text = '本专利采用 **高精度声镊技术** 实现细胞转染。'
  const nodes = formatCardRichNodes(text)
  assert.equal(nodes.length, 1)
  const children = nodes[0].children
  assert.equal(children[0].type, 'text')
  assert.equal(children[0].text, '本专利采用 ')
  assert.equal(children[1].name, 'strong')
  assert.equal(children[1].children[0].text, '高精度声镊技术')
  assert.equal(children[2].type, 'text')
  assert.equal(children[2].text, ' 实现细胞转染。')
})

test('支持代码与高亮 `代码/关键词`', () => {
  const text = '基于 `Python 3.10` 和 `PyTorch` 深度学习框架。'
  const nodes = formatCardRichNodes(text)
  assert.equal(nodes.length, 1)
  const codes = nodes[0].children.filter(c => c.name === 'code')
  assert.equal(codes.length, 2)
  assert.equal(codes[0].children[0].text, 'Python 3.10')
  assert.equal(codes[1].children[0].text, 'PyTorch')
})

test('列表项采用列表内边距，普通段落保持 2em 缩进', () => {
  const text = '该组合包含如下专利：\n1. 城市地铁站域特征识别\n2. 轨迹生成方法与装置'
  const nodes = formatCardRichNodes(text)
  assert.equal(nodes.length, 3)
  assert.match(nodes[0].attrs.style, /text-indent:\s*2em/)
  assert.doesNotMatch(nodes[1].attrs.style, /text-indent:\s*2em/)
  assert.match(nodes[1].attrs.style, /padding-left/)
  assert.equal(nodes[1].children[0].text, '1. 城市地铁站域特征识别')
  assert.doesNotMatch(nodes[2].attrs.style, /text-indent:\s*2em/)
})

test('支持引用语法 > 引用内容', () => {
  const text = '> 重点实验室核心成果推荐'
  const nodes = formatCardRichNodes(text)
  assert.equal(nodes.length, 1)
  assert.match(nodes[0].attrs.style, /border-left/)
  assert.equal(nodes[0].children[0].text, '重点实验室核心成果推荐')
})
