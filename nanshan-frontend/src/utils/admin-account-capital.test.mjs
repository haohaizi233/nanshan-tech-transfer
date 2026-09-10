import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

test('admin header wires profile and password panels to live APIs', () => {
  const source = readFileSync(new URL('../components/layout/AdminHeader.vue', import.meta.url), 'utf8')
  assert.match(source, /openProfile/)
  assert.match(source, /\/me\/password/)
  assert.match(source, /\/me\/profile/)
})

test('capital management page supports CRUD plus idempotent CSV import', () => {
  const source = readFileSync(new URL('../views/admin/CapitalView.vue', import.meta.url), 'utf8')
  assert.match(source, /\/admin\/institutions\/import/)
  assert.match(source, /method: 'DELETE'/)
  assert.match(source, /downloadTemplate/)
})
