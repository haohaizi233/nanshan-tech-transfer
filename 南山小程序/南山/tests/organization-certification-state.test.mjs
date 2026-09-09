import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeOrganizationCertification } from '../subpackages/tech-transfer/api/organization-certification-state.mjs'

test('机构管理员认证状态优先于普通成员并关闭申请入口', () => {
  const state = normalizeOrganizationCertification({
    memberships: [
      { id: 10, orgId: 8, orgName: '南山科技园', role: 'member', status: 'active' },
      { id: 11, orgId: 9, orgName: '南山产业集团', role: 'admin', status: 'active' },
    ],
  })

  assert.equal(state.status, 'certified_admin')
  assert.equal(state.label, '机构管理员')
  assert.equal(state.canApply, false)
  assert.equal(state.primaryMembership.orgName, '南山产业集团')
})

test('普通认证成员状态回显成员身份并关闭申请入口', () => {
  const state = normalizeOrganizationCertification({
    memberships: [
      { id: 12, orgId: 10, orgName: '南山大学', role: 'member', status: 'active' },
    ],
  })

  assert.equal(state.status, 'certified_member')
  assert.equal(state.label, '已认证成员')
  assert.equal(state.canApply, false)
  assert.equal(state.primaryMembership.orgName, '南山大学')
})

test('待审核成员申请回显机构并关闭重复申请入口', () => {
  const state = normalizeOrganizationCertification({
    memberships: [],
    membershipApplication: { id: 21, orgId: 11, orgName: '南山实验室', status: 'pending' },
  })

  assert.equal(state.status, 'membership_pending')
  assert.equal(state.label, '加入机构审核中')
  assert.equal(state.canApply, false)
  assert.equal(state.pendingName, '南山实验室')
})
