import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeCooperationCapacity } from '../subpackages/tech-transfer/utils/cooperation-capacity.mjs'

test('capacity bounds keep finite counts and normalize oversized counts to unlimited', () => {
  for (const value of ['', null, '10000', '9'.repeat(5000), 1e100]) assert.equal(normalizeCooperationCapacity(value), null)
  for (const value of [1, 9999, '9999']) assert.equal(normalizeCooperationCapacity(value), Number(value))
  for (const value of ['abc', 0, -1, '1.5']) assert.throws(() => normalizeCooperationCapacity(value))
})
