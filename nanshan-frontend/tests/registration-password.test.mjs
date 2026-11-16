import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
const source = readFileSync(new URL('../src/views/auth/RegisterView.vue', import.meta.url), 'utf8')
const validation = source.slice(source.indexOf('const validatePassword ='), source.indexOf('const submitUserRegistration ='))
const validate = vm.runInNewContext(validation + '; validatePassword')
for (const length of [6, 7, 129]) {
  test(`registration rejects ${length} characters`, () => {
    const password = 'a'.repeat(length)
    assert.ok(validate({ username: 'test', password, confirmPassword: password }))
  })
}
for (const length of [8, 128]) {
  test(`registration accepts ${length} characters`, () => {
    const password = 'a'.repeat(length)
    assert.equal(validate({ username: 'test', password, confirmPassword: password }), '')
  })
}
