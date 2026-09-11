import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isValidContactWay,
  isValidEmail,
  isValidPhone,
  validateContactWay,
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

test('institution contact way accepts crawled landlines as well as mobiles', () => {
  assert.equal(isValidContactWay('13900000000'), true)
  assert.equal(isValidContactWay('88015909'), true)
  assert.equal(isValidContactWay('0755-88015909'), true)
  assert.equal(isValidContactWay('abc'), false)
  assert.equal(validateContactWay('', { required: false }).ok, true)
  assert.equal(validateContactWay('nope').ok, false)
})
