import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolveContentFormActions } from './contentFormActions.js'

test('org admin create: draft + submit, never publish', () => {
  const actions = resolveContentFormActions({
    kind: 'demand',
    isPlatformAdmin: false,
    formMode: 'create',
  })
  assert.equal(actions.canSaveDraft, true)
  assert.equal(actions.canSubmit, true)
  assert.equal(actions.canPublish, false)
  assert.equal(actions.canSaveContent, false)
})

test('org admin published/matched: save content only, no submit', () => {
  for (const status of ['published', 'matched', 'closed', 'cancelled']) {
    const actions = resolveContentFormActions({
      kind: 'demand',
      isPlatformAdmin: false,
      formMode: 'edit',
      status,
    })
    assert.equal(actions.canSubmit, false, status)
    assert.equal(actions.canPublish, false, status)
    assert.equal(actions.canSaveDraft, false, status)
    assert.equal(actions.canSaveContent, true, status)
  }
})

test('org admin draft/rejected can submit; pending_review only saves content', () => {
  const draft = resolveContentFormActions({
    kind: 'demand',
    isPlatformAdmin: false,
    formMode: 'edit',
    status: 'draft',
  })
  assert.equal(draft.canSubmit, true)
  assert.equal(draft.canSaveDraft, true)

  const pending = resolveContentFormActions({
    kind: 'demand',
    isPlatformAdmin: false,
    formMode: 'edit',
    status: 'pending_review',
  })
  assert.equal(pending.canSubmit, false)
  assert.equal(pending.canSaveDraft, false)
  assert.equal(pending.canSaveContent, true)
})

test('platform admin pending_review can publish or save without status change', () => {
  const actions = resolveContentFormActions({
    kind: 'demand',
    isPlatformAdmin: true,
    formMode: 'edit',
    status: 'pending_review',
  })
  assert.equal(actions.canPublish, true)
  assert.equal(actions.canSaveContent, true)
  assert.equal(actions.canSaveDraft, false)
})

test('platform admin published demand does not show 直接发布', () => {
  const actions = resolveContentFormActions({
    kind: 'demand',
    isPlatformAdmin: true,
    formMode: 'edit',
    status: 'published',
  })
  assert.equal(actions.canPublish, false)
  assert.equal(actions.canSaveContent, true)
})

test('achievement org admin can resubmit offline, not published', () => {
  const offline = resolveContentFormActions({
    kind: 'achievement',
    isPlatformAdmin: false,
    formMode: 'edit',
    status: 'offline',
  })
  assert.equal(offline.canSubmit, true)
  assert.equal(offline.canSaveDraft, true)

  const published = resolveContentFormActions({
    kind: 'achievement',
    isPlatformAdmin: false,
    formMode: 'edit',
    status: 'published',
  })
  assert.equal(published.canSubmit, false)
  assert.equal(published.canSaveContent, true)
})
