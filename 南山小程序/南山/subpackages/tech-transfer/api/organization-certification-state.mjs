/** Normalize the API response into one UI state shared by certification pages. */
export function normalizeOrganizationCertification(payload = {}) {
  const memberships = Array.isArray(payload.memberships) ? payload.memberships : []
  const activeMemberships = memberships.filter((item) => item && item.status === 'active')
  const primaryMembership = activeMemberships.find((item) => item.role === 'admin') || activeMemberships[0] || null

  if (primaryMembership) {
    const isAdmin = primaryMembership.role === 'admin'
    return {
      status: isAdmin ? 'certified_admin' : 'certified_member',
      label: isAdmin ? '机构管理员' : '已认证成员',
      canApply: false,
      memberships: activeMemberships,
      primaryMembership,
      pendingName: '',
    }
  }

  const membershipApplication = payload.membershipApplication
  if (membershipApplication && membershipApplication.status === 'pending') {
    return {
      status: 'membership_pending',
      label: '加入机构审核中',
      canApply: false,
      memberships: [],
      primaryMembership: null,
      pendingName: membershipApplication.orgName || '',
    }
  }

  const organizationApplication = payload.organizationApplication
  if (organizationApplication && organizationApplication.status === 'pending') {
    return {
      status: 'organization_pending',
      label: '机构入驻审核中',
      canApply: false,
      memberships: [],
      primaryMembership: null,
      pendingName: organizationApplication.requestedName || '',
    }
  }

  return {
    status: 'unverified',
    label: '未认证',
    canApply: true,
    memberships: [],
    primaryMembership: null,
    pendingName: '',
  }
}
