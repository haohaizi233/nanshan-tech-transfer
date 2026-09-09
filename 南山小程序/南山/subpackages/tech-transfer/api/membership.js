/**
 * 机构认证 / 组织成员 API
 *
 * 认证机构（organization_membership）是正式归属，仅由后端审核建立；
 * 自填单位（companyText）仅为展示文本，不代表认证。
 */

import { apiRequest, setCurrentUser } from './client.js'
import { normalizeOrganizationCertification } from './organization-certification-state.mjs'

/** 拉取最新 /me 并刷新本地缓存（登录后机构状态变化时调用） */
export async function fetchCurrentUser() {
  const user = await apiRequest('GET', '/me', null, null)
  setCurrentUser(user)
  return user
}

/** 我的有效机构身份（含 orgId/orgName/role/status/version） */
export function getMembershipsFromUser(user) {
  const list = (user && user.organizationMemberships) || []
  return Array.isArray(list) ? list : []
}

/** 当前账号的实时机构认证状态；不依赖资料缓存。 */
export async function getMyOrganizationCertification() {
  const payload = await apiRequest('GET', '/me/organization-certification', null, null)
  return normalizeOrganizationCertification(payload)
}

/** 搜索 canonical 机构（仅 active，复用公开机构目录接口） */
export async function searchInstitutions(keyword, page, pageSize) {
  return apiRequest('GET', '/institutions', {
    keyword: keyword || '',
    page: page || 1,
    pageSize: pageSize || 20
  }, null)
}

/** 我发起的成员申请列表 */
export async function getMyMembershipApplications() {
  return apiRequest('GET', '/me/organization-membership-applications', null, null)
}

/** 申请加入已有机构（必须携带后端返回的 orgId，禁止用名称绑定） */
export async function applyMembership(body) {
  return apiRequest('POST', '/me/organization-membership-applications', null, body)
}

/** 取消我的待审核成员申请 */
export async function cancelMembershipApplication(applicationId, version) {
  return apiRequest('POST', `/me/organization-membership-applications/${applicationId}/cancel`, null, { version })
}

/** 申请成为机构管理员 */
export async function applyOrgAdmin(body) {
  return apiRequest('POST', '/me/organization-admin-applications', null, body)
}

/** 提交新机构入驻申请 */
export async function applyOrganization(body) {
  return apiRequest('POST', '/me/organization-applications', null, body)
}

/** 机构管理：本机构成员列表（仅机构管理员/系统管理员） */
export async function getOrgMembers(orgId, params) {
  return apiRequest('GET', '/org-admin/members', Object.assign({ orgId }, params || {}), null)
}

/** 机构管理：本机构成员申请审核队列 */
export async function getOrgMembershipApplications(orgId, params) {
  return apiRequest('GET', '/org-admin/membership-applications', Object.assign({ orgId }, params || {}), null)
}

/** 机构管理：通过成员申请 */
export async function approveMembershipApplication(applicationId, version) {
  return apiRequest('POST', `/org-admin/membership-applications/${applicationId}/approve`, null, { version })
}

/** 机构管理：驳回成员申请（必须填原因） */
export async function rejectMembershipApplication(applicationId, version, reason) {
  return apiRequest('POST', `/org-admin/membership-applications/${applicationId}/reject`, null, { version, reason })
}

/** 机构管理：撤销普通成员（必须填原因） */
export async function revokeOrgMember(membershipId, version, reason) {
  return apiRequest('POST', `/org-admin/members/${membershipId}/revoke`, null, { version, reason })
}
