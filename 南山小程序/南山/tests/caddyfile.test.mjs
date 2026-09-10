import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../')
const caddyfile = fs.readFileSync(path.join(repoRoot, 'deploy', 'Caddyfile'), 'utf8')
const caddyfileH5 = fs.readFileSync(path.join(repoRoot, 'deploy', 'Caddyfile.h5'), 'utf8')
const snippets = fs.readFileSync(path.join(repoRoot, 'deploy', 'nanshan.caddy'), 'utf8')
const tlsAcme = fs.readFileSync(path.join(repoRoot, 'deploy', 'tls-acme.caddy'), 'utf8')
const tlsLocal = fs.readFileSync(path.join(repoRoot, 'deploy', 'tls-local.caddy'), 'utf8')

test('unified Caddyfile splits /api, /h5, and the admin SPA on the same host', () => {
  assert.match(caddyfile, /import nanshan\.caddy/)
  assert.match(caddyfile, /handle \/health/)
  assert.match(caddyfile, /handle \/api\/\*/)
  assert.match(caddyfile, /handle \/h5\/\*/)
  assert.match(caddyfile, /import nanshan_api/)
  assert.match(caddyfile, /import nanshan_h5/)
  assert.match(caddyfile, /inanshan\.centips\.com/)
  assert.match(caddyfile, /https:\/\/\{\$NS_SITE/)
  assert.match(caddyfile, /NS_TLS_SNIPPET/)
  assert.match(caddyfile, /tls-acme\.caddy/)
  assert.doesNotMatch(caddyfile, /http:\/\/\{\$NS_SITE/)
  assert.match(snippets, /127\.0\.0\.1:8025/)
  assert.match(snippets, /127\.0\.0\.1:5173/)
  assert.match(snippets, /header_up X-Request-Id/)
  assert.match(snippets, /header_up X-Idempotency-Key/)
  assert.match(tlsAcme, /disable_http_challenge/)
  assert.match(tlsLocal, /tls internal/)
})

test('legacy Caddyfile.h5 reuses the unified Caddyfile', () => {
  assert.match(caddyfileH5, /import Caddyfile/)
})
