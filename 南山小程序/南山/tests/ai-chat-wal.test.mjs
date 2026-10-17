import assert from 'node:assert/strict'
import test from 'node:test'

import {
  AI_CHAT_WAL_PREFIX,
  acknowledgeTurn,
  beginTurn,
  clearTurns,
  loadActiveTurn,
  saveTurnResult,
} from '../subpackages/tech-transfer/api/ai-chat-wal.mjs'

function memoryStorage(initial = {}) {
  const values = { ...initial }
  return {
    values,
    getStorageSync(key) { return values[key] },
    setStorageSync(key, value) { values[key] = value },
    removeStorageSync(key) { delete values[key] },
  }
}

function accountStorage(userId, initial = {}) {
  return memoryStorage({
    tt_auth_mode: 'account',
    tt_current_user: { userId },
    ...initial,
  })
}

test('beginTurn persists the question before a request and exposes it for recovery', () => {
  const storage = accountStorage(7)
  assert.equal(beginTurn({ turnId: 'ai_abc_123', message: '查找视觉成果' }, storage), true)
  const turn = loadActiveTurn(storage)
  assert.equal(turn.turnId, 'ai_abc_123')
  assert.equal(turn.message, '查找视觉成果')
  assert.equal(turn.status, 'pending')
  assert.equal(storage.values[AI_CHAT_WAL_PREFIX + '7'].turn.message, '查找视觉成果')
})

test('a pending turn cannot be overwritten before it is acknowledged', () => {
  const storage = accountStorage(7)
  assert.equal(beginTurn({ turnId: 'ai_first', message: 'first' }, storage), true)
  assert.equal(beginTurn({ turnId: 'ai_second', message: 'second' }, storage), false)
  assert.equal(loadActiveTurn(storage).turnId, 'ai_first')
})

test('terminal results are written before display and survive reload until acknowledged', () => {
  const storage = accountStorage(7)
  beginTurn({ turnId: 'ai_done', message: 'question' }, storage)
  assert.equal(saveTurnResult('ai_done', { content: 'reply', type: 'text', payload: null }, 'succeeded', storage), true)
  const restored = loadActiveTurn(storage)
  assert.equal(restored.status, 'succeeded')
  assert.equal(restored.result.content, 'reply')
  assert.equal(acknowledgeTurn('ai_done', storage), true)
  assert.equal(loadActiveTurn(storage), null)
})

test('failed turn state can be recovered and acknowledged', () => {
  const storage = accountStorage(7)
  beginTurn({ turnId: 'ai_failed', message: 'question' }, storage)
  assert.equal(saveTurnResult('ai_failed', { content: 'unavailable' }, 'failed', storage), true)
  assert.equal(loadActiveTurn(storage).status, 'failed')
  acknowledgeTurn('ai_failed', storage)
  assert.equal(loadActiveTurn(storage), null)
})

test('WAL result sanitizer drops credentials and local temporary file paths', () => {
  const storage = accountStorage(7)
  beginTurn({ turnId: 'ai_sanitized', message: 'question' }, storage)
  saveTurnResult('ai_sanitized', {
    content: 'answer',
    payload: { cards: [{ title: 'safe', tempFilePath: 'wxfile://local-secret' }] },
    accessToken: 'must-not-persist',
  }, 'succeeded', storage)
  const turn = loadActiveTurn(storage)
  assert.equal(turn.result.accessToken, undefined)
  assert.equal(turn.result.payload.cards[0].tempFilePath, undefined)
  assert.equal(turn.result.payload.cards[0].title, 'safe')
})

test('WAL state is isolated by account and anonymous sessions', () => {
  const first = accountStorage(7)
  const second = accountStorage(8)
  beginTurn({ turnId: 'ai_user7', message: 'private question' }, first)
  assert.equal(loadActiveTurn(second), null)
  assert.equal(loadActiveTurn(memoryStorage()), null)
  assert.notEqual(AI_CHAT_WAL_PREFIX + '7', AI_CHAT_WAL_PREFIX + '8')
})

test('malformed WAL entries are removed and treated as a cache miss', () => {
  const key = AI_CHAT_WAL_PREFIX + '7'
  const storage = accountStorage(7, { [key]: { version: 999, scope: '7' } })
  assert.equal(loadActiveTurn(storage), null)
  assert.equal(storage.getStorageSync(key), undefined)
})

test('invalid serialized WAL data is removed so later sends can start safely', () => {
  const key = AI_CHAT_WAL_PREFIX + '7'
  const storage = accountStorage(7, { [key]: '{not-json' })
  assert.equal(loadActiveTurn(storage), null)
  assert.equal(storage.getStorageSync(key), undefined)
  assert.equal(beginTurn({ turnId: 'ai_recovered', message: 'question' }, storage), true)
})

test('storage write failures stop the caller from sending a turn', () => {
  const storage = accountStorage(7)
  storage.setStorageSync = () => { throw new Error('quota exceeded') }
  assert.equal(beginTurn({ turnId: 'ai_no_storage', message: 'question' }, storage), false)
  assert.equal(saveTurnResult('missing', {}, 'succeeded', storage), false)
})

test('clearTurns removes only the active account WAL', () => {
  const first = accountStorage(7)
  const second = accountStorage(8)
  beginTurn({ turnId: 'ai_user7', message: 'private question' }, first)
  beginTurn({ turnId: 'ai_user8', message: 'other question' }, second)
  assert.equal(clearTurns(first), true)
  assert.equal(loadActiveTurn(first), null)
  assert.equal(loadActiveTurn(second).message, 'other question')
})
