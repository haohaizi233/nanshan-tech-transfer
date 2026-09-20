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
  assert.equal(empty.price, '')
  assert.equal(toAchievementPreviewCard({}).price, '')
  assert.equal(toAchievementDockCard({ pricingMode: 'negotiable' }).price, '面议')
})

test('publish form leaves optional maturity blank instead of fabricating a default', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/post-result/post-result.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /maturityLevel:\s*''/)
  assert.match(source, /return opt \? opt\.label : '请选择成熟度'/)
})

test('publish form loads and submits an optional achievement category', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/post-result/post-result.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /getAchievementCategories/)
  assert.match(source, /loadCategories\(\)/)
  assert.match(source, /categoryId: f\.categoryId \|\| undefined/)
})

test('publish form supports structured external links instead of burying URLs in text', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/post-result/post-result.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /form\.links/)
  assert.match(source, /addLink\(\)/)
  assert.match(source, /body\.links = links/)
  assert.match(source, /\^https\?:\\\/\\\//)
})

test('publish form sends structured inventor references', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/post-result/post-result.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /addInventor\(\)/)
  assert.match(source, /removeInventor\(index\)/)
  assert.match(source, /body\.inventorRefs = inventorRefs/)
})

test('publish form loads configured industries and sends selected ids without defaults', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/post-result/post-result.vue', import.meta.url),
    'utf8',
  )
  const api = readFileSync(new URL('../subpackages/tech-transfer/api/achievement.js', import.meta.url), 'utf8')
  assert.match(source, /industryIds:\s*\[\]/)
  assert.match(source, /getAchievementIndustries/)
  assert.match(source, /body\.industryIds = f\.industryIds/)
  assert.match(api, /\/achievements\/industries/)
})

test('achievement list exposes the optional configured industry filter', () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/achievement-list/achievement-list.vue', import.meta.url), 'utf8')
  assert.match(source, /getAchievementIndustries/)
  assert.match(source, /activeIndustryId/)
  assert.match(source, /industryId: this\.activeIndustryId/)
})

test('achievement preview cards use the API thumbnail rather than fetching a cover original', () => {
  const list = readFileSync(
    new URL('../subpackages/tech-transfer/pages/achievement-list/achievement-list.vue', import.meta.url),
    'utf8',
  )
  const service = readFileSync(
    new URL('../../../tech-transfer-service/modules/achievement/service.py', import.meta.url),
    'utf8',
  )
  // 列表页通过 coverDisplayUrl 解析封面，helper 内部仍优先 thumbnailUrl 再回退到 url，
  // 同时补上绝对 origin + access_token 让 WeChat MP <image> 能加载。
  assert.match(list, /coverDisplayUrl\(item\.cover\)/)
  assert.match(list, /thumbnailUrl \|\| cover\.url/)
  assert.match(service, /thumbnailUrl/)
  assert.match(service, /variant=thumbnail/)
})

test('achievement price helper never invents negotiable pricing for absent data', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/api/achievement.js', import.meta.url),
    'utf8',
  )
  assert.doesNotMatch(source, /modeLabels\[item\.pricingMode\]\s*\|\|\s*'面议'/)
  assert.match(source, /return modeLabels\[item\.pricingMode\]\s*\|\|\s*''/)
})

test('achievement list and detail hide an absent price instead of inventing a mode', () => {
  const homeSource = readFileSync(new URL('../subpackages/tech-transfer/pages/home/home.vue', import.meta.url), 'utf8')
  const detailSource = readFileSync(new URL('../subpackages/tech-transfer/pages/achievement-detail/achievement-detail.vue', import.meta.url), 'utf8')
  assert.match(homeSource, /v-if="item\.price" class="price-row"/)
  assert.match(detailSource, /return PRICING_MODE_LABELS\[mode\] \|\| ''/)
  assert.match(detailSource, /d\.priceMinWan != null \|\| d\.priceMaxWan != null/)
})

test('the active docking detail keeps dynamic achievement content from the detail API', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/dock-detail/dock-detail.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /sections: data\.sections \|\| \[\]/)
  assert.match(source, /patents: data\.patents \|\| \[\]/)
  assert.match(source, /links: data\.links \|\| \[\]/)
  assert.match(source, /media: data\.media \|\| \[\]/)
  assert.match(source, /openPatent\(patent\)/)
})

test('achievement patent links only look actionable when an internal or external route exists', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/achievement-detail/achievement-detail.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /canOpenPatent\(patent\)/)
  assert.match(source, /if \(!this\.canOpenPatent\(patent\)\) return/)
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
