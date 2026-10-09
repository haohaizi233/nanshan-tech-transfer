<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

import { api } from '../../api/client'
import { confirmDialog, alertDialog } from '../../utils/appDialog.js'
import { validateContactWay } from '../../utils/contactValidation.js'

const MODULES = [
  { key: 'poc', label: '概念验证中心', kind: 'platform', type: 'poc' },
  { key: 'pilot', label: '中小试基地', kind: 'platform', type: 'pilot' },
  { key: 'bank', label: '银行融资', kind: 'service', type: '' },
  { key: 'invest', label: '投资机构', kind: 'invest', type: '' },
]

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'active', label: '已上架' },
  { value: 'disabled', label: '已下架' },
]

const CSV_TEMPLATE = [
  'kind,platformTypeKey,platformType,name,serialNo,region,unit,functionText,contact,phone,label,sortOrder',
  'platform,poc,概念验证中心,示例概念验证中心,1,深圳市南山区,依托单位,服务早期技术验证,张三,13800138000,,1',
  'platform,pilot,中小试基地,示例中小试基地,2,深圳市南山区,依托单位,工程化中试资源,李四,13800138001,,2',
  'service,,,示例融资服务机构,,深圳市南山区,,,,13800138002,融资,3',
  'invest,,,示例投资机构,,深圳市南山区,,,,13800138003,投资,4',
].join('\n')

const activeModule = ref('poc')
const current = computed(() => MODULES.find(item => item.key === activeModule.value) || MODULES[0])

const filters = reactive({ keyword: '', status: '' })
const applied = reactive({ keyword: '', status: '' })
const currentPage = ref(1)
const pageSize = ref(10)
const rows = ref([])
const total = ref(0)
const totalPages = ref(1)
const loading = ref(false)
const loadError = ref('')
const actionError = ref('')
const actingId = ref(null)

const modalVisible = ref(false)
const modalMode = ref('create')
const modalError = ref('')
const saving = ref(false)
const currentItem = ref(null)
const form = reactive({
  name: '',
  region: '',
  intro: '',
  unit: '',
  functionText: '',
  contact: '',
  phone: '',
  label: '',
  sortOrder: 0,
})

const importing = ref(false)
const isPlatformModule = computed(() => current.value.kind === 'platform')
const colCount = computed(() => (isPlatformModule.value ? 8 : 5))

async function loadList() {
  loading.value = true
  loadError.value = ''
  try {
    const params = {
      page: currentPage.value,
      pageSize: pageSize.value,
      keyword: applied.keyword.trim(),
      kind: current.value.kind,
      status: applied.status,
    }
    if (current.value.type) params.type = current.value.type
    const data = await api('/admin/institutions', { params })
    rows.value = data.list || []
    total.value = data.total || 0
    totalPages.value = data.totalPages || Math.max(1, Math.ceil(total.value / pageSize.value))
  } catch (err) {
    rows.value = []
    total.value = 0
    totalPages.value = 1
    loadError.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadList)

const switchModule = key => {
  activeModule.value = key
  currentPage.value = 1
  loadList()
}

const handleSearch = () => {
  Object.assign(applied, filters)
  currentPage.value = 1
  loadList()
}

const reset = () => {
  filters.keyword = ''
  filters.status = ''
  Object.assign(applied, filters)
  currentPage.value = 1
  loadList()
}

const openCreate = () => {
  modalMode.value = 'create'
  currentItem.value = null
  modalError.value = ''
  Object.assign(form, { name: '', region: '', intro: '', unit: '', functionText: '', contact: '', phone: '', label: '', sortOrder: 0 })
  modalVisible.value = true
}

const openEdit = item => {
  modalMode.value = 'edit'
  currentItem.value = item
  modalError.value = ''
  Object.assign(form, {
    name: item.name || '',
    region: item.region || '',
    intro: item.intro || '',
    unit: item.unit || '',
    functionText: item.functionText || '',
    contact: item.contact || '',
    phone: item.phone || '',
    label: item.label || '',
    sortOrder: Number(item.sortOrder) || 0,
  })
  modalVisible.value = true
}

const closeModal = () => {
  modalVisible.value = false
}

const save = async () => {
  if (!form.name.trim()) {
    modalError.value = '请输入名称'
    return
  }
  if (isPlatformModule.value) {
    const phoneCheck = validateContactWay(form.phone, { required: false, label: '联系方式' })
    if (!phoneCheck.ok) {
      modalError.value = phoneCheck.message
      return
    }
  }
  if (saving.value) return
  saving.value = true
  modalError.value = ''
  try {
    const body = {
      name: form.name.trim(),
      region: form.region.trim(),
      intro: form.intro.trim(),
      label: form.label.trim(),
      sortOrder: Number(form.sortOrder) || 0,
    }
    if (isPlatformModule.value) {
      body.unit = form.unit.trim()
      body.contact = form.contact.trim()
      body.phone = validateContactWay(form.phone, { required: false, label: '联系方式' }).value
      body.functionText = form.functionText.trim()
    }
    if (modalMode.value === 'create') {
      body.kind = current.value.kind
      if (current.value.type) {
        body.platformTypeKey = current.value.type
        body.platformType = current.value.label
      }
      await api('/admin/institutions', { method: 'POST', body })
      currentPage.value = 1
    } else {
      await api(`/admin/institutions/${currentItem.value.id}`, { method: 'PATCH', body })
    }
    closeModal()
    loadList()
  } catch (err) {
    modalError.value = err.message || '保存失败'
  } finally {
    saving.value = false
  }
}

const toggleStatus = async item => {
  if (actingId.value) return
  actingId.value = item.id
  const goingOnline = item.status !== 'active'
  try {
    const ok = await confirmDialog({
      title: goingOnline ? '上架资源' : '下架资源',
      message: `确定${goingOnline ? '上架' : '下架'}「${item.name}」吗？`,
      confirmText: goingOnline ? '确定上架' : '确定下架',
      tone: goingOnline ? 'primary' : 'danger',
    })
    if (!ok) return
    actionError.value = ''
    await api(`/admin/institutions/${item.id}/${goingOnline ? 'online' : 'offline'}`, { method: 'POST' })
    await loadList()
  } catch (err) {
    actionError.value = err.message || '操作失败'
  } finally {
    actingId.value = null
  }
}

const removeItem = async item => {
  if (actingId.value) return
  actingId.value = item.id
  try {
    const ok = await confirmDialog({
      title: '删除资源',
      message: `确定删除「${item.name}」吗？删除后不可恢复。`,
      confirmText: '确定删除',
      tone: 'danger',
    })
    if (!ok) return
    actionError.value = ''
    await api(`/admin/institutions/${item.id}`, { method: 'DELETE' })
    if (rows.value.length <= 1 && currentPage.value > 1) {
      currentPage.value -= 1
    }
    await loadList()
  } catch (err) {
    actionError.value = err.message || '删除失败'
  } finally {
    actingId.value = null
  }
}

const splitCsvLine = line => {
  const out = []
  let current = ''
  let quoted = false
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        current += '"'
        i += 1
      } else {
        quoted = !quoted
      }
    } else if (ch === ',' && !quoted) {
      out.push(current)
      current = ''
    } else {
      current += ch
    }
  }
  out.push(current)
  return out
}

const parseCsv = text => {
  const lines = String(text || '').replace(/^\uFEFF/, '').split(/\r?\n/).filter(line => line.trim())
  if (!lines.length) return []
  const headers = splitCsvLine(lines[0]).map(item => item.trim())
  return lines.slice(1).map(line => {
    const cols = splitCsvLine(line)
    const row = {}
    headers.forEach((key, index) => {
      row[key] = (cols[index] || '').trim()
    })
    return row
  })
}

const downloadTemplate = () => {
  const blob = new Blob(['\uFEFF' + CSV_TEMPLATE], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = '资本对接导入模板.csv'
  link.click()
  URL.revokeObjectURL(url)
}

const importFile = async event => {
  const file = event.target.files && event.target.files[0]
  event.target.value = ''
  if (!file) return
  importing.value = true
  actionError.value = ''
  try {
    const text = await file.text()
    const items = parseCsv(text).filter(item => item.name)
    if (!items.length) {
      actionError.value = '文件中没有可导入的数据'
      return
    }
    const data = await api('/admin/institutions/import', { method: 'POST', body: { items } })
    await alertDialog({
      title: '导入完成',
      message: `新增 ${data.created || 0} 条，更新 ${data.updated || 0} 条。`,
    })
    loadList()
  } catch (err) {
    actionError.value = err.message || '导入失败'
  } finally {
    importing.value = false
  }
}

const pages = computed(() => {
  const count = totalPages.value
  if (count <= 7) return Array.from({ length: count }, (_, index) => index + 1)
  if (currentPage.value <= 4) return [1, 2, 3, 4, 5, '...', count]
  if (currentPage.value >= count - 3) return [1, '...', count - 4, count - 3, count - 2, count - 1, count]
  return [1, '...', currentPage.value - 1, currentPage.value, currentPage.value + 1, '...', count]
})

const goPage = page => {
  if (page === '...' || page === currentPage.value) return
  currentPage.value = page
  loadList()
}
</script>

<template>
  <div class="capital-page">
    <section class="filter-card">
      <div class="module-tabs">
        <button
          v-for="item in MODULES"
          :key="item.key"
          type="button"
          :class="{ active: activeModule === item.key }"
          @click="switchModule(item.key)"
        >
          {{ item.label }}
        </button>
      </div>
      <div class="filter-row">
        <div class="filter-item keyword">
          <label>关键词</label>
          <input
            v-model="filters.keyword"
            :placeholder="isPlatformModule ? '名称、简介或依托单位' : '名称或简介'"
            @keyup.enter="handleSearch"
          />
        </div>
        <div class="filter-item">
          <label>状态</label>
          <select v-model="filters.status" @change="handleSearch">
            <option
              v-for="item in STATUS_OPTIONS"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }}
            </option>
          </select>
        </div>
        <div class="filter-actions">
          <button class="primary-btn" type="button" @click="handleSearch">查询</button>
          <button class="default-btn" type="button" @click="reset">重置</button>
          <button class="primary-btn" type="button" @click="openCreate">＋ 新增</button>
          <button class="outline-btn" type="button" @click="downloadTemplate">下载模板</button>
          <label class="outline-btn upload-btn">
            {{ importing ? '导入中…' : '批量导入' }}
            <input type="file" accept=".csv,text/csv" :disabled="importing" @change="importFile" />
          </label>
        </div>
      </div>
      <p class="hint">导入 CSV 按 kind + sourcePk/名称幂等更新。平台列：kind / platformTypeKey / platformType / name / serialNo / region / unit / functionText / contact / phone / label / sortOrder。</p>
    </section>

    <section class="table-card">
      <p v-if="loadError || actionError" class="error-text">{{ loadError || actionError }}</p>
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>名称</th>
              <th v-if="isPlatformModule">依托单位</th>
              <th>{{ isPlatformModule ? '平台功能' : '简介' }}</th>
              <th v-if="isPlatformModule">联系人</th>
              <th v-if="isPlatformModule">联系方式</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td :colspan="colCount">加载中…</td>
            </tr>
            <tr v-else-if="!rows.length">
              <td :colspan="colCount">暂无数据</td>
            </tr>
            <tr v-for="item in rows" :key="item.id">
              <td>{{ item.id }}</td>
              <td>{{ item.name || '-' }}</td>
              <td v-if="isPlatformModule">{{ item.unit || '-' }}</td>
              <td class="fn-cell" :title="item.functionText || item.intro">{{ (isPlatformModule ? (item.functionText || item.intro) : item.intro) || '-' }}</td>
              <td v-if="isPlatformModule">{{ item.contact || '-' }}</td>
              <td v-if="isPlatformModule">{{ item.phone || '-' }}</td>
              <td>{{ item.status === 'active' ? '已上架' : '已下架' }}</td>
              <td class="ops-col">
                <div class="ops">
                  <button type="button" :disabled="actingId != null" @click="openEdit(item)">编辑</button>
                  <span>|</span>
                  <button type="button" :disabled="actingId != null" @click="toggleStatus(item)">{{ item.status === 'active' ? '下架' : '上架' }}</button>
                  <span>|</span>
                  <button type="button" :disabled="actingId != null" @click="removeItem(item)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span>共 {{ total }} 条</span>
        <button
          v-for="page in pages"
          :key="'p-' + page"
          type="button"
          :class="{ active: page === currentPage }"
          @click="goPage(page)"
        >
          {{ page }}
        </button>
      </div>
    </section>

    <div v-if="modalVisible" class="mask" @click.self="closeModal">
      <section class="modal">
        <header>
          <h2>{{ modalMode === 'create' ? '新增资本对接资源' : '编辑资本对接资源' }}</h2>
          <button type="button" @click="closeModal">×</button>
        </header>
        <p v-if="modalError" class="error-text">{{ modalError }}</p>
        <div class="form-grid">
          <label class="full">名称<input v-model="form.name" /></label>
          <label>地区<input v-model="form.region" /></label>
          <label>排序<input v-model="form.sortOrder" type="number" /></label>
          <label v-if="isPlatformModule">依托单位<input v-model="form.unit" /></label>
          <label v-if="isPlatformModule">联系人<input v-model="form.contact" /></label>
          <label v-if="isPlatformModule">联系方式<input v-model="form.phone" /></label>
          <label>标签<input v-model="form.label" /></label>
          <label v-if="isPlatformModule" class="full">平台功能<textarea v-model="form.functionText" rows="4" /></label>
          <label class="full">简介<textarea v-model="form.intro" rows="3" /></label>
        </div>
        <footer>
          <button type="button" class="default-btn" @click="closeModal">取消</button>
          <button type="button" class="primary-btn" :disabled="saving" @click="save">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </footer>
      </section>
    </div>
  </div>
</template>

<style scoped>
.capital-page { padding: 0 4px 24px; }
.filter-card, .table-card {
  background: #fff;
  border: 1px solid #edf1f6;
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 16px;
}
.module-tabs { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.module-tabs button {
  height: 36px;
  padding: 0 14px;
  border: 1px solid #dbe3ee;
  border-radius: 18px;
  background: #fff;
  color: #4a5667;
}
.module-tabs button.active { border-color: #1a7fff; background: #eaf3ff; color: #1a7fff; }
.filter-row { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-end; }
.filter-item { display: flex; flex-direction: column; gap: 6px; color: #536073; font-size: 13px; }
.filter-item.keyword { min-width: 260px; flex: 1; }
.filter-item input, .filter-item select, .form-grid input, .form-grid textarea {
  height: 38px;
  padding: 0 12px;
  border: 1px solid #e5eaf1;
  border-radius: 6px;
}
.form-grid textarea { height: auto; padding: 8px 12px; }
.filter-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.primary-btn, .default-btn, .outline-btn {
  height: 36px;
  padding: 0 14px;
  border-radius: 6px;
  border: 1px solid #dbe3ee;
  background: #fff;
  color: #4a5667;
}
.primary-btn { border: 0; background: #1a7fff; color: #fff; }
.upload-btn { position: relative; overflow: hidden; cursor: pointer; display: inline-flex; align-items: center; }
.upload-btn input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.hint { margin: 12px 0 0; color: #8a95a5; font-size: 12px; }
.error-text { color: #ef4f5d; font-size: 13px; }
.table-wrapper { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { height: 52px; padding: 0 12px; border-bottom: 1px solid #edf1f5; text-align: left; font-size: 13px; color: #4f5b6d; }
.fn-cell { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ops-col { width: 1%; white-space: nowrap; }
.ops { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
td button { border: 0; background: transparent; color: #1a7fff; }
td button:disabled { color: #9aa6b6; cursor: not-allowed; }
.pager { display: flex; align-items: center; gap: 8px; padding-top: 14px; color: #8a95a5; font-size: 13px; }
.pager button { min-width: 32px; height: 32px; border: 1px solid #e5eaf1; background: #fff; border-radius: 6px; }
.pager button.active { border-color: #1a7fff; color: #1a7fff; }
.mask { position: fixed; inset: 0; z-index: 70; display: flex; align-items: center; justify-content: center; background: rgba(18, 32, 48, 0.35); }
.modal { width: 640px; max-width: calc(100vw - 40px); background: #fff; border-radius: 12px; }
.modal header, .modal footer { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; }
.modal header h2 { margin: 0; font-size: 18px; }
.modal header button { border: 0; background: transparent; font-size: 22px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 0 20px 12px; }
.form-grid .full { grid-column: 1 / -1; }
.form-grid label { display: flex; flex-direction: column; gap: 6px; color: #536073; font-size: 13px; }
</style>
