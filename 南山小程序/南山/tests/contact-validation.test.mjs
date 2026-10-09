import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isValidEmail,
  isValidPhone,
  validateEmail,
  validatePhone,
} from '../subpackages/tech-transfer/api/contact-validation.mjs'

test('accepts 11-digit phones and rejects malformed numbers', () => {
  assert.equal(isValidPhone('13800138000'), true)
  assert.equal(isValidPhone('12345678902'), true)
  assert.equal(isValidPhone('1380013800'), false)
  assert.equal(validatePhone('', { required: true }).ok, false)
  assert.equal(validatePhone('', { required: false }).ok, true)
})

test('accepts standard emails and rejects incomplete values', () => {
  assert.equal(isValidEmail('user@example.com'), true)
  assert.equal(isValidEmail('wqe'), false)
  assert.equal(validateEmail('wqe', { required: true }).message, '邮箱格式不正确')
  assert.equal(validateEmail('', { required: false }).ok, true)
})
