import assert from 'node:assert/strict'
import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const subpackageDir = fileURLToPath(new URL('../subpackages/tech-transfer/', import.meta.url))

function directorySize(directory) {
  return readdirSync(directory, { withFileTypes: true }).reduce((total, entry) => {
    const path = join(directory, entry.name)
    return entry.isDirectory() ? total + directorySize(path) : total + statSync(path).size
  }, 0)
}

test('keeps the tech-transfer subpackage within the WeChat 2MB per-subpackage limit', () => {
  assert.ok(directorySize(subpackageDir) <= 2_000_000)
})
