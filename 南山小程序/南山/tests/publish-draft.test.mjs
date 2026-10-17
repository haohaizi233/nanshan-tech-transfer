import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  clearPublishDraft,
  getPendingPublishRoute,
  restorePublishDraft,
  savePublishDraft,
} from '../subpackages/tech-transfer/api/publish-draft.mjs'

function createStorage() {
  const values = new Map()
  return {
    values,
    getStorageSync: key => values.get(key),
    setStorageSync: (key, value) => values.set(key, value),
    removeStorageSync: key => values.delete(key),
  }
}

test('guest draft transfers to the authenticated user once and is kept account scoped', () => {
  const storage = createStorage()
  assert.equal(savePublishDraft('demand', { title: 'draft', nested: { password: 'secret' } }, { storage, now: 100 }), true)
  assert.equal(getPendingPublishRoute({ storage, now: 101 }), 'pages/post-demand/post-demand')
  assert.deepEqual(restorePublishDraft('demand', { storage, scope: 'user-1', now: 102 }), {
    title: 'draft', nested: {},
  })
  assert.equal(getPendingPublishRoute({ storage, now: 103 }), null)
  assert.deepEqual(restorePublishDraft('demand', { storage, scope: 'user-1', now: 104 }), {
    title: 'draft', nested: {},
  })
  assert.equal(restorePublishDraft('demand', { storage, scope: 'user-2', now: 105 }), null)
})

test('pending login navigation claims the guest draft for the signed-in account', () => {
  const storage = createStorage()
  savePublishDraft('achievement', { title: 'pending' }, { storage, now: 10 })
  assert.equal(getPendingPublishRoute({ storage, scope: 'user-1', now: 11 }), 'pages/post-result/post-result')
  assert.equal(getPendingPublishRoute({ storage, scope: 'user-2', now: 12 }), null)
  assert.deepEqual(restorePublishDraft('achievement', { storage, scope: 'user-1', now: 13 }), { title: 'pending' })
})

test('draft expiry removes old data and preserves only remote file URLs', () => {
  const storage = createStorage()
  savePublishDraft('achievement', {
    title: 'result',
    media: [{ tempFilePath: 'wxfile://tmp/image.png', url: 'https://cdn.example/image.png' }],
  }, { storage, now: 10 })
  assert.deepEqual(restorePublishDraft('achievement', { storage, now: 20 }), {
    title: 'result', media: [{ url: 'https://cdn.example/image.png' }],
  })
  assert.equal(restorePublishDraft('achievement', { storage, now: 86_400_010 }), null)
  assert.equal(getPendingPublishRoute({ storage, now: 86_400_011 }), null)
})

test('clearing a successful publication removes guest and current user drafts', () => {
  const storage = createStorage()
  savePublishDraft('demand', { title: 'guest' }, { storage, now: 1 })
  restorePublishDraft('demand', { storage, scope: 'user-1', now: 2 })
  savePublishDraft('achievement', { title: 'private' }, { storage, scope: 'user-1', now: 3 })
  clearPublishDraft(undefined, { storage, scope: 'user-1' })
  assert.equal(restorePublishDraft('demand', { storage, scope: 'user-1', now: 4 }), null)
  assert.equal(restorePublishDraft('achievement', { storage, scope: 'user-1', now: 4 }), null)
})
