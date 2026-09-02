/**
 * MockIdentityProvider —— 本地开发身份
 * 仅在 local/development/testing 环境使用
 * 正式环境由 AiNanshanIdentityProvider 替代
 */

const MOCK_ISSUER = 'local-dev'
const MOCK_SUBJECT = 'dev-user-001'
const MOCK_DISPLAY_NAME = '本地测试用户'
const MOCK_TICKET_PREFIX = 'local-dev-ticket-'

export function generateMockTicket(subject) {
  const sub = subject || MOCK_SUBJECT
  return MOCK_TICKET_PREFIX + sub
}

export function getMockIdentity() {
  return {
    issuer: MOCK_ISSUER,
    tenantId: 'default',
    externalSubject: MOCK_SUBJECT,
    displayName: MOCK_DISPLAY_NAME,
  }
}

export function getMockTicket() {
  return generateMockTicket(MOCK_SUBJECT)
}
