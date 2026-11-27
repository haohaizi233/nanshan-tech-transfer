import test from 'node:test'
import assert from 'node:assert/strict'
import { formatPreviewText, splitParagraphs } from '../subpackages/tech-transfer/utils/paragraph-text.mjs'

test('splitParagraphs splits on newlines, trims half/full-width spaces, and drops empty lines', () => {
  const input = '\u3000\u3000第一段正文。  \r\n\r\n  \u3000第二段正文。\t\n\n   \n第三段正文。'
  assert.deepEqual(splitParagraphs(input), [
    '第一段正文。',
    '第二段正文。',
    '第三段正文。',
  ])
  assert.deepEqual(splitParagraphs(null), [])
  assert.deepEqual(splitParagraphs(undefined), [])
  assert.deepEqual(splitParagraphs('  \u3000 \n '), [])
})

test('formatPreviewText collapses newlines and full-width spaces for 2-line previews', () => {
  const input = '\u3000\u3000无人机载单比特nanoSAR雷达（S01）\n具有全天候、\u3000全天时优点。  '
  assert.equal(formatPreviewText(input), '无人机载单比特nanoSAR雷达（S01） 具有全天候、 全天时优点。')
  assert.equal(formatPreviewText(''), '')
  assert.equal(formatPreviewText(null), '')
})
