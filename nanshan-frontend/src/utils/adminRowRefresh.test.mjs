import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  insertAdminRow,
  mergeAdminRow,
  reconcileAdminRow,
  removeAdminRow,
  rowMatchesAdminFilters,
} from './adminRowRefresh.js'

test('merges a refreshed record into its existing row and preserves unrelated rows', () => {
  const rows = [{ id: 1, title: 'old', localOnly: true }, { id: 2, title: 'other' }]
  assert.deepEqual(mergeAdminRow(rows, { id: 1, title: 'updated' }), [
    { id: 1, title: 'updated', localOnly: true },
    { id: 2, title: 'other' },
  ])
})

test('matches all active admin filters case-insensitively', () => {
  const row = { status: 'offline', categoryCode: 'BIO', title: 'Solar Cell', orgName: 'Green Lab' }
  assert.equal(rowMatchesAdminFilters(row, { status: 'offline', categoryCode: 'BIO', keyword: 'green' }, ['title', 'orgName']), true)
  assert.equal(rowMatchesAdminFilters(row, { status: 'published' }, ['title']), false)
  assert.equal(rowMatchesAdminFilters(row, { keyword: 'wind' }, ['title', 'orgName']), false)
})

test('inserts a created row at the front and keeps the current page size', () => {
  assert.deepEqual(insertAdminRow([{ id: 2 }, { id: 1 }], { id: 3 }, 2), [{ id: 3 }, { id: 2 }])
})

test('removes only the affected row using string-safe IDs', () => {
  assert.deepEqual(removeAdminRow([{ id: 1 }, { id: '2' }, { id: 3 }], 2), [{ id: 1 }, { id: 3 }])
})

test('reconciles a status change that no longer matches filters and decrements the total', () => {
  const result = reconcileAdminRow([{ id: 1, status: 'published' }], { id: 1, status: 'offline' }, {
    filters: { status: 'published' },
    keywordFields: ['title'],
  })
  assert.deepEqual(result, { rows: [], totalDelta: -1 })
})

test('counts a matching created row but inserts it only on the first page', () => {
  const created = { id: 3, status: 'draft', title: 'New' }
  const laterPage = reconcileAdminRow([{ id: 2 }], created, {
    filters: { status: 'draft' }, keywordFields: ['title'], page: 2, pageSize: 10, created: true,
  })
  assert.deepEqual(laterPage, { rows: [{ id: 2 }], totalDelta: 1 })
  const firstPage = reconcileAdminRow([{ id: 2 }], created, {
    filters: { status: 'draft' }, keywordFields: ['title'], page: 1, pageSize: 1, created: true,
  })
  assert.deepEqual(firstPage, { rows: [created], totalDelta: 1 })
})

test('supports rows keyed by userId and exact module filters', () => {
  const rows = [{ userId: 8, status: 'active', kind: 'enterprise' }]
  const updated = { userId: 8, status: 'active', kind: 'platform', platformTypeKey: 'poc' }
  const changed = reconcileAdminRow(rows, updated, {
    idField: 'userId',
    exactFields: ['status', 'kind', 'platformTypeKey'],
    filters: { kind: 'platform', platformTypeKey: 'poc' },
    keywordFields: ['displayName'],
  })
  assert.deepEqual(changed, { rows: [{ ...rows[0], ...updated }], totalDelta: 0 })
  assert.deepEqual(removeAdminRow(changed.rows, 8, 'userId'), [])
})

test('admin record forms reconcile affected rows instead of reloading their whole tables', () => {
  const pages = [
    'AchievementView.vue',
    'RequirementView.vue',
    'CapitalView.vue',
    'InstitutionView.vue',
    'MembershipReviewView.vue',
    'UserView.vue',
  ]
  for (const page of pages) {
    const source = readFileSync(new URL(`../views/admin/${page}`, import.meta.url), 'utf8')
    assert.match(source, /reconcileAdminRow\(|apply\w*Row\(/, `${page} should reconcile only the changed row`)
  }

  const detailSource = readFileSync(new URL('../views/admin/RequirementDetailView.vue', import.meta.url), 'utf8')
  assert.match(detailSource, /await fetchDetail\(\)/, 'requirement detail actions should refresh the current detail only')
  assert.doesNotMatch(detailSource, /fetchList\(/, 'requirement detail should not reload a table')
})

test('creating records on a later page preserves the active page until row reconciliation', () => {
  const pages = [
    ['AchievementView.vue', 'refreshAchievementRow'],
    ['RequirementView.vue', 'refreshDemandRow'],
    ['CapitalView.vue', 'refreshCapitalRow'],
    ['InstitutionView.vue', 'refreshInstitutionRow'],
  ]
  for (const [page, refreshName] of pages) {
    const source = readFileSync(new URL(`../views/admin/${page}`, import.meta.url), 'utf8')
    const saveFlow = source.match(
      /const created = (?:formMode|modalMode)\.value === 'create'[\s\S]*?await refresh\w+Row\(saved\.id, \{ created \}\)/,
    )?.[0]
    assert.ok(saveFlow, `${page} should save and reconcile its affected row`)
    assert.doesNotMatch(saveFlow, /currentPage\.value\s*=\s*1/, `${page} must not reset pagination after create`)
    assert.match(saveFlow, new RegExp(`await ${refreshName}\\(saved\\.id, \\{ created \\}\\)`))
  }
})

test('achievement staging imports and publishes update batch rows without reloading the batch table', () => {
  const source = readFileSync(new URL('../views/admin/AchievementImportView.vue', import.meta.url), 'utf8')
  assert.match(source, /upsertBatchSummary\(/, 'batch details should reconcile their summary row')
  const publish = source.match(/async function publishItem\([\s\S]*?\n\}/)?.[0] || ''
  assert.match(publish, /selectBatch\(/, 'publishing should refresh the selected batch detail')
  assert.doesNotMatch(publish, /loadBatches\(/, 'publishing should not refetch the entire batch list')
  const importFlow = source.match(/async function runImportFlow\([\s\S]*?\n\}/)?.[0] || ''
  assert.doesNotMatch(importFlow, /loadBatches\(/, 'new batches should be inserted from import results')
})
