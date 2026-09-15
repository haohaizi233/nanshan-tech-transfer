import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { getCapitalGroups } from '../subpackages/tech-transfer/constants/capital-modules.js'

test('capital tab hides the pending evaluation service module', () => {
  const groups = getCapitalGroups()
  assert.deepEqual(groups.map((item) => item.source), ['platform', 'finance'])
  assert.equal(groups.some((item) => item.label === '评估服务'), false)
  const home = readFileSync(new URL('../subpackages/tech-transfer/pages/home/home.vue', import.meta.url), 'utf8')
  assert.match(home, /title: '识别结果'/)
  assert.doesNotMatch(home, /成果对接待开通/)
})

test('home and dock-detail hide gray meta strips when location/budget/source are empty', () => {
  const home = readFileSync(new URL('../subpackages/tech-transfer/pages/home/home.vue', import.meta.url), 'utf8')
  const dock = readFileSync(new URL('../subpackages/tech-transfer/pages/dock-detail/dock-detail.vue', import.meta.url), 'utf8')
  assert.match(home, /v-if="item\.location \|\| item\.budget"/)
  assert.match(home, /v-if="item\.source" class="meta-row"/)
  assert.match(dock, /v-if="detail\.company \|\| detail\.location"/)
  assert.match(dock, /v-if="detail\.budget \|\| detail\.deadline"/)
  assert.match(dock, /v-if="detail\.source" class="meta-row"/)
})

test('search achievements fall back to the public list when keyword is empty', () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/search/search.vue', import.meta.url), 'utf8')
  assert.match(source, /getAchievements/)
  assert.match(source, /const data = kw[\s\S]*searchAchievements[\s\S]*getAchievements/)
  assert.match(source, /this\.resultTotal = Number\(data\.total\)/)
  assert.match(source, /this\.demandTotal = Number\(data\.total\)/)
  assert.match(source, /onReachBottom\(\)/)
  assert.match(source, /currentTotal/)
})

test('switching search categories preserves the keyword and reuses it for the next query', () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/search/search.vue', import.meta.url), 'utf8')
  const switchType = source.match(/switchType\(type\)\s*\{([\s\S]*?)\r?\n\s*\},\r?\n\s*mapDemand/)
  assert.ok(switchType)
  assert.doesNotMatch(switchType[1], /this\.keyword\s*=/)
  assert.match(switchType[1], /this\.loadDemands\(this\.keyword,\s*true\)/)
  assert.match(switchType[1], /this\.loadResults\(this\.keyword,\s*true\)/)
})

test('org apply checks duplicate names on the client before submit', () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/org-apply/org-apply.vue', import.meta.url), 'utf8')
  assert.match(source, /checkExistingName/)
  assert.match(source, /该机构已存在/)
  assert.match(source, /nameError/)
})

test('certified publication forms lock company or source to the membership org', () => {
  const postDemand = readFileSync(new URL('../subpackages/tech-transfer/pages/post-demand/post-demand.vue', import.meta.url), 'utf8')
  const postResult = readFileSync(new URL('../subpackages/tech-transfer/pages/post-result/post-result.vue', import.meta.url), 'utf8')
  const userApi = readFileSync(new URL('../subpackages/tech-transfer/api/user.js', import.meta.url), 'utf8')
  assert.match(postDemand, /certifiedCompanyLocked/)
  assert.match(postDemand, /syncCertifiedCompany/)
  assert.match(postResult, /certifiedCompanyLocked/)
  assert.match(postResult, /form\.sourceOrgName = org\.orgName/)
  assert.match(userApi, /companyText \|\| user\.orgTitle/)
})

test('membership applications list uses GET on the caller-owned endpoint', () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/api/membership.js', import.meta.url), 'utf8')
  assert.match(source, /export async function getMyMembershipApplications/)
  assert.match(source, /apiRequest\('GET', '\/me\/organization-membership-applications'/)
})

test('mine page loads publication, interaction, and membership counts sequentially', () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
  assert.match(source, /async refresh\(\)/)
  assert.match(source, /await this\.loadMyPublicationCounts\(\)/)
  assert.match(source, /await this\.loadInteractionCounts\(\)/)
  assert.match(source, /await this\.loadMemberships\(\)/)
})

test('dock detail consumes server-approved counterpart contacts and safely refreshes active cooperation', () => {
  const api = readFileSync(new URL('../subpackages/tech-transfer/api/interaction.js', import.meta.url), 'utf8')
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/dock-detail/dock-detail.vue', import.meta.url), 'utf8')

  assert.match(api, /contactShareConsent:\s*true/)
  assert.match(source, /displayContact\(\)/)
  assert.match(source, /counterpartContact/)
  assert.match(source, /startIntentRefresh\(\)/)
  assert.match(source, /stopIntentRefresh\(\)/)
  assert.match(source, /setInterval\([\s\S]*?,\s*10000\)/)

  const loadIntent = source.match(/async loadIntent\(id\)\s*\{([\s\S]*?)\r?\n\s*\},\r?\n\s*clearConfirmTimer/)
  assert.ok(loadIntent)
  assert.doesNotMatch(loadIntent[1], /this\.intention\s*=\s*null/)
})
