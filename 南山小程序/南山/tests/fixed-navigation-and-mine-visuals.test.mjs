import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const patentDetail = readFileSync(new URL('subpackages/tech-transfer/pages/patent-detail/patent-detail.vue', root), 'utf8')
const mine = readFileSync(new URL('subpackages/tech-transfer/pages/mine/mine.vue', root), 'utf8')
const home = readFileSync(new URL('subpackages/tech-transfer/pages/home/home.vue', root), 'utf8')
const dockDetail = readFileSync(new URL('subpackages/tech-transfer/pages/dock-detail/dock-detail.vue', root), 'utf8')
const achievementList = readFileSync(new URL('subpackages/tech-transfer/pages/achievement-list/achievement-list.vue', root), 'utf8')
const patentList = readFileSync(new URL('subpackages/tech-transfer/pages/patent-list/patent-list.vue', root), 'utf8')
const app = readFileSync(new URL('App.vue', root), 'utf8')
const membership = readFileSync(new URL('subpackages/tech-transfer/api/membership.js', root), 'utf8')

test('keeps the patent reader navigation inside the H5 portrait shell', () => {
  assert.match(patentDetail, /\.reader-nav\s*\{[\s\S]*left:\s*var\(--window-left,\s*0px\)/)
  assert.match(patentDetail, /\.reader-nav\s*\{[\s\S]*right:\s*var\(--window-right,\s*0px\)/)
})

test('switches patent reader cards instead of scrolling between all sections', () => {
  assert.match(patentDetail, /v-if="activeSection === 'abstract' && detail\.abstract"/)
  assert.match(patentDetail, /v-if="activeSection === 'claims' && detail\.claims"/)
  assert.match(patentDetail, /v-if="activeSection === 'description' && detail\.description"/)
  assert.doesNotMatch(patentDetail, /pageScrollTo/)
  assert.doesNotMatch(patentDetail, /showDescription/)
})

test('indents all detail values and descriptive preview text', () => {
	assert.match(dockDetail, /\.field-value\s*\{[\s\S]*text-indent:\s*2em/)
	assert.match(home, /class="info-text info-text-user-text"[^>]*>\{\{ item\.demandDesc \}\}/)
	assert.match(home, /class="info-text info-text-user-text"[^>]*>\{\{ item\.techIntro \}\}/)
	assert.match(home, /\.info-text-user-text\s*\{[\s\S]*text-indent:\s*2em/)
	assert.match(achievementList, /\.tech-intro\s*\{[\s\S]*text-indent:\s*2em/)
	assert.match(patentList, /\.tech-intro\s*\{[\s\S]*text-indent:\s*2em/)
})

test('uses the certification artwork as a subtle right-side scene instead of a second card frame', () => {
  assert.match(mine, /\.org-card-bg\s*\{[\s\S]*left:\s*auto[\s\S]*right:\s*-8rpx[\s\S]*width:\s*76%[\s\S]*opacity:\s*0\.92/)
  assert.match(mine, /\.org-card\s*\{[\s\S]*background:\s*linear-gradient/)
})

test('gives the supplied functional icons a larger display area', () => {
  assert.match(mine, /\.module-icon\s*\{[\s\S]*width:\s*92rpx[\s\S]*height:\s*92rpx/)
  assert.match(mine, /\.org-card-icon\s*\{[\s\S]*width:\s*112rpx[\s\S]*height:\s*112rpx/)
})

test('enlarges information icons without increasing contact row spacing', () => {
  assert.match(mine, /\.contact-icon\s*\{[\s\S]*width:\s*64rpx[\s\S]*height:\s*64rpx/)
  assert.match(mine, /\.contact-row\s*\{[\s\S]*padding:\s*12rpx 0/)
})

test('shows the supplied certification icon on card previews and dock details', () => {
  const certificationIcon = /\/static\/icons\/mine\/certification-badge\.png/
  assert.match(home, certificationIcon)
  assert.match(dockDetail, certificationIcon)
  assert.match(app, /\.cert-badge-icon-inline\s*\{[\s\S]*width:\s*24rpx[\s\S]*height:\s*24rpx/)
})

test('uses a per-account certification cache before revalidating the mine card', () => {
  assert.match(membership, /export function getCachedOrganizationCertification\(/)
  assert.match(membership, /export function isOrganizationCertificationCacheFresh\(/)
  assert.match(mine, /const cachedCertification = getCachedOrganizationCertification\(\)/)
  assert.match(mine, /cacheOrganizationCertification\(certification\)/)
})

test('keeps organization card secondary actions transparent and gives unverified state its own layout', () => {
  assert.match(mine, /\.org-manage-btn\s*\{[\s\S]*background:\s*transparent/)
  assert.match(mine, /\.org-action-btn\s*\{[\s\S]*background:\s*transparent/)
  assert.match(mine, /\.org-card-unverified\s*\{[\s\S]*background:\s*linear-gradient/)
})

test('lets a profile keep free-form company text while choosing an existing institution suggestion', () => {
  assert.match(mine, /@focus="showCompanySuggestions"/)
  assert.match(mine, /@input="onCompanyInput"/)
  assert.match(mine, /v-for="org in companySuggestions"/)
  assert.match(mine, /searchInstitutions\(keyword, 1, 8\)/)
  assert.match(mine, /selectCompanySuggestion\(org\)/)
})

test('uses the certification backdrop and compact actions in one unverified card row', () => {
  assert.match(mine, /class="org-card-bg" src="\/static\/images\/mine\/org-certification-bg\.png"/)
  assert.doesNotMatch(mine, /<image v-if="certification\.status !== 'unverified'" class="org-card-bg"/)
  assert.match(mine, /<button class="org-action-btn" size="mini" @click="goOrgJoin">加入机构<\/button>/)
  assert.match(mine, /<button class="org-action-btn ghost" size="mini" @click="goOrgApply">机构入驻<\/button>/)
  assert.match(mine, /\.org-card-unverified\s*\{[\s\S]*min-height:\s*132rpx/)
})
