/**
 * 构建期环境硬校验
 * staging/production 环境违规组合直接抛错
 */

import { APP_ENV, HOST_MODE, AUTH_PROVIDER, API_BASE } from './local.env.js'

const PRODUCTION_ENVS = ['staging', 'production']
const BANNED = {
  HOST_MODE: 'local',
  AUTH_PROVIDER: 'mock',
  API_BASE: '127.0.0.1',
}

export function assertEnvironment() {
  if (!PRODUCTION_ENVS.includes(APP_ENV)) {
    return
  }
  const violations = []
  if (HOST_MODE === BANNED.HOST_MODE) violations.push(`HOST_MODE=${BANNED.HOST_MODE}`)
  if (AUTH_PROVIDER === BANNED.AUTH_PROVIDER) violations.push(`AUTH_PROVIDER=${BANNED.AUTH_PROVIDER}`)
  if (API_BASE && API_BASE.includes(BANNED.API_BASE)) violations.push(`API_BASE contains ${BANNED.API_BASE}`)
  if (violations.length > 0) {
    throw new Error(
      `[FATAL] 环境保护断言失败：${violations.join(', ')} 不允许在 ${APP_ENV} 环境启动`
    )
  }
}
