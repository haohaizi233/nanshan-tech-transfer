import test from 'node:test'
import assert from 'node:assert/strict'

import {
  normalizeOtpInput,
  isValidPhoneNumber,
  isValidEmailAddress,
  computeCooldownSeconds,
  buildContactVerifyPayload,
} from '../subpackages/tech-transfer/utils/mine-security-helpers.mjs'

import {
  createTurnId,
  isActiveRequestContext,
  mapCardList,
  normalizeHistoryMessages,
} from '../subpackages/tech-transfer/utils/ai-match-helpers.mjs'

test('mine-security-helpers: OTP preserves leading zeros and trims non-digits', () => {
  assert.equal(normalizeOtpInput('001234'), '001234')
  assert.equal(normalizeOtpInput(' 0a9b8765 '), '098765')
  assert.equal(isValidPhoneNumber('+86 138-0013-8000'), true)
  assert.equal(isValidPhoneNumber('12345'), false)
  assert.equal(isValidEmailAddress('user@nanshan.cn'), true)
  assert.equal(isValidEmailAddress('bad-email'), false)
  assert.equal(computeCooldownSeconds(10500, 10000), 1)
  assert.equal(computeCooldownSeconds(9000, 10000), 0)
  assert.deepEqual(
    buildContactVerifyPayload({ type: 'phone', value: ' 13800138000 ', code: '004321', stepUpGrant: 'g1' }),
    { type: 'phone', value: '13800138000', code: '004321', stepUpGrant: 'g1' }
  )
})

test('ai-match-helpers: turnId, request context guard, and history card mapping', () => {
  const id1 = createTurnId()
  const id2 = createTurnId()
  assert.ok(id1.startsWith('ai_'))
  assert.notEqual(id1, id2)

  assert.equal(
    isActiveRequestContext({ alive: true, visible: true, scope: 'u1', currentScope: 'u1', generation: 2, currentGeneration: 2 }),
    true
  )
  assert.equal(
    isActiveRequestContext({ alive: true, visible: false, scope: 'u1', currentScope: 'u1', generation: 2, currentGeneration: 2 }),
    false
  )
  assert.equal(
    isActiveRequestContext({ alive: true, visible: true, scope: 'u1', currentScope: 'u2', generation: 2, currentGeneration: 2 }),
    false
  )

  const mapped = mapCardList([{ id: 1, title: 'A' }], (c) => ({ ...c, tagged: true }))
  assert.deepEqual(mapped, [{ id: 1, title: 'A', tagged: true }])

  const hist = normalizeHistoryMessages([{ role: 'assistant', cards: [{ id: 2 }] }], (c) => ({ ...c, v: 1 }))
  assert.deepEqual(hist[0].cards, [{ id: 2, v: 1 }])
})
