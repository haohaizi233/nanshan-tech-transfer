<script setup>
import {
  computed,
  onMounted,
  reactive,
  ref
} from 'vue'

import { api } from '../../api/client'

const KIND_OPTIONS = [
  { value: 'platform', label: '平台' },
  { value: 'invest', label: '投资机构' },
  { value: 'service', label: '服务机构' }
]

const STATUS_OPTIONS = [
  { value: 'active', label: '已上架' },
  { value: 'disabled', label: '已下架' }
]

const kindLabel = item => {
  if (item.kind === 'platform') {
    return item.platformTypeKey === 'poc' ? '平台·验证' : item.platformTypeKey === 'pilot' ? '平台·中试' : '平台'
  }
  return { invest: '投资机构', service: '服务机构' }[item.kind] || '未分类'
}

const kindClass = item => ({
  platform: 'tag-platform',
  invest: 'tag-invest',
  service: 'tag-service'
}[item.kind] || 'tag-none')

const fmtTime = v => (v ? String(v).replace('T', ' ').slice(0, 16) : '-')

const filters = reactive({
  keyword: '',
  kind: '',
  status: ''
})

const applied = reactive({
  keyword: '',
  kind: '',
  status: ''
})

const currentPage = ref(1)
const pageSize = ref(10)

const rows = ref([])
const total = ref(0)
const totalPages = ref(1)
const loading = ref(false)
const loadError = ref('')
const actionError = ref('')

const modalVisible = ref(false)
const modalMode = ref('view')
const modalLoading = ref(false)
const modalError = ref('')
const saving = ref(false)
const currentItem = ref(null)

const form = reactive({
  kind: 'platform',
  name: '',
  intro: '',
  label: '',
  sortOrder: 0,
  contact: '',
  phone: '',
  unit: ''
})

const pages = computed(() => {
  const count = totalPages.value

  if (count <= 7) {
    return Array.from({ length: count }, (_, index) => index + 1)
  }

  if (currentPage.value <= 4) {
    return [1, 2, 3, 4, 5, '...', count]
  }

  if (currentPage.value >= count - 3) {
    return [1, '...', count - 4, count - 3, count - 2, count - 1, count]
  }

  return [1, '...', currentPage.value - 1, currentPage.value, currentPage.value + 1, '...', count]
})

async function loadList() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await api('/admin/institutions', {
      params: {
        page: currentPage.value,
        pageSize: pageSize.value,
        keyword: applied.keyword.trim(),
        kind: applied.kind,
        status: applied.status
      }
    })
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

const handleSearch = () => {
  Object.assign(applied, filters)
  currentPage.value = 1
  loadList()
}

const reset = () => {
  Object.assign(filters, { keyword: '', kind: '', status: '' })
  Object.assign(applied, { keyword: '', kind: '', status: '' })
  currentPage.value = 1
  loadList()
}

const changePage = page => {
  if (page === '...') return
  if (page < 1 || page > totalPages.value) return
  currentPage.value = page
  loadList()
}

const handlePageSizeChange = () => {
  currentPage.value = 1
  loadList()
}

const openView = async item => {
  modalMode.value = 'view'
  modalVisible.value = true
  modalLoading.value = true
  modalError.value = ''
  try {
    currentItem.value = await api(`/admin/institutions/${item.id}`)
  } catch (err) {
    currentItem.value = null
    modalError.value = err.message || '加载失败'
  } finally {
    modalLoading.value = false
  }
}

const fillForm = item => {
  Object.assign(form, {
    kind: item.kind || 'platform',
    name: item.name || '',
    intro: item.intro || '',
    label: item.label || '',
    sortOrder: item.sortOrder || 0,
    contact: item.contact || '',
    phone: item.phone || '',
    unit: item.unit || ''
  })
}

const openEdit = item => {
  modalMode.value = 'edit'
  currentItem.value = item
  modalError.value = ''
  fillForm(item)
  modalVisible.value = true
}

const openCreate = () => {
  modalMode.value = 'create'
  currentItem.value = null
  modalError.value = ''
  Object.assign(form, {
    kind: 'platform',
    name: '',
    intro: '',
    label: '',
    sortOrder: 0,
    contact: '',
    phone: '',
    unit: ''
  })
  modalVisible.value = true
}

const closeModal = () => {
  modalVisible.value = false
}

const save = async () => {
  if (!form.name.trim()) {
    modalError.value = '请输入机构名称'
    return
  }

  saving.value = true
  modalError.value = ''
  try {
    const body = {
      name: form.name.trim(),
      intro: form.intro.trim(),
      label: form.label.trim(),
      sortOrder: Number(form.sortOrder) || 0
    }
    if (form.kind === 'platform') {
      body.contact = form.contact.trim()
      body.phone = form.phone.trim()
      body.unit = form.unit.trim()
    }

    if (modalMode.value === 'create') {
      body.kind = form.kind
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
  const goingOnline = item.status !== 'active'
  const action = goingOnline ? '上架' : '下架'

  if (!window.confirm(`确定${action}机构《${item.name}》吗？`)) {
    return
  }

  actionError.value = ''
  try {
    await api(`/admin/institutions/${item.id}/${goingOnline ? 'online' : 'offline'}`, { method: 'POST' })
    loadList()
  } catch (err) {
    actionError.value = err.message || '操作失败'
  }
}

const exporting = ref(false)

const escapeCsv = value => `"${String(value ?? '').replaceAll('"', '""')}"`

const exportData = async () => {
  exporting.value = true
  actionError.value = ''
  try {
    const all = []
    for (let page = 1; page <= 20; page++) {
      const data = await api('/admin/institutions', {
        params: {
          page,
          pageSize: 50,
          keyword: applied.keyword.trim(),
          kind: applied.kind,
          status: applied.status
        }
      })
      all.push(...(data.list || []))
      if (page >= (data.totalPages || 1)) break
    }

    const csv = [
      ['ID', '机构名称', '机构类型', '标签', '简介', '状态', '更新时间'],
      ...all.map(item => [
        item.id,
        item.name,
        kindLabel(item),
        item.label,
        item.intro,
        item.status === 'active' ? '已上架' : '已下架',
        fmtTime(item.updatedAt)
      ])
    ].map(row => row.map(escapeCsv).join(',')).join('\n')

    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '机构列表.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    actionError.value = err.message || '导出失败'
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="institution-page">
    <section class="filter-card">
      <div class="filter-row">
        <div class="filter-item keyword">
          <label>关键词</label>
          <input
            v-model="filters.keyword"
            placeholder="请输入机构名称、标签或简介关键词"
            @keyup.enter="handleSearch"
          />
        </div>

        <div class="filter-item">
          <label>机构类型</label>
          <select v-model="filters.kind">
            <option value="">
              请选择机构类型
            </option>
            <option
              v-for="item in KIND_OPTIONS"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }}
            </option>
          </select>
        </div>

        <div class="filter-item">
          <label>状态</label>
          <select v-model="filters.status">
            <option value="">
              请选择状态
            </option>
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
          <button
            class="primary-btn"
            @click="handleSearch"
          >
            查询
          </button>

          <button
            class="default-btn"
            @click="reset"
          >
            重置
          </button>

          <button
            class="primary-btn"
            @click="openCreate"
          >
            ＋ 新增机构
          </button>
        </div>
      </div>
    </section>

    <section class="table-card">
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>机构名称</th>
              <th>机构类型</th>
              <th>标签</th>
              <th>简介</th>
              <th>排序</th>
              <th>状态</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>

          <tbody>
            <tr
              v-for="item in rows"
              :key="item.id"
            >
              <td>{{ item.id }}</td>

              <td
                class="name-cell"
                :title="item.name"
              >
                {{ item.name || '-' }}
              </td>

              <td>
                <span
                  class="type-tag"
                  :class="kindClass(item)"
                >
                  {{ kindLabel(item) }}
                </span>
              </td>

              <td
                class="label-cell"
                :title="item.label"
              >
                {{ item.label || '-' }}
              </td>

              <td
                class="intro-cell"
                :title="item.intro"
              >
                {{ item.intro || '-' }}
              </td>

              <td>{{ item.sortOrder }}</td>

              <td>
                <span
                  class="status"
                  :class="{
                    online: item.status === 'active',
                    offline: item.status !== 'active'
                  }"
                >
                  <i></i>

                  {{ item.status === 'active' ? '已上架' : '已下架' }}
                </span>
              </td>

              <td class="time-cell">
                {{ fmtTime(item.updatedAt) }}
              </td>

              <td>
                <div class="operation">
                  <button @click="openView(item)">
                    查看
                  </button>

                  <span>|</span>

                  <button @click="openEdit(item)">
                    编辑
                  </button>

                  <span>|</span>

                  <button @click="toggleStatus(item)">
                    {{ item.status === 'active' ? '下架' : '上架' }}
                  </button>
                </div>
              </td>
            </tr>

            <tr v-if="loading">
              <td
                colspan="9"
                class="state-row"
              >
                加载中…
              </td>
            </tr>

            <tr v-else-if="loadError">
              <td
                colspan="9"
                class="state-row error"
              >
                {{ loadError }}

                <button
                  class="retry-btn"
                  @click="loadList"
                >
                  重试
                </button>
              </td>
            </tr>

            <tr v-else-if="rows.length === 0">
              <td
                colspan="9"
                class="state-row"
              >
                暂无符合条件的机构
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div
        v-if="actionError"
        class="action-error"
      >
        {{ actionError }}
      </div>

      <div class="batch-right">
        <button
          class="outline-btn"
          :disabled="exporting"
          @click="exportData"
        >
          {{ exporting ? '导出中…' : '⇩ 导出数据' }}
        </button>
      </div>

      <div class="pagination">
        <span>
          共 {{ total }} 条
        </span>

        <select
          v-model="pageSize"
          @change="handlePageSizeChange"
        >
          <option :value="10">
            10条/页
          </option>
          <option :value="20">
            20条/页
          </option>
          <option :value="50">
            50条/页
          </option>
        </select>

        <button
          :disabled="currentPage === 1"
          @click="changePage(currentPage - 1)"
        >
          ‹
        </button>

        <template
          v-for="(page, index) in pages"
          :key="`${page}-${index}`"
        >
          <span
            v-if="page === '...'"
            class="ellipsis"
          >
            ...
          </span>

          <button
            v-else
            :class="{ active: currentPage === page }"
            @click="changePage(page)"
          >
            {{ page }}
          </button>
        </template>

        <button
          :disabled="currentPage === totalPages"
          @click="changePage(currentPage + 1)"
        >
          ›
        </button>
      </div>
    </section>

    <div
      v-if="modalVisible"
      class="modal-mask"
      @click.self="closeModal"
    >
      <div class="modal">
        <div class="modal-header">
          <h3>
            {{ modalMode === 'view' ? '机构详情' : modalMode === 'create' ? '新增机构' : '编辑机构' }}
          </h3>

          <button @click="closeModal">
            ×
          </button>
        </div>

        <div
          v-if="modalMode === 'view'"
          class="detail-grid"
        >
          <template v-if="modalLoading">
            <div class="full state-text">
              加载中…
            </div>
          </template>

          <template v-else-if="modalError">
            <div class="full state-text error">
              {{ modalError }}
            </div>
          </template>

          <template v-else-if="currentItem">
            <div>
              <label>机构编号</label>
              <strong>{{ currentItem.id }}</strong>
            </div>

            <div>
              <label>机构名称</label>
              <strong>{{ currentItem.name || '-' }}</strong>
            </div>

            <div>
              <label>机构类型</label>
              <strong>{{ kindLabel(currentItem) }}</strong>
            </div>

            <div>
              <label>状态</label>
              <strong>{{ currentItem.status === 'active' ? '已上架' : '已下架' }}</strong>
            </div>

            <div>
              <label>标签</label>
              <strong>{{ currentItem.label || '-' }}</strong>
            </div>

            <div>
              <label>排序</label>
              <strong>{{ currentItem.sortOrder }}</strong>
            </div>

            <template v-if="currentItem.kind === 'platform'">
              <div>
                <label>依托单位</label>
                <strong>{{ currentItem.unit || '-' }}</strong>
              </div>

              <div>
                <label>平台类型</label>
                <strong>{{ { poc: '验证平台', pilot: '中试平台', other: '其他' }[currentItem.platformTypeKey] || '-' }}</strong>
              </div>

              <div>
                <label>联系人</label>
                <strong>{{ currentItem.contact || '-' }}</strong>
              </div>

              <div>
                <label>联系电话</label>
                <strong>{{ currentItem.phone || '-' }}</strong>
              </div>
            </template>

            <div class="full">
              <label>简介</label>
              <strong>{{ currentItem.intro || '-' }}</strong>
            </div>

            <div
              v-if="currentItem.detailInfo"
              class="full"
            >
              <label>详细信息</label>
              <strong>{{ currentItem.detailInfo }}</strong>
            </div>

            <div class="full">
              <label>更新时间</label>
              <strong>{{ fmtTime(currentItem.updatedAt) }}</strong>
            </div>
          </template>
        </div>

        <div
          v-else
          class="form-grid"
        >
          <label>
            机构名称 *

            <input
              v-model="form.name"
              placeholder="请输入机构名称"
            />
          </label>

          <label v-if="modalMode === 'create'">
            机构类型 *

            <select v-model="form.kind">
              <option
                v-for="item in KIND_OPTIONS"
                :key="item.value"
                :value="item.value"
              >
                {{ item.label }}
              </option>
            </select>
          </label>

          <label>
            标签

            <input
              v-model="form.label"
              placeholder="如：概念验证、投融资"
            />
          </label>

          <label>
            排序

            <input
              v-model.number="form.sortOrder"
              type="number"
            />
          </label>

          <template v-if="form.kind === 'platform'">
            <label>
              依托单位

              <input v-model="form.unit" />
            </label>

            <label>
              联系人

              <input v-model="form.contact" />
            </label>

            <label>
              联系电话

              <input v-model="form.phone" />
            </label>
          </template>

          <label class="full">
            简介

            <textarea
              v-model="form.intro"
              rows="4"
            ></textarea>
          </label>
        </div>

        <div
          v-if="modalError && modalMode !== 'view'"
          class="modal-error"
        >
          {{ modalError }}
        </div>

        <div class="modal-footer">
          <button
            class="default-btn"
            @click="closeModal"
          >
            {{ modalMode === 'view' ? '关闭' : '取消' }}
          </button>

          <button
            v-if="modalMode !== 'view'"
            class="primary-btn"
            :disabled="saving"
            @click="save"
          >
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.institution-page {
  width: 100%;
}

.filter-card,
.table-card {
  border: 1px solid #e8edf4;
  border-radius: 11px;
  background: #fff;
  box-shadow:
    0 2px 14px rgba(40, 72, 110, 0.07);
}

.filter-card {
  padding: 26px 28px;
}

.filter-row {
  display: grid;
  grid-template-columns:
    1.35fr 1fr 1fr auto;
  align-items: end;
  gap: 28px;
}

.filter-item label {
  display: block;
  margin-bottom: 9px;
  color: #283447;
  font-size: 14px;
  font-weight: 600;
}

.filter-item input,
.filter-item select,
.pagination select,
.form-grid input,
.form-grid select,
.form-grid textarea {
  width: 100%;
  height: 42px;
  padding: 0 13px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  outline: none;
  background: white;
}

.form-grid textarea {
  height: auto;
  padding-top: 10px;
  resize: vertical;
}

.filter-item input:focus,
.filter-item select:focus,
.form-grid input:focus,
.form-grid select:focus,
.form-grid textarea:focus {
  border-color: #1677ff;
}

.filter-actions {
  display: flex;
  gap: 12px;
}

.primary-btn,
.default-btn,
.outline-btn {
  height: 42px;
  padding: 0 24px;
  border-radius: 5px;
}

.primary-btn {
  border: 1px solid #1677ff;
  background: #1677ff;
  color: white;
}

.primary-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.default-btn {
  border: 1px solid #dce4ee;
  background: white;
  color: #4f5c6d;
}

.outline-btn {
  border: 1px solid #78afff;
  background: white;
  color: #1677ff;
}

.outline-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.table-card {
  margin-top: 14px;
}

.table-wrapper {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 1240px;
  border-collapse: collapse;
  table-layout: fixed;
}

th,
td {
  height: 62px;
  padding: 0 14px;
  border-bottom: 1px solid #edf1f5;
  color: #4f5b6d;
  font-size: 13px;
  text-align: left;
}

th {
  color: #29364a;
  font-weight: 600;
}

th:nth-child(1) {
  width: 70px;
}

th:nth-child(2) {
  width: 220px;
}

th:nth-child(3) {
  width: 110px;
}

th:nth-child(4) {
  width: 110px;
}

th:nth-child(6) {
  width: 65px;
}

th:nth-child(7) {
  width: 90px;
}

th:nth-child(8) {
  width: 145px;
}

th:nth-child(9) {
  width: 150px;
}

tbody tr:hover {
  background: #fafcff;
}

.name-cell {
  overflow: hidden;
  font-weight: 500;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.label-cell,
.intro-cell,
.time-cell {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.type-tag {
  display: inline-block;
  padding: 5px 9px;
  border-radius: 4px;
  white-space: nowrap;
}

.type-tag.tag-platform {
  background: #eaf3ff;
  color: #1677ff;
}

.type-tag.tag-invest {
  background: #fff3e2;
  color: #ee991f;
}

.type-tag.tag-service {
  background: #e9faf8;
  color: #24b6a2;
}

.type-tag.tag-none {
  background: #eef1f5;
  color: #7b8494;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.status i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.status.online i {
  background: #20b875;
}

.status.offline i {
  background: #efa21c;
}

.operation {
  display: flex;
  gap: 7px;
  white-space: nowrap;
}

.operation button {
  padding: 0;
  border: 0;
  background: transparent;
  color: #1677ff;
}

.operation button:hover {
  text-decoration: underline;
}

.operation span {
  color: #d4dbe4;
}

.state-row {
  height: 120px;
  color: #97a1b0;
  text-align: center;
}

.state-row.error {
  color: #ef4f5d;
}

.retry-btn {
  margin-left: 12px;
  padding: 4px 14px;
  border: 1px solid #ef4f5d;
  border-radius: 4px;
  background: white;
  color: #ef4f5d;
}

.action-error,
.modal-error {
  padding: 10px 25px;
  color: #ef4f5d;
  font-size: 13px;
}

.batch-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 17px;
  min-height: 64px;
  padding: 0 25px;
  border-bottom: 1px solid #edf1f5;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 7px;
  min-height: 74px;
  padding: 0 25px;
}

.pagination select {
  width: 105px;
  margin: 0 15px;
}

.pagination button {
  min-width: 38px;
  height: 38px;
  border: 1px solid #dfe5ed;
  border-radius: 5px;
  background: white;
}

.pagination button.active {
  border-color: #1677ff;
  background: #1677ff;
  color: white;
}

.pagination button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.ellipsis {
  padding: 0 4px;
}

.modal-mask {
  position: fixed;
  z-index: 800;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 28, 48, 0.38);
}

.modal {
  width: 650px;
  max-height: 82vh;
  overflow-y: auto;
  border-radius: 10px;
  background: white;
  box-shadow:
    0 25px 80px rgba(20, 40, 70, 0.2);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 62px;
  padding: 0 24px;
  border-bottom: 1px solid #edf1f5;
}

.modal-header h3 {
  margin: 0;
}

.modal-header button {
  border: 0;
  background: transparent;
  color: #8994a4;
  font-size: 24px;
}

.detail-grid,
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 22px;
  padding: 26px;
}

.detail-grid label {
  display: block;
  margin-bottom: 8px;
  color: #8a95a5;
  font-size: 12px;
}

.detail-grid strong {
  color: #3c495c;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.7;
  word-break: break-all;
}

.state-text {
  color: #97a1b0;
  font-size: 14px;
}

.state-text.error {
  color: #ef4f5d;
}

.form-grid label {
  color: #536073;
  font-size: 13px;
}

.form-grid input,
.form-grid select,
.form-grid textarea {
  margin-top: 8px;
}

.full {
  grid-column: 1 / -1;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 17px 24px;
  border-top: 1px solid #edf1f5;
}
</style>
