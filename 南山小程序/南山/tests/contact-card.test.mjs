import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { buildContactRows } from '../subpackages/tech-transfer/utils/contact-card.mjs'

test('buildContactRows returns empty array when all contact fields are empty or whitespace', () => {
  assert.deepEqual(buildContactRows(null), [])
  assert.deepEqual(buildContactRows(undefined), [])
  assert.deepEqual(buildContactRows({}), [])
  assert.deepEqual(buildContactRows({
    displayName: '   ',
    orgTitle: '',
    phone: null,
    email: undefined,
    wechat: '  \t ',
  }), [])
  assert.deepEqual(buildContactRows({
    contactName: '',
    contactTitle: ' ',
    contactPhone: '',
    contactEmail: '',
    contactWechat: '',
  }), [])
})

test('buildContactRows omits blank fields and formats name and title without dangling parentheses', () => {
  assert.deepEqual(
    buildContactRows({ displayName: '张老师', orgTitle: '教授', phone: '13800138000' }),
    [
      { key: 'contact', label: '联系人', value: '张老师（教授）', action: '' },
      { key: 'phone', label: '电话', value: '13800138000', action: 'call' },
    ],
  )
  assert.deepEqual(
    buildContactRows({ displayName: '张老师', orgTitle: '  ' }),
    [{ key: 'contact', label: '联系人', value: '张老师', action: '' }],
  )
  assert.deepEqual(
    buildContactRows({ displayName: '', orgTitle: '技术转移中心' }),
    [{ key: 'contact', label: '联系人', value: '技术转移中心', action: '' }],
  )
})

test('buildContactRows supports separateTitle and achievement-detail field names', () => {
  assert.deepEqual(
    buildContactRows(
      {
        contactName: '李工',
        contactTitle: '项目经理',
        contactPhone: '13900139000',
        contactEmail: 'li@example.com',
        contactWechat: 'wx_li',
      },
      { separateTitle: true },
    ),
    [
      { key: 'name', label: '联系人', value: '李工', action: '' },
      { key: 'title', label: '职务', value: '项目经理', action: '' },
      { key: 'phone', label: '电话', value: '13900139000', action: 'call' },
      { key: 'email', label: '邮箱', value: 'li@example.com', action: 'copy', copyLabel: '邮箱' },
      { key: 'wechat', label: '微信', value: 'wx_li', action: 'copy', copyLabel: '微信号' },
    ],
  )
})

test('buildContactRows includes counterpartName when non-empty', () => {
  assert.deepEqual(
    buildContactRows(
      { displayName: '', phone: '' },
      { counterpartName: '深圳某研究院' },
    ),
    [{ key: 'counterpart', label: '对接对象', value: '深圳某研究院', action: '' }],
  )
})

test('ContactCard hides entire section when rows is empty and is adopted by detail pages', () => {
  const component = readFileSync(
    new URL('../subpackages/tech-transfer/components/contact-card.vue', import.meta.url),
    'utf8',
  )
  const dock = readFileSync(
    new URL('../subpackages/tech-transfer/pages/dock-detail/dock-detail.vue', import.meta.url),
    'utf8',
  )
  const achievement = readFileSync(
    new URL('../subpackages/tech-transfer/pages/achievement-detail/achievement-detail.vue', import.meta.url),
    'utf8',
  )

  assert.match(component, /<view v-if="rows\.length"/)
  assert.match(dock, /<contact-card\b/)
  assert.match(achievement, /<contact-card\b/)
})
