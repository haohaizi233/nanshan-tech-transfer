<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { api, getToken } from '../../api/client'
import { alertDialog, confirmDialog } from '../../utils/appDialog.js'

const batches = ref([])
const loading = ref(false)
const loadError = ref('')
const selectedBatch = ref(null)
const detailLoading = ref(false)
const confirmingId = ref(null)
const candidateImageUrls = ref({})

const formatTime = value => value ? String(value).replace('T', ' ').slice(0, 16) : '—'

function candidateImageUrl(image) {
  return candidateImageUrls.value[image.fileId] || ''
}

async function loadCandidateImage(image) {
  const fileId = Number(image?.fileId)
  if (!fileId || candidateImageUrls.value[fileId]) return
  try {
    const response = await fetch(`/api/tech-transfer/v1/files/${fileId}`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    })
    if (!response.ok) return
    candidateImageUrls.value = {
      ...candidateImageUrls.value,
      [fileId]: URL.createObjectURL(await response.blob()),
    }
  } catch {
    // 无权读取或文件已失效时仍显示候选文件元信息，避免打断整批审核。
  }
}

function loadCandidateImages(batch) {
  for (const item of batch?.items || []) {
    for (const image of item.raw?.images || []) loadCandidateImage(image)
  }
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
  detailLoading.value = true
  selectedBatch.value = null
  try {
    selectedBatch.value = await api(`/admin/achievement-imports/${batch.id}`)
    loadCandidateImages(selectedBatch.value)
  } catch (error) {
    await alertDialog({ title: '加载失败', message: error.message || '导入详情加载失败' })
  } finally {
    detailLoading.value = false
  }
}

async function confirmItem(item) {
  if (confirmingId.value || item.status !== 'staged' || (item.validationErrors || []).length) return
  const ok = await confirmDialog({
    title: '确认导入成果',
    message: '仅会创建成果草稿，仍需按正常流程补充资料、提交审核和发布。',
    confirmText: '确认入库',
    tone: 'primary',
  })
  if (!ok) return
  confirmingId.value = item.id
  try {
    await api(`/admin/achievement-imports/${selectedBatch.value.id}/items/${item.id}/confirm`, { method: 'POST', body: {} })
    await Promise.all([selectBatch(selectedBatch.value), loadBatches()])
  } catch (error) {
    await alertDialog({ title: '入库失败', message: error.message || '请刷新后重试' })
  } finally {
    confirmingId.value = null
  }
}

onMounted(loadBatches)
onBeforeUnmount(() => Object.values(candidateImageUrls.value).forEach(URL.revokeObjectURL))
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div><h2>成果导入暂存</h2><p>解析结果必须人工确认；不会自动发布或覆盖已有成果。</p></div>
      <button type="button" class="default-button" :disabled="loading" @click="loadBatches">刷新</button>
    </header>

    <p v-if="loadError" class="error">{{ loadError }}</p>
    <div class="layout">
      <section class="card batches">
        <p v-if="loading" class="state">加载中…</p>
        <p v-else-if="!batches.length" class="state">暂无导入批次。可使用服务端导入工具创建暂存批次。</p>
        <button v-for="batch in batches" :key="batch.id" type="button" class="batch" :class="{ active: selectedBatch && selectedBatch.id === batch.id }" @click="selectBatch(batch)">
          <strong>{{ batch.sourceFilename }}</strong>
          <span>{{ batch.sourceOrgName || '未填写来源机构' }}</span>
          <small>共 {{ batch.totalCount }} 条 · 已入库 {{ batch.successCount }} 条 · 异常 {{ batch.failedCount }} 条</small>
          <small>{{ formatTime(batch.createdAt) }}</small>
        </button>
      </section>

      <section class="card detail">
        <p v-if="detailLoading" class="state">正在读取解析结果…</p>
        <p v-else-if="!selectedBatch" class="state">选择左侧批次查看原始来源、识别字段和校验结果。</p>
        <template v-else>
          <header class="detail-header"><div><h3>{{ selectedBatch.sourceFilename }}</h3><p>{{ selectedBatch.sourceOrgName || '未填写来源机构' }} · {{ selectedBatch.status }}</p></div></header>
          <article v-for="item in selectedBatch.items" :key="item.id" class="item">
            <div class="item-title"><strong>{{ item.sourcePageOrSlide }} · {{ item.normalized.title || '未识别标题' }}</strong><span :class="['status', item.status]">{{ item.status }}</span></div>
            <p v-if="item.normalized.techIntro" class="intro">{{ item.normalized.techIntro }}</p>
            <div v-if="item.normalized.sections && item.normalized.sections.length" class="chips"><span v-for="section in item.normalized.sections" :key="section.code">{{ section.title }}</span></div>
            <div v-if="item.normalized.patents && item.normalized.patents.length" class="patents">专利：{{ item.normalized.patents.map(p => p.patentNo).join('、') }}</div>
            <div v-if="item.raw.images && item.raw.images.length" class="candidate-media">
              <strong>候选媒体（请确认不是 Logo 或装饰背景）</strong>
              <div class="candidate-grid">
                <figure v-for="image in item.raw.images" :key="image.fileId || image.filename">
                  <img v-if="candidateImageUrl(image)" :src="candidateImageUrl(image)" :alt="image.filename" />
                  <div v-else class="candidate-placeholder">无法预览</div>
                  <figcaption>{{ image.filename }}<span v-if="image.width && image.height"> · {{ image.width }}×{{ image.height }}</span></figcaption>
                </figure>
              </div>
            </div>
            <ul v-if="item.validationErrors && item.validationErrors.length" class="errors"><li v-for="error in item.validationErrors" :key="error.field">{{ error.field }}：{{ error.message }}</li></ul>
            <details><summary>查看原始文本</summary><pre>{{ item.raw.text }}</pre></details>
            <button v-if="item.status === 'staged' && !(item.validationErrors || []).length" type="button" class="primary-button" :disabled="confirmingId === item.id" @click="confirmItem(item)">{{ confirmingId === item.id ? '入库中…' : '确认并创建草稿' }}</button>
          </article>
        </template>
      </section>
    </div>
  </section>
</template>

<style scoped>
.page { width: 100%; }.page-header,.detail-header,.item-title { display:flex; align-items:center; justify-content:space-between; gap:16px; }.page-header { margin-bottom:18px; }.page-header h2,.detail-header h3 { margin:0; color:#1d2b3e; }.page-header p,.detail-header p { margin:7px 0 0; color:#78879a; font-size:13px; }.layout { display:grid; grid-template-columns:300px minmax(0, 1fr); gap:18px; }.card { border:1px solid #e5ebf3; border-radius:10px; background:#fff; box-shadow:0 2px 12px rgba(38,70,110,.06); }.batches { overflow:hidden; }.batch { display:block; width:100%; padding:16px 18px; border:0; border-bottom:1px solid #edf1f6; background:#fff; text-align:left; cursor:pointer; }.batch:hover,.batch.active { background:#f2f7ff; }.batch strong,.batch span,.batch small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.batch strong { color:#28384d; }.batch span { margin-top:6px; color:#65768b; font-size:13px; }.batch small { margin-top:5px; color:#98a5b5; font-size:12px; }.detail { min-height:460px; padding:20px; }.state { padding:36px; color:#8794a5; text-align:center; }.item { padding:18px 0; border-top:1px solid #edf1f5; }.item:first-of-type { margin-top:16px; }.intro { color:#45566c; line-height:1.65; white-space:pre-wrap; }.status { border-radius:4px; padding:4px 8px; font-size:12px; }.status.staged { background:#eaf3ff; color:#2875dc; }.status.imported { background:#e8f8ef; color:#159458; }.status.failed { background:#fff0f1; color:#d94d5e; }.chips span { display:inline-block; margin:0 6px 6px 0; padding:4px 8px; border-radius:4px; background:#f1f6ff; color:#4e79bd; font-size:12px; }.patents { margin:6px 0; color:#56677d; font-size:13px; }.candidate-media { margin:14px 0; color:#465d79; font-size:13px; }.candidate-grid { display:flex; flex-wrap:wrap; gap:10px; margin-top:8px; }.candidate-grid figure { width:140px; margin:0; padding:7px; border:1px solid #dfe8f4; border-radius:6px; background:#f8fbff; }.candidate-grid img,.candidate-placeholder { display:block; width:100%; height:90px; border-radius:4px; object-fit:cover; background:#edf3fb; }.candidate-placeholder { box-sizing:border-box; padding-top:35px; color:#8a98aa; text-align:center; }.candidate-grid figcaption { overflow:hidden; margin-top:5px; color:#718198; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }.errors { color:#d94d5e; }.errors li { margin:4px 0; } details { margin:10px 0; color:#65768b; } summary { cursor:pointer; } pre { max-height:200px; overflow:auto; padding:10px; border-radius:5px; background:#f7f9fc; color:#536277; white-space:pre-wrap; word-break:break-word; }.primary-button,.default-button { height:36px; padding:0 16px; border-radius:5px; font-size:13px; }.primary-button { border:1px solid #1677ff; background:#1677ff; color:#fff; }.default-button { border:1px solid #d9e2ee; background:#fff; color:#4a5c72; }.primary-button:disabled,.default-button:disabled { opacity:.55; cursor:not-allowed; }.error { color:#d94d5e; } @media (max-width:900px) { .layout { grid-template-columns:1fr; } .batches { max-height:280px; overflow:auto; } }
</style>
