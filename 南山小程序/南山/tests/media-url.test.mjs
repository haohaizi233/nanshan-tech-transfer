import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isImageMedia,
  mediaDisplayUrl,
  resolveMediaUrl,
  splitDemandAttachments,
  withMediaAccessToken,
} from '../subpackages/tech-transfer/api/media-url.mjs'
import { resolveServiceOrigin } from '../subpackages/tech-transfer/api/api-origin.js'

test('relative file paths become absolute URLs for WeChat image tags', () => {
  const env = { hostMode: 'ainanshan', apiBase: 'https://api.example.com' }
  assert.equal(
    resolveMediaUrl('/api/tech-transfer/v1/files/12', env),
    'https://api.example.com/api/tech-transfer/v1/files/12',
  )
  assert.equal(resolveMediaUrl('wxfile://tmp/a.png', env), 'wxfile://tmp/a.png')
  assert.equal(resolveMediaUrl('https://cdn.example.com/a.png', env), 'https://cdn.example.com/a.png')
})

test('local host mode still follows the H5 tunnel origin rule', () => {
  assert.equal(
    resolveServiceOrigin(
      { appEnv: 'local', hostMode: 'local', apiBase: 'http://127.0.0.1:8787' },
      { protocol: 'http:', hostname: '192.168.1.8', port: '8077' },
    ),
    'http://192.168.1.8:8076',
  )
})

test('display URL prefers the local temp path and appends access_token for remote files', () => {
  const env = { hostMode: 'ainanshan', apiBase: 'https://api.example.com' }
  assert.equal(
    mediaDisplayUrl({ localPath: 'wxfile://tmp/a.png', url: '/api/tech-transfer/v1/files/1' }, env, 'tok'),
    'wxfile://tmp/a.png',
  )
  assert.equal(
    withMediaAccessToken('https://api.example.com/api/tech-transfer/v1/files/1', 'tok'),
    'https://api.example.com/api/tech-transfer/v1/files/1?access_token=tok',
  )
})

test('demand attachments split images from downloadable files', () => {
  const split = splitDemandAttachments([
    { fileId: 1, role: 'image', name: 'a.png' },
    { fileId: 2, role: 'attachment', name: 'spec.pdf', mimeType: 'application/pdf' },
    { fileId: 3, role: 'attachment', name: 'photo.jpg' },
  ])
  assert.deepEqual(split.images.map((item) => item.fileId), [1, 3])
  assert.deepEqual(split.files.map((item) => item.fileId), [2])
  assert.equal(isImageMedia({ mimeType: 'image/jpeg' }), true)
})
