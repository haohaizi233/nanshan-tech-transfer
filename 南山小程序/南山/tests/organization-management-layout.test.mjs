import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const mine = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
const manage = readFileSync(new URL('../subpackages/tech-transfer/pages/org-manage/org-manage.vue', import.meta.url), 'utf8')

test('places the certification badge on the organization-certification title row', () => {
  assert.match(mine, /class="org-card-heading">\s*<text class="org-card-title">机构认证<\/text>\s*<text class="org-role admin"/)
  assert.match(mine, /\.org-card-heading\s*\{[\s\S]*justify-content:\s*space-between/)
})

test('keeps application approve and reject actions on one row', () => {
  assert.match(manage, /\.action-row\s*\{[\s\S]*flex-direction:\s*row/)
  assert.match(manage, /\.action-row\s+\.mini-btn\s*\{[\s\S]*margin:/)
})

test('keeps the revoke dialog as a centered card instead of a full-width overlay', () => {
  assert.match(manage, /\.dialog-panel\s*\{[\s\S]*?width:\s*560rpx/)
  assert.match(manage, /left:\s*var\(--window-left,\s*0px\)/)
  assert.match(manage, /right:\s*var\(--window-right,\s*0px\)/)
})

import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const Vue = require('vue')
const { compile } = require('@vue/compiler-dom')
const { renderToString } = require('@vue/server-renderer')
const template = manage.match(/<template>([\s\S]*?)<\/template>/)[1]
const render = new Function('Vue', compile(template, { mode: 'function', prefixIdentifiers: true }).code)(Vue)
function component(api = {}) {
  const script = manage.match(/<script>([\s\S]*?)<\/script>/)[1]
    .replace(/import[\s\S]*?from\s+['"][^'"]+['"]/g, '')
    .replace('export default', 'return')
  return new Function('createPageStateMixin', 'getOrgMembers', 'getOrgMembershipApplications', script)(() => ({}), api.members, api.applications)
}
async function html(members, applications = [], tab = 'members') {
  const options = component()
  return renderToString(Vue.createSSRApp({
    ...options, render,
    data: () => ({ ...options.data(), loadingOrgs: false, adminOrgs: [{ orgId: 10, orgName: '机构' }], currentOrgId: 10, members, applications, tab })
  }))
}
test('renders name, number, role, department and title together', async () => {
  const output = await html([{ id: 1, realName: '李明', userNo: 'U123', role: 'member', department: '研发部', title: '经理' }])
  for (const text of ['李明', '工号：U123', '成员', '研发部', '经理', '撤销']) assert.ok(output.includes(text), text)
})
test('missing name retains number and admin role without revoke', async () => {
  const output = await html([{ id: 1, realName: null, userNo: 'U456', role: 'admin' }])
  for (const text of ['未填写姓名', '工号：U456', '管理员']) assert.ok(output.includes(text), text)
  assert.ok(!output.includes('>撤销<'))
})
test('application renders both submitted name and number', async () => {
  const output = await html([], [{ id: 2, realName: '王明', userNo: 'U789' }], 'applications')
  for (const text of ['王明', '工号：U789', '通过', '驳回']) assert.ok(output.includes(text), text)
})
test('old organization response cannot replace current organization names', async () => {
  const pending = []
  const options = component({ members: () => new Promise(resolve => pending.push(resolve)) })
  const vm = { ...options.data(), ...options.methods, currentOrgId: 10, invalidatePageState() {}, markPageStateFresh() {} }
  const first = vm.loadList()
  vm.switchOrg(20)
  assert.deepEqual(vm.members, [])
  pending[1]({ list: [{ realName: '当前机构' }] })
  await new Promise(resolve => setImmediate(resolve))
  pending[0]({ list: [{ realName: '旧机构' }] })
  await first
  assert.equal(vm.members[0].realName, '当前机构')
  assert.equal(vm.loadingList, false)
})
test('revoke keeps membership relation ID and optimistic version', () => {
  const options = component()
  const vm = { ...options.data(), ...options.methods }
  vm.openRevoke({ id: 91, userId: 1234, version: 7 })
  assert.deepEqual(vm.dialogAction, { type: 'revoke', id: 91, version: 7 })
})
