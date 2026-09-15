import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../index.html', import.meta.url), 'utf8')

test('keeps the H5 application in a centered portrait shell on desktop widths', () => {
  assert.match(source, /@media screen and \(min-width: 500px\)/)
  assert.match(source, /#app\s*\{[\s\S]*max-width:\s*414px/)
  assert.match(source, /#app\s*\{[\s\S]*margin:\s*0 auto/)
})
