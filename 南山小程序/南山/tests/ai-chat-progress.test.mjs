import assert from 'node:assert/strict'
import test from 'node:test'
import * as progress from '../subpackages/tech-transfer/api/ai-chat-progress.mjs'

test('older stage events cannot regress or finish an active turn', () => {
  const start = progress.createChatProgress({ scope: '7', turnId: 'turn_a', generation: 2 })
  const running = progress.mergeChatProgress(start, { turnId: 'turn_a', generation: 2, status: 'running', stage: 'retrieving', stageSeq: 4 }, '7')
  assert.equal(running.stage, 'retrieving')
  assert.equal(progress.mergeChatProgress(running, { turnId: 'turn_a', generation: 2, status: 'succeeded', stageSeq: 3 }, '7'), running)
})

test('account, generation and turn mismatches never enter the active state', () => {
  const start = progress.createChatProgress({ scope: '7', turnId: 'turn_a', generation: 2 })
  const reply = { turnId: 'turn_a', generation: 2, status: 'succeeded', stage: 'succeeded', stageSeq: 9 }
  assert.equal(progress.mergeChatProgress(start, reply, '8'), start)
  assert.equal(progress.mergeChatProgress(start, { ...reply, generation: 1 }, '7'), start)
  assert.equal(progress.mergeChatProgress(start, { ...reply, turnId: 'turn_b' }, '7'), start)
})

test('unknown stages do not invent progress and confirmed terminals cannot reopen', () => {
  const start = progress.createChatProgress({ scope: '7', turnId: 'turn_a' })
  const unknown = progress.mergeChatProgress(start, { turnId: 'turn_a', status: 'running', stage: 'thinking', stageSeq: 1 }, '7')
  assert.equal(unknown.stage, '')
  const done = progress.mergeChatProgress(unknown, { turnId: 'turn_a', status: 'succeeded', stageSeq: 2 }, '7')
  assert.equal(done.status, 'succeeded')
  assert.equal(progress.mergeChatProgress(done, { turnId: 'turn_a', status: 'running', stage: 'routing', stageSeq: 3 }, '7'), done)
})

test('legacy synchronous and status responses remain readable without invented stages', () => {
  const start = progress.createChatProgress({ scope: '7', turnId: 'old' })
  const legacy = progress.mergeChatProgress(start, { success: true, message: '回答', data: [] }, '7')
  assert.equal(legacy.status, 'succeeded')
  assert.equal(legacy.stage, '')
  assert.equal(progress.mergeChatProgress(start, { turnId: 'old', status: 'running' }, '7').status, 'running')
  assert.match(progress.chatProgressText(start), /生成/)
})

test('references require a separate server message ID and a card on that message', () => {
  const card = { card_type: 'achievement', id: 12 }
  const local = { id: 'm_99', role: 'assistant', payload: { cards: [card] } }
  assert.equal(progress.cardReference(local, card), null)
  const legacy = { ...local, serverMessageId: 99 }
  assert.equal(progress.cardReference(legacy, card), null)
  const durable = { ...legacy, serverTurnId: 'turn1', serverGeneration: 2 }
  assert.deepEqual(progress.cardReference(durable, card), { messageId: 99, cardType: 'achievement', cardId: 12 })
  assert.equal(progress.cardReference({ ...durable, role: 'user' }, card), null)
  assert.equal(progress.cardReference(durable, { ...card, id: 13 }), null)
})
