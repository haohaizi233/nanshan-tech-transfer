import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('achievement import staging keeps separate scroll panes and a single-column media preview', () => {
  const router = read('../router/index.js')
  const page = read('../views/admin/AchievementImportView.vue')
  assert.match(router, /AchievementImportView/)
  assert.match(router, /path:\s*'achievement-imports'/)
  assert.match(page, /\/admin\/achievement-imports/)
  assert.match(page, /items\/\$\{item\.id\}\/publish/)
  assert.match(page, /一键发布成果/)
  assert.match(page, /activeRaw\.value\.images/)
  assert.match(page, /loadCandidateImage/)
  assert.match(page, /\.batches\s*\{[^}]*overflow-y:\s*auto/)
  assert.match(page, /\.phone-preview\s*\{[^}]*overflow-y:\s*auto/)
  assert.match(page, /height:\s*calc\(100vh - 190px\)/)
  assert.match(page, /@media \(max-width: 900px\)[\s\S]*grid-template-rows/)
  assert.match(page, /@media \(max-width: 900px\)[\s\S]*\.phone-preview\s*\{[^}]*overflow-y:\s*auto/)
  assert.match(page, /\.mp-image-grid\s*\{[^}]*grid-template-columns:\s*1fr/)
})
