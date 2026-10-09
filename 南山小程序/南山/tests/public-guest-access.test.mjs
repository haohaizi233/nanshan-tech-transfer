import assert from 'node:assert/strict'
import HostBridge from '../host/host-bridge.js'
import { getDemands } from '../subpackages/tech-transfer/api/demand.js'
import { getAchievements } from '../subpackages/tech-transfer/api/achievement.js'
import { searchAll } from '../subpackages/tech-transfer/api/search.js'
import { searchInstitutions } from '../subpackages/tech-transfer/api/membership.js'

const adapter = {
  _getEnvironment() {
    return { appEnv: 'staging', apiPrefix: '/api/tech-transfer/v1' }
  },
  _getIdentityCredential() {
    return { deviceId: 'guest-device' }
  },
  _request({ method, path, query }) {
    if (method === 'GET' && path === '/demands') {
      return { code: 0, data: { list: [{ id: 1, title: 'guest demand' }], total: 1, page: query.page ?? 1, pageSize: query.pageSize ?? 10 } }
    }
    if (method === 'GET' && path === '/achievements') {
      return { code: 0, data: { list: [{ id: 2, title: 'guest achievement' }], total: 1, page: query.page ?? 1, pageSize: query.pageSize ?? 10 } }
    }
    if (method === 'GET' && path === '/search') {
      return { code: 0, data: { achievements: { list: [] }, demands: { list: [] } } }
    }
    if (method === 'GET' && path === '/institutions') {
      return { code: 0, data: { list: [{ id: 3, name: 'guest org' }], total: 1, page: query.page ?? 1, pageSize: query.pageSize ?? 20 } }
    }
    return { code: 0, data: {} }
  },
  _upload() {},
  _navigate() {},
  _showMessage() {},
  _reportError() {},
  _getStorage() { return null },
  _setStorage() {},
}

HostBridge.registerAdapter(adapter)

try {
  const demands = await getDemands({ page: 1, pageSize: 1 })
  assert.equal(demands.list[0].title, 'guest demand')

  const achievements = await getAchievements({ page: 1, pageSize: 1 })
  assert.equal(achievements.list[0].title, 'guest achievement')

  const search = await searchAll('AI', 'all', 1, 10)
  assert.ok(search)

  const institutions = await searchInstitutions('AI', 1, 20)
  assert.equal(institutions.list[0].name, 'guest org')

  console.log('guest public access OK')
} catch (error) {
  console.error('guest public access FAILED')
  console.error(error)
  process.exit(1)
}
