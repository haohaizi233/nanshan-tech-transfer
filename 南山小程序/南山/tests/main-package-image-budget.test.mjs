import assert from 'node:assert/strict'
import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const staticDir = fileURLToPath(new URL('../static/', import.meta.url))

function imageSize(directory) {
  return readdirSync(directory, { withFileTypes: true }).reduce((total, entry) => {
    const path = join(directory, entry.name)
    return entry.isDirectory() ? total + imageSize(path) : total + statSync(path).size
  }, 0)
}

test('keeps source image resources within the main-package budget', () => {
  assert.ok(imageSize(staticDir) <= 1_600_000)
})
