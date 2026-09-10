import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isValidEmail,
  isValidPhone,
  validateEmail,
  validatePhone,
} from './contactValidation.js'

test('admin contact validation matches the shared phone and email rules', () => {
  assert.equal(isValidPhone('13900000000'), true)
  assert.equal(isValidPhone('1390000000'), false)
  assert.equal(isValidEmail('admin@nanshan.cn'), true)
  assert.equal(isValidEmail('wqe'), false)
  assert.equal(validatePhone('', { required: true }).ok, false)
  assert.equal(validateEmail('wqe').ok, false)
})
