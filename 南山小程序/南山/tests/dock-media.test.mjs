import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')

test('demand cards keep attachment urls so dock-detail can render images', () => {
  const demand = read('../subpackages/tech-transfer/api/demand.js')
  assert.match(demand, /attachments:\s*\(d\.attachments \|\| \[\]\)\.map/)
  assert.match(demand, /url:\s*item\.url/)
})

test('dock-detail shows demand and achievement images through resolved media urls', () => {
  const detail = read('../subpackages/tech-transfer/pages/dock-detail/dock-detail.vue')
  assert.match(detail, /demandImages/)
  assert.match(detail, /resultMedia/)
  assert.match(detail, /mediaDisplayUrl/)
  assert.match(detail, /需求图片/)
  assert.doesNotMatch(detail, /:src="media\.url"/)
})

test('publish preview and post pages pass image thumbnails instead of filenames only', () => {
  const preview = read('../subpackages/tech-transfer/components/publish-preview.vue')
  const demand = read('../subpackages/tech-transfer/pages/post-demand/post-demand.vue')
  const result = read('../subpackages/tech-transfer/pages/post-result/post-result.vue')
  assert.match(preview, /previewImages/)
  assert.match(preview, /preview-thumb/)
  assert.match(demand, /:images="previewImages"/)
  assert.match(demand, /localPath:\s*path/)
  assert.match(result, /:images="previewImages"/)
  assert.match(result, /localPath:\s*path/)
})
