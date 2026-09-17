import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

test('notification poller stays in the main package and only refreshes the summary', () => {
  const source = readFileSync(new URL('../utils/notification-poller.js', import.meta.url), 'utf8')
  const app = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
  assert.match(source, /getNotificationSummary/)
  assert.doesNotMatch(source, /subpackages\/tech-transfer/)
  assert.match(source, /HostBridge\.request/)
  assert.match(source, /setInterval\(refreshNotificationBadge, 5000\)/)
  assert.match(source, /inFlight/)
  assert.match(source, /99\+/)
  assert.match(app, /startNotificationPolling\(\)/)
  assert.match(app, /stopNotificationPolling\(\)/)
})

test('main-package notification polling leaves no orphan subpackage API module', () => {
  assert.equal(existsSync(new URL('../subpackages/tech-transfer/api/notifications.js', import.meta.url)), false)
})

test('notification polling is not started for a visitor session and stops after 401', () => {
  const source = readFileSync(new URL('../utils/notification-poller.js', import.meta.url), 'utf8')
  assert.match(source, /function hasNotificationSession\(\)/)
  assert.match(source, /if \(!hasNotificationSession\(\)\)\s*\{[\s\S]*?return/)
  assert.match(source, /if \(isUnauthorized\(e\)\)\s*\{[\s\S]*?clearNotificationSession\(\)/)
})

test('root host redirects to the business home during load instead of rendering an empty page', () => {
  const source = readFileSync(new URL('../pages/dev-home/dev-home.vue', import.meta.url), 'utf8')
  assert.match(source, /onLoad\(\)\s*\{[\s\S]*?uni\.reLaunch/)
  assert.match(source, /v-else class="dev-redirecting"/)
})
