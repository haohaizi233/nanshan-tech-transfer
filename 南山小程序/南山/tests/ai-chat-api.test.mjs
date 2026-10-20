import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

test('chat sends the async preference and explicit reference through the shared client', async () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/api/ai.js', import.meta.url), 'utf8')
  const script = source.replace(/^import .*$/gm, '').replace(/export /g, '')
  let sent
  const chat = new Function('apiRequest', 'AI_FEATURE_ENABLED', script + '; return chatWithAgent')(
    async (...args) => { sent = args; return { status: 'running' } }, true,
  )
  const reference = { messageId: 31, cardType: 'achievement', cardId: 8 }
  await chat('介绍这项', 'turn1', reference)
  assert.deepEqual(sent[3], { message: '介绍这项', turnId: 'turn1', reference })
  assert.equal(sent[4].headers.Prefer, 'respond-async')
})

test('shared client forwards optional headers and keeps its idempotency key', async () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/api/client.js', import.meta.url), 'utf8')
  const script = source.slice(source.indexOf('export async function apiRequest'), source.indexOf('export async function publicRequest')).replace('export ', '')
  let sent
  const request = new Function('ensureSession', 'HostBridge', script + '; return apiRequest')(
    async () => {}, { request: async options => { sent = options; return { code: 0, data: {} } } },
  )
  await request('POST', '/ai/chat', null, {}, { headers: { Prefer: 'respond-async' } })
  assert.equal(sent.headers.Prefer, 'respond-async')
  assert.match(sent.headers['X-Idempotency-Key'], /^tt_/)
})
