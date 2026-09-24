import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('achievement import staging keeps separate scroll panes and a single-column media preview', () => {
  const router = read('../router/index.js')
  const page = read('../views/admin/AchievementImportView.vue')
  assert.match(router, /AchievementImportView/)
  assert.match(router, /path:\s*'achievement-imports'/)
  assert.match(page, /\/admin\/achievement-imports/)
  assert.match(page, /items\/\$\{item\.id\}\/publish/)
  assert.match(page, /一键发布成果/)
  assert.match(page, /选择文件/)
  assert.match(page, /导入文件夹/)
  assert.match(page, /confirmAndRunAchievementImport/)
  assert.match(page, /snapshotFileList/)
  assert.match(page, /showDirectoryPicker/)
  assert.match(page, /webkitdirectory/)
  assert.match(page, /IMPORT_ACCEPT/)
  assert.match(page, /来源机构（可选）/)
  assert.match(page, /fileInput\.value\?\.click\(\)/)
  assert.match(page, /activeRaw\.value\.images/)
  assert.match(page, /loadCandidateImage/)
  assert.match(page, /candidateImageUrls\.value\[fileId\]\s*=/)
  assert.match(page, /v-if="img\.url"/)
  assert.match(page, /watch\(activeItem/)
  assert.doesNotMatch(page, /candidateImageUrls\.value\s*=\s*\{[\s\S]*\.\.\.candidateImageUrls\.value/)
  assert.match(page, /\.batches\s*\{[^}]*overflow-y:\s*auto/)
  assert.match(page, /\.phone-preview\s*\{[^}]*overflow-y:\s*auto/)
  assert.match(page, /height:\s*calc\(100vh - 190px\)/)
  assert.match(page, /@media \(max-width: 900px\)[\s\S]*grid-template-rows/)
  assert.match(page, /@media \(max-width: 900px\)[\s\S]*\.phone-preview\s*\{[^}]*overflow-y:\s*auto/)
  assert.match(page, /\.mp-image-grid\s*\{[^}]*grid-template-columns:\s*1fr/)
})

test('admin client posts achievement import files as multipart instead of JSON', () => {
  const client = read('../api/client.js')
  assert.match(client, /body instanceof FormData/)
  assert.match(client, /isForm \? body : JSON\.stringify\(body\)/)
})

test('achievement list page exposes file and folder import actions for platform admins', () => {
  const page = read('../views/admin/AchievementView.vue')
  assert.match(page, /选择文件/)
  assert.match(page, /导入文件夹/)
  assert.match(page, /confirmAndRunAchievementImport/)
  assert.match(page, /snapshotFileList/)
  assert.match(page, /showDirectoryPicker/)
  assert.match(page, /webkitdirectory/)
  assert.match(page, /v-if="isPlatformAdmin"/)
})

test('import helper keeps pptx/pdf from a folder and skips other files', () => {
  const helper = read('./importAchievementDocuments.js')
  assert.match(helper, /form\.append\('files', file\)/)
  assert.match(helper, /旧版 \.ppt/)
  assert.match(helper, /sourceOrg/)
  assert.match(helper, /pickAchievementImportFiles/)
  assert.match(helper, /webkitRelativePath/)
  assert.match(helper, /export async function runAchievementImport/)
  assert.match(helper, /snapshotFileList/)
  assert.match(helper, /confirmAndRunAchievementImport/)
})

test('folder file lists keep pptx/pdf and skip ppt/other files', async () => {
  const { pickAchievementImportFiles, snapshotFileList, describeImportSelection } = await import('./importAchievementDocuments.js')
  const picked = pickAchievementImportFiles([
    new File([new Uint8Array([1])], '成果.pptx'),
    new File([new Uint8Array([1])], '旧稿.ppt'),
    new File([new Uint8Array([1])], '说明.txt'),
    new File([new Uint8Array([1])], '简介.pdf'),
  ])
  assert.deepEqual(picked.files.map(file => file.name), ['成果.pptx', '简介.pdf'])
  assert.equal(picked.skippedPpt.length, 1)
  assert.equal(picked.skippedOther.length, 1)
  assert.match(describeImportSelection(picked.files.concat(
    new File([new Uint8Array([1])], '旧稿.ppt'),
    new File([new Uint8Array([1])], '说明.txt'),
  )).message, /将导入 2 个 PPTX\/PDF/)
  const live = { length: 1, 0: new File([new Uint8Array([1])], 'a.pptx') }
  const copied = snapshotFileList(live)
  live.length = 0
  assert.equal(copied.length, 1)
})
