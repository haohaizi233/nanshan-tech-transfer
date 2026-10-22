import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildEvalStreamUrl,
  canUseEvalStream,
  extractStreamSections,
  parseSseFrames,
} from '../subpackages/tech-transfer/api/ai-eval-stream.mjs'

// ══════════════════════════════════════════════════════════════
// SSE 帧解析
// ══════════════════════════════════════════════════════════════

test('parseSseFrames 切出完整帧并保留半截帧', () => {
  const buffer = 'data: {"type":"stage","text":"读取中"}\n\ndata: {"type":"content_'
  const { frames, rest } = parseSseFrames(buffer)
  assert.equal(frames.length, 1)
  assert.deepEqual(frames[0], { type: 'stage', text: '读取中' })
  assert.equal(rest, 'data: {"type":"content_')
})

test('parseSseFrames 忽略心跳注释与 event: 行', () => {
  const buffer = ': keep-alive\n\nevent: message\ndata: {"type":"timeout"}\n\n'
  const { frames, rest } = parseSseFrames(buffer)
  assert.equal(frames.length, 1)
  assert.equal(frames[0].type, 'timeout')
  assert.equal(rest, '')
})

test('parseSseFrames 兼容 CRLF 分隔', () => {
  const { frames } = parseSseFrames('data: {"type":"done","status":"succeeded"}\r\n\r\n')
  assert.equal(frames.length, 1)
  assert.equal(frames[0].status, 'succeeded')
})

test('parseSseFrames 丢弃损坏帧但不断流', () => {
  const buffer = 'data: {bad json}\n\ndata: {"type":"stage","text":"x"}\n\n'
  const { frames } = parseSseFrames(buffer)
  assert.equal(frames.length, 1)
  assert.equal(frames[0].type, 'stage')
})

// ══════════════════════════════════════════════════════════════
// URL 与能力检测
// ══════════════════════════════════════════════════════════════

test('buildEvalStreamUrl 与请求层同构（apiBase + apiPrefix + path）', () => {
  assert.equal(
    buildEvalStreamUrl({ apiBase: 'http://43.138.138.200:8025', apiPrefix: '/api/tech-transfer/v1' }, 7),
    'http://43.138.138.200:8025/api/tech-transfer/v1/ai/evaluation-tasks/7/stream',
  )
  // 生产同源：apiBase 为空 → 相对路径
  assert.equal(
    buildEvalStreamUrl({ apiBase: '', apiPrefix: '/api/tech-transfer/v1' }, 9),
    '/api/tech-transfer/v1/ai/evaluation-tasks/9/stream',
  )
  // 末尾斜杠容错
  assert.equal(
    buildEvalStreamUrl({ apiBase: 'http://x/', apiPrefix: '/p/' }, 1),
    'http://x/p//ai/evaluation-tasks/1/stream',
  )
})

test('canUseEvalStream 返回布尔值（Node 环境有 fetch，恒为 true）', () => {
  assert.equal(typeof canUseEvalStream(), 'boolean')
  assert.equal(canUseEvalStream(), true)
})

// ══════════════════════════════════════════════════════════════
// extractStreamSections：增量容错解析 partial JSON
// ══════════════════════════════════════════════════════════════

const FULL_JSON = JSON.stringify({
  dimensions: { innovation: { score: 80, comment: '创新明确' } },
  conclusion: '总体不错',
  highlights: ['快', '稳'],
  report: [
    { heading: '总体评价', content: '详细分析一' },
    { heading: '转化建议', content: '详细分析二' },
  ],
})

test('完整 JSON 走 JSON.parse 得到全部分节', () => {
  const out = extractStreamSections(FULL_JSON)
  assert.equal(out.conclusion, '总体不错')
  assert.deepEqual(out.highlights, ['快', '稳'])
  assert.equal(out.sections.length, 2)
  assert.deepEqual(out.sections[0], { heading: '总体评价', content: '详细分析一' })
})

test('空输入返回空结构', () => {
  assert.deepEqual(extractStreamSections(''), {
    conclusion: '', highlights: [], sections: [],
  })
  assert.deepEqual(extractStreamSections(null), {
    conclusion: '', highlights: [], sections: [],
  })
})

test('半截 JSON：report 尾部对象只有半个字符串也能解析', () => {
  const raw = '{"conclusion":"不错","report":[{"heading":"总体评价","content":"详细分析一"},{"heading":"转化","content":"详细'
  const out = extractStreamSections(raw)
  assert.equal(out.conclusion, '不错')
  assert.equal(out.sections.length, 2)
  assert.deepEqual(out.sections[0], { heading: '总体评价', content: '详细分析一' })
  assert.equal(out.sections[1].heading, '转化')
  assert.equal(out.sections[1].content, '详细')
})

test('半截 JSON：report 数组只到 heading 也出分节', () => {
  const raw = '{"report":[{"heading":"总体评'
  const out = extractStreamSections(raw)
  assert.equal(out.sections.length, 1)
  assert.equal(out.sections[0].heading, '总体评')
  assert.equal(out.sections[0].content, '')
})

test('半截 JSON：悬空逗号/冒号/半截数字可修复', () => {
  assert.equal(
    extractStreamSections('{"dimensions":{"a":{"score":80,').sections.length,
    0,
  )
  const out = extractStreamSections('{"conclusion":"好","highlights":["快",')
  assert.equal(out.conclusion, '好')
  assert.deepEqual(out.highlights, ['快'])
})

test('半截 JSON：highlights 数组逐项容错', () => {
  const out = extractStreamSections('{"highlights":["快","稳","省')
  assert.deepEqual(out.highlights, ['快', '稳', '省'])
})

test('转义字符不切错对象边界', () => {
  const raw = '{"report":[{"heading":"有\\"引号\\"","content":"含{花}括号"},{"heading":"B","content":"C"}]}'
  const out = extractStreamSections(raw)
  assert.equal(out.sections.length, 2)
  assert.equal(out.sections[0].heading, '有"引号"')
  assert.equal(out.sections[0].content, '含{花}括号')
})

test('JSON 前的杂文字 / markdown 围栏容错', () => {
  const out = extractStreamSections('好的，评价如下：\n```json\n{"conclusion":"行"}')
  assert.equal(out.conclusion, '行')
})
