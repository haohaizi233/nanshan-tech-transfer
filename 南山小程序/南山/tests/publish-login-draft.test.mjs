import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')

test('guest publishing saves before validation and routes to login from the submit action', () => {
  const demand = read('../subpackages/tech-transfer/pages/post-demand/post-demand.vue')
  const achievement = read('../subpackages/tech-transfer/pages/post-result/post-result.vue')
  for (const source of [demand, achievement]) {
    assert.doesNotMatch(source, /onLoad\(\)\s*\{\s*if\s*\(\s*!ensureLoginForDock/)
    assert.match(source, /savePublishDraft/)
    assert.match(source, /restorePublishDraft/)
    assert.match(source, /saveDraftAndRequestLogin\(\)/)
    assert.match(source, /if\s*\(!isLoggedIn\(\)\)\s*\{\s*this\.saveDraftAndRequestLogin\(\)/)
    assert.match(source, /HostBridge\.navigate\('pages\/mine\/mine'\)/)
  }
  assert.ok(existsSync(new URL('../subpackages/tech-transfer/api/publish-draft.mjs', import.meta.url)))
})

test('guests can open publication preview and are only redirected on final confirmation', () => {
  const sources = [
    read('../subpackages/tech-transfer/pages/post-demand/post-demand.vue'),
    read('../subpackages/tech-transfer/pages/post-result/post-result.vue'),
  ]
  for (const source of sources) {
    const previewStart = source.indexOf('onPreview()')
    const previewEnd = source.indexOf('saveDraftAndRequestLogin()', previewStart)
    const submitStart = source.indexOf('async onSubmit()')
    const submitEnd = source.indexOf('this.previewing = false', submitStart)
    const preview = source.slice(previewStart, previewEnd)
    const submit = source.slice(submitStart, submitEnd)
    assert.ok(previewStart >= 0 && previewEnd > previewStart, 'onPreview should remain a distinct method')
    assert.ok(submitStart >= 0 && submitEnd > submitStart, 'onSubmit should remain a distinct method')
    assert.doesNotMatch(preview, /!isLoggedIn\(\)/)
    assert.match(preview, /previewing\s*=\s*true/)
    assert.match(submit, /!isLoggedIn\(\)/)
  }
})

test('publication validation leaves an inline reason instead of appearing to ignore the preview button', () => {
  const sources = [
    read('../subpackages/tech-transfer/pages/post-demand/post-demand.vue'),
    read('../subpackages/tech-transfer/pages/post-result/post-result.vue'),
  ]
  for (const source of sources) {
    assert.match(source, /v-if="previewError"/)
    assert.match(source, /previewError:\s*''/)
    assert.match(source, /this\.previewError\s*=/)
  }
})

test('drafts are deep-cloned and login plus profile completion resume the saved publishing route', () => {
  const draft = read('../subpackages/tech-transfer/api/publish-draft.mjs')
  const mine = read('../subpackages/tech-transfer/pages/mine/mine.vue')
  assert.match(draft, /JSON\.parse\(JSON\.stringify\(form \|\| \{\}\)\)/)
  assert.match(draft, /JSON\.parse\(JSON\.stringify\(value\.form\)\)/)
  assert.match(mine, /resumePublishDraftAfterLogin/)
  assert.match(mine, /if \(!res\.needProfile\) this\.resumePublishDraftAfterLogin\(\)/)
  assert.match(mine, /await this\.refresh\(\)\s*\n\s*this\.resumePublishDraftAfterLogin\(\)/)
})

test('demand publishing distinguishes image uploads while reusing the shared attachment field', () => {
  const demand = read('../subpackages/tech-transfer/pages/post-demand/post-demand.vue')
  assert.match(demand, /chooseDemandImage\(\)/)
  assert.match(demand, /uni\.chooseImage/)
  assert.match(demand, /role: 'image'/)
  assert.match(demand, /uploadContentFile\(path\)/)
})

test('demand attachment payload uses the file object id returned by upload', () => {
  const demand = read('../subpackages/tech-transfer/pages/post-demand/post-demand.vue')
  assert.match(demand, /fileId:\s*item\.fileId\s*\|\|\s*item\.id/)
  assert.match(demand, /:key="attachment\.fileId\s*\|\|\s*attachment\.id"/)
})

test('publish preview is constrained to the phone-width application surface on H5', () => {
  const preview = read('../subpackages/tech-transfer/components/publish-preview.vue')
  assert.match(preview, /max-width:\s*414px/)
  assert.match(preview, /virtualHost:\s*true/)
  assert.match(preview, /left:\s*0/)
  assert.match(preview, /top:\s*0/)
  assert.match(preview, /justify-content:\s*center/)
  assert.doesNotMatch(preview, /inset\s*:/)
})

test('publish preview keeps list rendering compatible with WeChat compiler', () => {
  const preview = read('../subpackages/tech-transfer/components/publish-preview.vue')
  assert.match(preview, /v-for="item in visibleItems"/)
  assert.doesNotMatch(preview, /v-for="item in items"[^>]*v-if="item\.value"/)
  assert.match(preview, /@tap="\$emit\('confirm'\)"/)
  assert.match(preview, /images:\s*\{\s*type:\s*Array/)
  assert.match(preview, /preview-thumb/)
})

test('demand publishing keeps budget and company introduction optional', () => {
  const demand = read('../subpackages/tech-transfer/pages/post-demand/post-demand.vue')
  assert.match(demand, /预算 <text class="optional">选填<\/text>/)
  assert.match(demand, /公司简介 <text class="optional">选填<\/text>/)
  assert.doesNotMatch(demand, /\{ key: 'budget'/)
})
