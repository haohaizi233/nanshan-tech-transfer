import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  formatMaturityLabel,
  toAchievementDockCard,
  toAchievementPreviewCard,
} from '../subpackages/tech-transfer/api/achievement-dock-card.mjs'

test('keeps the API ownership flag when preparing an achievement for docking', () => {
  const detail = toAchievementDockCard({
    id: 347,
    title: '自有成果',
    isMine: true,
    status: 'published',
    version: 6,
    sourceOrgName: '南山测试大学',
  })

  assert.equal(detail.isMine, true)
  assert.equal(detail.status, 'published')
  assert.equal(detail.statusLabel, '已发布')
  assert.equal(detail.version, 6)
  assert.equal(detail.title, '自有成果')
  assert.equal(detail.source, '南山测试大学')
})

test('hides the docking entry for an owned achievement in preview cards', () => {
  assert.equal(toAchievementPreviewCard({ id: 1, isMine: true }).canDock, false)
  assert.equal(toAchievementPreviewCard({ id: 2, isMine: false }).canDock, true)
})

test('shows Chinese maturity labels instead of raw callback codes', () => {
  assert.equal(formatMaturityLabel('01_idea'), '概念阶段')
  assert.equal(formatMaturityLabel('02_lab', '02_lab'), '实验室验证')
  assert.equal(formatMaturityLabel('03_pilot_ready', '可进入中试'), '可进入中试')
  assert.equal(
    toAchievementDockCard({ maturityLevel: '01_idea' }).maturity,
    '概念阶段',
  )
  assert.equal(
    toAchievementDockCard({ maturityLevel: '02_lab', maturityDesc: '02_lab' }).maturity,
    '实验室验证',
  )
})

test('omits placeholder copy for empty optional achievement fields', () => {
  const empty = toAchievementDockCard({})
  assert.equal(empty.patentHolder, '')
  assert.equal(empty.patentNo, '')
  assert.equal(empty.maturity, '')
  assert.equal(empty.source, '')
})

test('publish form defaults maturity to the visible first option', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/post-result/post-result.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /maturityLevel:\s*'01_idea'/)
  assert.match(source, /maturityDesc:\s*\(MATURITY_OPTIONS\.find/)
})

test('own published achievements can open the take-down confirm without an existing intention', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/dock-detail/dock-detail.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /if \(!this\.intention && op !== 'offline'\) return/)
  assert.match(source, /this\.detail\.status === 'published'/)
  assert.match(source, />下架<\/button>/)
})
