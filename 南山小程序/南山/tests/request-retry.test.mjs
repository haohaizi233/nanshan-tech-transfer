import assert from 'node:assert/strict'
import test from 'node:test'

import { retryRequest } from '../common/request-retry.js'

test('returns the first successful request result without delaying', async () => {
  let delays = 0

  const result = await retryRequest(async () => ({ total: 5 }), {
    sleep: async () => { delays += 1 },
  })

  assert.deepEqual(result, { total: 5 })
  assert.equal(delays, 0)
})

test('retries a transient request failure with increasing short delays', async () => {
  let attempts = 0
  const delays = []

  const result = await retryRequest(async () => {
    attempts += 1
    if (attempts < 3) throw new Error('502 Bad Gateway')
    return 'loaded'
  }, {
    sleep: async (ms) => { delays.push(ms) },
  })

  assert.equal(result, 'loaded')
  assert.equal(attempts, 3)
  assert.deepEqual(delays, [300, 600])
})

test('returns the final failure after the retry limit is exhausted', async () => {
  let attempts = 0
  const failure = new Error('tunnel unavailable')

  await assert.rejects(
    retryRequest(async () => {
      attempts += 1
      throw failure
    }, { sleep: async () => {} }),
    failure,
  )
  assert.equal(attempts, 3)
})
