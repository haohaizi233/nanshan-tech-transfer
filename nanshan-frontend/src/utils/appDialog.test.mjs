import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'

import {
  alertDialog,
  cancelDialog,
  confirmDialog,
  dialogState,
  promptDialog,
  submitDialog,
} from './appDialog.js'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')

function walk(dir, files = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, files)
    else files.push(full)
  }
  return files
}

test('admin views no longer call native browser dialogs', () => {
  const files = walk(srcRoot).filter((file) => (
    (file.endsWith('.vue') || file.endsWith('.js'))
    && !file.endsWith('appDialog.js')
    && !file.endsWith('appDialog.test.mjs')
  ))
  assert.ok(files.length > 0)
  for (const file of files) {
    const source = readFileSync(file, 'utf8')
    assert.doesNotMatch(source, /window\.(confirm|alert|prompt)\s*\(/, file)
  }
})

test('confirm / alert / prompt resolve through the shared dialog', async () => {
  const confirmed = confirmDialog({ message: '下架机构' })
  assert.equal(dialogState.visible, true)
  assert.equal(dialogState.type, 'confirm')
  submitDialog()
  assert.equal(await confirmed, true)
  assert.equal(dialogState.visible, false)

  const cancelled = confirmDialog({ message: '取消' })
  cancelDialog()
  assert.equal(await cancelled, false)

  const alerted = alertDialog({ message: '导出失败' })
  submitDialog()
  assert.equal(await alerted, undefined)

  const prompted = promptDialog({ message: '请填写原因', placeholder: '请填写撤销原因' })
  dialogState.inputValue = '  不再担任  '
  submitDialog()
  assert.equal(await prompted, '不再担任')

  const emptyPrompt = promptDialog({ message: '必填' })
  submitDialog()
  assert.equal(dialogState.visible, true)
  assert.equal(dialogState.error, '请填写后再确定')
  cancelDialog()
  assert.equal(await emptyPrompt, null)
})
