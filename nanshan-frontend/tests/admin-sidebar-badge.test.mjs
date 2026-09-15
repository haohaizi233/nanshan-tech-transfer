import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

test('sidebar notification badge is a compact circular counter aligned to the right', () => {
  const source = readFileSync(new URL('../src/components/layout/AdminSidebar.vue', import.meta.url), 'utf8')
  assert.match(source, /\.menu-badge\s*\{/)
  assert.match(source, /\.menu-badge[\s\S]*?margin-left:\s*auto/)
  assert.match(source, /\.menu-badge[\s\S]*?min-width:\s*18px/)
  assert.match(source, /\.menu-badge[\s\S]*?border-radius:\s*999px/)
})
