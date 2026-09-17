import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('achievement import staging has an admin route and review actions', () => {
  const router = read('../router/index.js')
  const page = read('../views/admin/AchievementImportView.vue')
  assert.match(router, /AchievementImportView/)
  assert.match(router, /path:\s*'achievement-imports'/)
  assert.match(page, /\/admin\/achievement-imports/)
  assert.match(page, /items\/\$\{item\.id\}\/confirm/)
  assert.match(page, /仅会创建成果草稿/)
  assert.match(page, /item\.raw\.images/)
  assert.match(page, /loadCandidateImage/)
})
