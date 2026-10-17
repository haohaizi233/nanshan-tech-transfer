<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { api, getToken } from '../../api/client'
import {
  alertDialog,
  closeProgressDialog,
  confirmDialog,
  openProgressDialog,
  updateProgressDialog,
} from '../../utils/appDialog.js'
import {
  IMPORT_ACCEPT,
  confirmAndRunAchievementImport,
  readDirectoryFiles,
  snapshotFileList,
  summarizeAchievementImport,
} from '../../utils/importAchievementDocuments.js'

const batches = ref([])
const loading = ref(false)
const loadError = ref('')
const selectedBatch = ref(null)
const detailLoading = ref(false)
const publishingId = ref(null)
const clearing = ref(false)
const candidateImageUrls = ref({})
const candidateImageErrors = ref({})
const inflightImageIds = new Set()
const lightboxIndex = ref(-1)
const activeItemIndex = ref(0)
const importing = ref(false)
const importProgress = ref('')
const sourceOrg = ref('')
const fileInput = ref(null)
const folderInput = ref(null)

const formatTime = value => value ? String(value).replace('T', ' ').slice(0, 16) : '—'

const items = computed(() => selectedBatch.value?.items || [])

const activeItem = computed(() => {
  const list = items.value
  if (!list.length) return null
  return list[Math.min(activeItemIndex.value, list.length - 1)]
})

const activeNormalized = computed(() => activeItem.value?.normalized || {})
const activeRaw = computed(() => activeItem.value?.raw || {})

const previewImages = computed(() => {
  const images = activeRaw.value.images || []
  return images.map(img => ({
    fileId: img.fileId,
    filename: img.filename,
    url: candidateImageUrls.value[Number(img.fileId)] || candidateImageUrls.value[img.fileId] || '',
    failed: Boolean(candidateImageErrors.value[Number(img.fileId)] || candidateImageErrors.value[img.fileId]),
    width: img.width,
    height: img.height,
  }))
})

const previewInventors = computed(() => activeNormalized.value.inventorRefs || [])
const previewSections = computed(() => activeNormalized.value.sections || [])
const previewPatents = computed(() => activeNormalized.value.patents || [])
const previewLinks = computed(() => activeNormalized.value.links || [])

function upsertBatchSummary(batch) {
  if (!batch?.id) return
  const summary = {
    id: batch.id,
    sourceFilename: batch.sourceFilename,
    sourceOrgName: batch.sourceOrgName,
    status: batch.status,
    totalCount: batch.totalCount,
    successCount: batch.successCount,
    failedCount: batch.failedCount,
    createdAt: batch.createdAt,
    completedAt: batch.completedAt,
  }
  const exists = batches.value.some(item => String(item.id) === String(batch.id))
  const next = exists
    ? batches.value.map(item => String(item.id) === String(batch.id) ? { ...item, ...summary } : item)
    : [...batches.value, summary]
  batches.value = next.sort((left, right) => Number(right.id) - Number(left.id)).slice(0, 50)
}

async function loadCandidateImage(image) {
  const fileId = Number(image?.fileId)
  if (!fileId || candidateImageUrls.value[fileId] || inflightImageIds.has(fileId)) return
  inflightImageIds.add(fileId)
  try {
    const response = await fetch(`/api/tech-transfer/v1/files/${fileId}`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    })
    if (!response.ok) {
      candidateImageErrors.value[fileId] = true
      return
    }
    const blob = await response.blob()
    const typed = blob.type && blob.type.startsWith('image/') ? blob : new Blob([blob], { type: image?.mimeType || 'image/jpeg' })
    // 就地写入，避免多张图并行完成后互相覆盖，只剩最后一张能预览。
    candidateImageUrls.value[fileId] = URL.createObjectURL(typed)
  } catch {
    candidateImageErrors.value[fileId] = true
  }
  finally {
    inflightImageIds.delete(fileId)
  }
}

function loadItemImages(item) {
  for (const image of item?.raw?.images || []) loadCandidateImage(image)
}

watch(activeItem, (item) => {
  lightboxIndex.value = -1
  if (item) loadItemImages(item)
})

// 撤销所有已创建的 blob URL，释放 GPU/内存；切换批次或清空暂存时必须调用
function revokeCandidateUrls() {
  Object.values(candidateImageUrls.value).forEach((url) => {
    if (url) URL.revokeObjectURL(url)
  })
  candidateImageUrls.value = {}
  candidateImageErrors.value = {}
  inflightImageIds.clear()
  lightboxIndex.value = -1
}

async function loadBatches() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await api('/admin/achievement-imports', { params: { page: 1, pageSize: 50 } })
    batches.value = data.list || []
  } catch (error) {
    batches.value = []
    loadError.value = error.message || '导入批次加载失败'
  } finally {
    loading.value = false
  }
}

async function selectBatch(batch) {
  revokeCandidateUrls() // 切换批次前撤销旧 blob URL，避免内存泄漏
  detailLoading.value = true
  selectedBatch.value = null
  activeItemIndex.value = 0
  try {
    selectedBatch.value = await api(`/admin/achievement-imports/${batch.id}`)
    upsertBatchSummary(selectedBatch.value)
    loadItemImages(selectedBatch.value.items?.[0])
  } catch (error) {
    await alertDialog({ title: '加载失败', message: error.message || '导入详情加载失败' })
  } finally {
    detailLoading.value = false
  }
}

function selectItem(index) { activeItemIndex.value = index }

async function clearStaging() {
  if (clearing.value) return
  const ok = await confirmDialog({
    title: '清空导入暂存',
    message: '将删除全部导入批次和暂存条目，已入库为草稿的成果不受影响。确定继续？',
    confirmText: '清空', tone: 'danger',
  })
  if (!ok) return
  clearing.value = true
  try {
    await api('/admin/achievement-imports/clear', { method: 'POST', body: {} })
    revokeCandidateUrls() // 清空暂存后撤销所有 blob URL
    selectedBatch.value = null
    batches.value = []
    activeItemIndex.value = 0
  } catch (error) {
    await alertDialog({ title: '清空失败', message: error.message || '请刷新后重试' })
  } finally {
    clearing.value = false
  }
}

function openFilePicker() {
  if (importing.value) return
  fileInput.value?.click()
}

async function openFolderPicker() {
  if (importing.value) return
  if (typeof window.showDirectoryPicker === 'function') {
    try {
      const dir = await window.showDirectoryPicker({ mode: 'read' })
      await runImportFlow(await readDirectoryFiles(dir))
    } catch (error) {
      if (error?.name === 'AbortError') return
      await alertDialog({ title: '导入失败', message: error.message || '无法读取文件夹' })
    }
    return
  }
  folderInput.value?.click()
}

async function importDocuments(event) {
  const files = snapshotFileList(event.target.files)
  event.target.value = ''
  await runImportFlow(files)
}

async function runImportFlow(files) {
  if (!files?.length || importing.value) return
  importing.value = true
  try {
    const data = await confirmAndRunAchievementImport(files, {
      api,
      sourceOrg: sourceOrg.value,
      confirmDialog,
      openProgressDialog,
      updateProgressDialog,
      closeProgressDialog,
    })
    if (!data) return
    await alertDialog({
      title: '导入完成',
      message: summarizeAchievementImport(data),
    })
    const summaries = await Promise.all((data.list || []).map(item => api(`/admin/achievement-imports/${item.batchId}`)))
    summaries.forEach(upsertBatchSummary)
    const nextId = data.batchId || data.list?.[0]?.batchId
    const next = summaries.find(item => String(item.id) === String(nextId)) || summaries[0]
    if (next) {
      revokeCandidateUrls()
      selectedBatch.value = next
      activeItemIndex.value = 0
      loadItemImages(next.items?.[0])
    }
  } catch (error) {
    await alertDialog({
      title: error.code === 'NO_IMPORT_FILES' ? '未找到可导入文件' : '导入失败',
      message: error.message || '请检查文件后重试',
    })
  } finally {
    importing.value = false
    importProgress.value = ''
  }
}

async function publishItem(item) {
  if (publishingId.value || item.status !== 'staged' || (item.validationErrors || []).length) return
  const ok = await confirmDialog({
    title: '一键发布成果',
    message: '将直接确认入库、提交审核并通过审核发布到小程序前端，用户即可看到该成果。',
    confirmText: '发布', tone: 'primary',
  })
  if (!ok) return
  publishingId.value = item.id
  try {
    await api(`/admin/achievement-imports/${selectedBatch.value.id}/items/${item.id}/publish`, { method: 'POST', body: {} })
    await selectBatch(selectedBatch.value)
  } catch (error) {
    await alertDialog({ title: '发布失败', message: error.message || '请刷新后重试' })
  } finally {
    publishingId.value = null
  }
}

onMounted(loadBatches)
onBeforeUnmount(revokeCandidateUrls)
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h2>成果导入暂存</h2>
        <p>可选择多个 .pptx/.pdf，或直接导入整个文件夹。右侧预览小程序样式，确认无误后一键发布。</p>
      </div>
      <div class="header-actions">
        <input v-model="sourceOrg" class="org-input" type="text" maxlength="80" placeholder="来源机构（可选）" :disabled="importing" />
        <input ref="fileInput" class="hidden-file" type="file" :accept="IMPORT_ACCEPT" multiple @change="importDocuments" />
        <input ref="folderInput" class="hidden-file" type="file" webkitdirectory directory multiple @change="importDocuments" />
        <button type="button" class="primary-button" :disabled="importing" @click="openFilePicker">{{ importing ? (importProgress || '导入中…') : '选择文件' }}</button>
        <button type="button" class="default-button" :disabled="importing" @click="openFolderPicker">导入文件夹</button>
        <button type="button" class="default-button" :disabled="clearing || importing" @click="clearStaging">{{ clearing ? '清空中…' : '清空暂存' }}</button>
        <button type="button" class="default-button" :disabled="loading || importing" @click="loadBatches">刷新</button>
      </div>
    </header>

    <p v-if="loadError" class="error">{{ loadError }}</p>
    <div class="layout">
      <section class="card batches">
        <p v-if="loading" class="state">加载中…</p>
        <p v-else-if="!batches.length" class="state">暂无导入批次。点击右上角「选择文件」或「导入文件夹」上传 .pptx / .pdf。</p>
        <template v-for="batch in batches" :key="batch.id">
          <button type="button" class="batch" :class="{ active: selectedBatch && selectedBatch.id === batch.id }" @click="selectBatch(batch)">
            <strong>{{ batch.sourceFilename }}</strong>
            <span>{{ batch.sourceOrgName || '未填写来源机构' }}</span>
            <small>共 {{ batch.totalCount }} 条 · 已入库 {{ batch.successCount }} 条 · 异常 {{ batch.failedCount }} 条</small>
            <small>{{ formatTime(batch.createdAt) }}</small>
          </button>
          <template v-if="selectedBatch && selectedBatch.id === batch.id">
            <button
              v-for="(item, index) in selectedBatch.items"
              :key="item.id"
              type="button"
              class="sub-item"
              :class="{ active: activeItemIndex === index }"
              @click="selectItem(index)"
            >
              <span class="sub-page">{{ item.sourcePageOrSlide }}</span>
              <span class="sub-title">{{ item.normalized.title || '未识别标题' }}</span>
              <span :class="['status-tag', item.status]">{{ item.status === 'imported' ? '已入库' : item.status === 'staged' ? '待确认' : '异常' }}</span>
            </button>
          </template>
        </template>
      </section>

      <section class="card detail">
        <p v-if="detailLoading" class="state">正在读取解析结果…</p>
        <p v-else-if="!selectedBatch || !activeItem" class="state">选择左侧条目查看小程序前端预览效果。</p>
        <template v-else>
          <header class="detail-header">
            <div>
              <h3>{{ activeNormalized.title || '未识别标题' }}</h3>
              <p>{{ activeItem.sourcePageOrSlide }} · {{ activeRaw.pageType || 'project' }} · {{ activeItem.status === 'imported' ? '已入库' : '待确认' }}</p>
            </div>
            <button
              v-if="activeItem.status === 'staged' && !(activeItem.validationErrors || []).length"
              type="button"
              class="publish-button"
              :disabled="publishingId === activeItem.id"
              @click="publishItem(activeItem)"
            >{{ publishingId === activeItem.id ? '发布中…' : '发布' }}</button>
            <span v-else-if="activeItem.status === 'imported'" class="published-badge">已入库</span>
          </header>

          <div class="phone-preview">
            <div class="phone-screen">
              <div class="mp-title-section">
                <h1 class="mp-title">{{ activeNormalized.title || '未识别标题' }}</h1>
                <p v-if="activeNormalized.titleEn" class="mp-title-en">{{ activeNormalized.titleEn }}</p>
                <div v-if="activeNormalized.sourceOrgName" class="mp-org">{{ activeNormalized.sourceOrgName }}</div>
              </div>

              <div v-if="previewImages.length" :class="['mp-media-section', previewImages.length === 1 ? 'mp-media-single' : '']">
                <div v-if="previewImages.length === 1" class="mp-single-image">
                  <button v-if="previewImages[0].url" type="button" class="mp-image-hit" @click="lightboxIndex = 0">
                    <img :src="previewImages[0].url" :alt="previewImages[0].filename" />
                  </button>
                  <div v-else-if="previewImages[0].failed" class="mp-image-loading">图片文件缺失，无法预览</div>
                  <div v-else class="mp-image-loading">正在加载图片…</div>
                </div>
                <div v-else class="mp-image-grid">
                  <figure v-for="(img, i) in previewImages" :key="img.fileId || i" class="mp-image-card">
                    <button v-if="img.url" type="button" class="mp-image-hit" @click="lightboxIndex = i">
                      <img :src="img.url" :alt="img.filename" />
                    </button>
                    <div v-else-if="img.failed" class="mp-image-loading">图片文件缺失，无法预览</div>
                    <div v-else class="mp-image-loading">正在加载图片…</div>
                  </figure>
                </div>
              </div>

              <div v-if="activeNormalized.techIntro" class="mp-section">
                <div class="mp-section-title">技术简介</div>
                <div class="mp-section-body">{{ activeNormalized.techIntro }}</div>
              </div>

              <div v-for="section in previewSections" :key="section.code" class="mp-section">
                <div class="mp-section-title">{{ section.title }}</div>
                <div class="mp-section-body">{{ section.content }}</div>
              </div>

              <div v-if="previewPatents.length" class="mp-section">
                <div class="mp-section-title">相关专利</div>
                <div v-for="patent in previewPatents" :key="patent.patentNo" class="mp-patent-row">
                  <span class="mp-patent-no">{{ patent.patentNo }}</span>
                  <span class="mp-patent-jump">点击搜索 →</span>
                </div>
              </div>

              <div v-if="previewLinks.length" class="mp-section">
                <div class="mp-section-title">相关链接</div>
                <a v-for="link in previewLinks" :key="link.url" class="mp-link" :href="link.url" target="_blank">{{ link.label || link.url }}</a>
              </div>

              <div v-if="activeNormalized.maturityLevel || activeNormalized.pricingMode" class="mp-section mp-info-row">
                <div v-if="activeNormalized.maturityLevel" class="mp-info-item">
                  <span class="mp-info-label">成熟度</span>
                  <span class="mp-info-value">{{ activeNormalized.maturityLevel }}</span>
                </div>
                <div v-if="activeNormalized.pricingMode" class="mp-info-item">
                  <span class="mp-info-label">转化方式</span>
                  <span class="mp-info-value">{{ activeNormalized.pricingMode }}</span>
                </div>
              </div>

              <div v-if="activeNormalized.applicationFields && activeNormalized.applicationFields.length" class="mp-section">
                <div class="mp-section-title">可应用领域</div>
                <div class="mp-tags">
                  <span v-for="field in activeNormalized.applicationFields" :key="field" class="mp-tag">{{ field }}</span>
                </div>
              </div>

              <div v-if="previewInventors.length" class="mp-section">
                <div class="mp-section-title">成果完成人（{{ previewInventors.length }}人）</div>
                <div v-for="(inv, i) in previewInventors" :key="i" class="mp-inventor-card">
                  <div class="mp-inventor-avatar">
                    <span class="mp-avatar-placeholder">{{ (inv.name || '?').charAt(0) }}</span>
                  </div>
                  <div class="mp-inventor-info">
                    <div class="mp-inventor-name">{{ inv.name }}</div>
                    <div v-if="inv.title" class="mp-inventor-title">{{ inv.title }}</div>
                    <div v-if="inv.email" class="mp-inventor-contact">邮箱：{{ inv.email }}</div>
                    <div v-if="inv.phone" class="mp-inventor-contact">电话：{{ inv.phone }}</div>
                    <div v-if="inv.bio" class="mp-inventor-bio">{{ inv.bio }}</div>
                  </div>
                </div>
              </div>

              <div v-if="activeNormalized.contactName || activeNormalized.contactEmail || activeNormalized.contactPhone" class="mp-section mp-contact">
                <div class="mp-section-title">联系方式</div>
                <div v-if="activeNormalized.contactName" class="mp-contact-row">联系人：{{ activeNormalized.contactName }}</div>
                <div v-if="activeNormalized.contactPhone" class="mp-contact-row">电话：{{ activeNormalized.contactPhone }}</div>
                <div v-if="activeNormalized.contactEmail" class="mp-contact-row">邮箱：{{ activeNormalized.contactEmail }}</div>
              </div>

              <div v-if="activeItem.validationErrors && activeItem.validationErrors.length" class="mp-errors">
                <div class="mp-section-title">校验问题</div>
                <ul><li v-for="error in activeItem.validationErrors" :key="error.field">{{ error.field }}：{{ error.message }}</li></ul>
              </div>

              <details class="mp-raw"><summary>查看原始解析文本</summary><pre>{{ activeRaw.text }}</pre></details>
            </div>
          </div>
          <div v-if="lightboxIndex >= 0 && previewImages[lightboxIndex]?.url" class="lightbox" @click="lightboxIndex = -1">
            <img :src="previewImages[lightboxIndex].url" :alt="previewImages[lightboxIndex].filename" />
            <p>{{ previewImages[lightboxIndex].filename }}</p>
          </div>
        </template>
      </section>
    </div>
  </section>
</template>

<style scoped>
.page { width: 100%; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.page-header h2 { margin: 0; color: #1d2b3e; }
.page-header p { margin: 7px 0 0; color: #78879a; font-size: 13px; }
.header-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px; position: relative; }
.org-input { height: 36px; width: 180px; padding: 0 10px; border: 1px solid #d9e2ee; border-radius: 5px; color: #4a5c72; }
.primary-button { height: 36px; padding: 0 16px; border: 0; border-radius: 5px; background: #1677ff; color: #fff; font-size: 13px; font-weight: 600; cursor: pointer; }
.primary-button:hover { background: #0958d9; }
.primary-button:disabled, .default-button:disabled { opacity: .55; cursor: not-allowed; }
.hidden-file { position: fixed; left: 0; top: 0; width: 0; height: 0; opacity: 0; }
.layout { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 18px; height: calc(100vh - 190px); min-height: 460px; overflow: hidden; }
.card { min-height: 0; border: 1px solid #e5ebf3; border-radius: 10px; background: #fff; box-shadow: 0 2px 12px rgba(38,70,110,.06); }
.state { padding: 36px; color: #8794a5; text-align: center; }
.error { color: #d94d5e; margin-bottom: 12px; }

.batches { overflow-y: auto; overscroll-behavior: contain; }
.batch { display: block; width: 100%; padding: 16px 18px; border: 0; border-bottom: 1px solid #edf1f6; background: #fff; text-align: left; cursor: pointer; }
.batch:hover, .batch.active { background: #f2f7ff; }
.batch strong, .batch span, .batch small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.batch strong { color: #28384d; }
.batch span { margin-top: 6px; color: #65768b; font-size: 13px; }
.batch small { margin-top: 5px; color: #98a5b5; font-size: 12px; }
.sub-item { display: flex; align-items: center; gap: 8px; width: 100%; padding: 10px 24px; border: 0; border-bottom: 1px solid #f0f4f8; background: #fafcff; text-align: left; cursor: pointer; font-size: 12px; }
.sub-item:hover, .sub-item.active { background: #e8f1ff; }
.sub-page { color: #98a5b5; flex-shrink: 0; }
.sub-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #45566c; }
.status-tag { flex-shrink: 0; border-radius: 4px; padding: 2px 6px; font-size: 11px; }
.status-tag.staged { background: #eaf3ff; color: #2875dc; }
.status-tag.imported { background: #e8f8ef; color: #159458; }
.status-tag.failed { background: #fff0f1; color: #d94d5e; }

.detail { box-sizing: border-box; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.detail-header { flex-shrink: 0; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 20px; border-bottom: 1px solid #edf1f5; }
.detail-header h3 { margin: 0; color: #1d2b3e; font-size: 16px; }
.detail-header p { margin: 5px 0 0; color: #98a5b5; font-size: 12px; }
.publish-button { flex-shrink: 0; height: 36px; padding: 0 24px; border: 0; border-radius: 6px; background: #1677ff; color: #fff; font-size: 14px; font-weight: 600; cursor: pointer; }
.publish-button:hover { background: #0958d9; }
.publish-button:disabled { opacity: .55; cursor: not-allowed; }
.published-badge { flex-shrink: 0; padding: 6px 14px; border-radius: 6px; background: #e8f8ef; color: #159458; font-size: 13px; font-weight: 600; }

.phone-preview { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 20px; background: #f5f7fa; display: flex; flex-direction: column; align-items: center; }
.phone-screen { width: 375px; max-width: 100%; flex-shrink: 0; background: #fff; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,.1); overflow: hidden; }
.mp-title-section { padding: 20px 16px 14px; border-bottom: 1px solid #f0f4f8; }
.mp-title { margin: 0; font-size: 20px; font-weight: 700; color: #1a1a1a; line-height: 1.4; }
.mp-title-en { margin: 6px 0 0; font-size: 13px; color: #999; }
.mp-org { margin-top: 8px; font-size: 12px; color: #1677ff; }

.mp-media-section { padding: 14px 16px; }
.mp-media-single { display: flex; justify-content: center; }
.mp-single-image img { max-width: 100%; max-height: 280px; border-radius: 8px; object-fit: contain; }
.mp-image-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
.mp-image-card { margin: 0; }
.mp-image-hit { display: block; width: 100%; padding: 0; border: 0; background: transparent; cursor: zoom-in; }
.mp-image-grid img { width: 100%; max-height: 280px; border-radius: 8px; background: #f5f7fa; object-fit: contain; }
.mp-image-loading { display: flex; align-items: center; justify-content: center; min-height: 88px; border-radius: 8px; background: #f5f7fa; color: #8794a5; font-size: 13px; }
.lightbox { position: fixed; inset: 0; z-index: 40; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 24px; background: rgba(16, 24, 40, .72); cursor: zoom-out; }
.lightbox img { max-width: min(92vw, 960px); max-height: 82vh; object-fit: contain; border-radius: 8px; background: #fff; }
.lightbox p { margin: 0; color: #fff; font-size: 13px; }

.mp-section { padding: 14px 16px; border-bottom: 1px solid #f5f7fa; }
.mp-section-title { font-size: 15px; font-weight: 600; color: #1a1a1a; margin-bottom: 8px; }
.mp-section-body { font-size: 14px; color: #555; line-height: 1.7; white-space: pre-wrap; }

.mp-patent-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; margin-bottom: 6px; border-radius: 6px; background: #f0f7ff; }
.mp-patent-no { font-size: 14px; color: #1677ff; font-weight: 600; }
.mp-patent-jump { font-size: 12px; color: #1677ff; }
.mp-link { display: block; padding: 6px 0; font-size: 14px; color: #1677ff; text-decoration: none; }
.mp-link:hover { text-decoration: underline; }

.mp-info-row { display: flex; gap: 16px; }
.mp-info-item { display: flex; flex-direction: column; gap: 4px; }
.mp-info-label { font-size: 12px; color: #999; }
.mp-info-value { font-size: 14px; color: #333; font-weight: 500; }

.mp-tags { display: flex; flex-wrap: wrap; gap: 8px; }
.mp-tag { padding: 4px 12px; border-radius: 12px; background: #f0f7ff; color: #1677ff; font-size: 12px; }

.mp-inventor-card { display: flex; gap: 12px; padding: 12px 0; border-top: 1px solid #f5f7fa; }
.mp-inventor-card:first-child { border-top: 0; }
.mp-inventor-avatar { flex-shrink: 0; width: 48px; height: 48px; border-radius: 50%; background: #e8f1ff; display: flex; align-items: center; justify-content: center; }
.mp-avatar-placeholder { font-size: 20px; color: #1677ff; font-weight: 600; }
.mp-inventor-info { flex: 1; }
.mp-inventor-name { font-size: 15px; font-weight: 600; color: #1a1a1a; }
.mp-inventor-title { font-size: 12px; color: #999; margin-top: 2px; }
.mp-inventor-contact { font-size: 13px; color: #666; margin-top: 4px; }
.mp-inventor-bio { font-size: 13px; color: #555; line-height: 1.6; margin-top: 6px; }

.mp-contact-row { font-size: 14px; color: #555; padding: 4px 0; }
.mp-errors { padding: 14px 16px; background: #fff5f5; }
.mp-errors ul { margin: 6px 0 0; padding-left: 18px; color: #d94d5e; font-size: 13px; }
.mp-raw { padding: 14px 16px; }
.mp-raw summary { cursor: pointer; color: #98a5b5; font-size: 13px; }
.mp-raw pre { max-height: 200px; overflow: auto; margin-top: 8px; padding: 10px; border-radius: 5px; background: #f7f9fc; color: #536277; white-space: pre-wrap; word-break: break-word; font-size: 12px; }

.default-button { height: 36px; padding: 0 16px; border-radius: 5px; border: 1px solid #d9e2ee; background: #fff; color: #4a5c72; font-size: 13px; cursor: pointer; }
.default-button:disabled { opacity: .55; cursor: not-allowed; }

@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; grid-template-rows: minmax(180px, 36%) minmax(0, 64%); height: calc(100dvh - 190px); min-height: 520px; overflow: hidden; }
  .batches { min-height: 0; max-height: none; overflow-y: auto; }
  .detail { min-height: 0; max-height: none; overflow: hidden; }
  .phone-preview { min-height: 0; overflow-y: auto; }
}
</style>
