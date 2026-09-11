<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

import { api } from '../../api/client'

const fmtTime = (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '-')

const ACTION_LABELS = {
  'achievement.approve': '通过成果审核',
  'achievement.reject': '驳回成果',
  'achievement.submit': '提交成果',
  'achievement.create': '创建成果',
  'achievement.update': '更新成果',
  'achievement.offline': '下架成果',
  'demand.approve': '通过需求审核',
  'demand.reject': '驳回需求',
  'demand.submit': '提交需求',
  'demand.create': '创建需求',
  'demand.update': '更新需求',
  'demand.cancel': '取消需求',
  'demand.close': '关闭需求',
  'institution.create': '新增机构',
  'institution.update': '更新机构',
  'institution.online': '上架机构',
  'institution.offline': '下架机构'
}

const RESOURCE_TYPE_LABELS = {
  achievement: '成果',
  demand: '需求',
  institution: '机构',
  cooperation_intent: '合作意向',
  user: '用户'
}

const targetTypeOptions = [
  { value: 'achievement', label: '成果' },
  { value: 'demand', label: '需求' },
  { value: 'institution', label: '机构' },
  { value: 'cooperation_intent', label: '合作意向' },
  { value: 'user', label: '用户' }
]

const filters = reactive({
  targetType: '',
  actorUserId: '',
  requestId: ''
})

const applied = reactive({
  targetType: '',
  actorUserId: '',
  requestId: ''
})

const tableData = ref([])
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
const totalPages = ref(1)
const loading = ref(false)
const loadError = ref('')

const fetchLogs = async () => {
  loading.value = true
  loadError.value = ''

  try {
    const data = await api('/admin/audit-logs', {
      params: {
        page: currentPage.value,
        pageSize: pageSize.value,
        targetType: applied.targetType,
        actorUserId: applied.actorUserId,
        requestId: applied.requestId
      }
    })

    tableData.value = data?.list ?? []
    total.value = data?.total ?? 0
    totalPages.value = Math.max(
      1,
      data?.totalPages ?? Math.ceil(total.value / pageSize.value)
    )
  } catch (error) {
    tableData.value = []
    total.value = 0
    totalPages.value = 1
    loadError.value = error.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(fetchLogs)

const search = () => {
  Object.assign(applied, {
    targetType: filters.targetType,
    actorUserId: filters.actorUserId.trim(),
    requestId: filters.requestId.trim()
  })

  currentPage.value = 1
  fetchLogs()
}

const reset = () => {
  Object.assign(filters, {
    targetType: '',
    actorUserId: '',
    requestId: ''
  })

  Object.assign(applied, {
    targetType: '',
    actorUserId: '',
    requestId: ''
  })

  currentPage.value = 1
  fetchLogs()
}

const goPage = (page) => {
  if (page < 1 || page > totalPages.value || page === currentPage.value) {
    return
  }

  currentPage.value = page
  fetchLogs()
}

const changePageSize = () => {
  currentPage.value = 1
  fetchLogs()
}

const pages = computed(() => {
  const count = totalPages.value

  if (count <= 7) {
    return Array.from(
      { length: count },
      (_, index) => index + 1
    )
  }

  const current = currentPage.value
  const start = Math.max(1, Math.min(current - 2, count - 4))
  const end = Math.min(count, start + 4)

  const list = []

  if (start > 1) {
    list.push(1)

    if (start > 2) {
      list.push('...')
    }
  }

  for (let page = start; page <= end; page += 1) {
    list.push(page)
  }

  if (end < count) {
    if (end < count - 1) {
      list.push('...')
    }

    list.push(count)
  }

  return list
})

const actionText = (action) => ACTION_LABELS[action] || action || '-'

const resourceTypeText = (type) => RESOURCE_TYPE_LABELS[type] || type || '-'

const displayText = (value) => {
  if (value === null || value === undefined || value === '') {
    return '-'
  }

  if (typeof value === 'string') {
    return value
  }

  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

const cellTitle = (value) => {
  const text = displayText(value)

  return text === '-' ? '' : text
}
</script>

<template>
  <div class="log-page">
    <section class="filter-card">
      <div class="filter-row">
        <div class="filter-item">
          <label>
            目标类型
          </label>

          <select v-model="filters.targetType" @change="search">
            <option value="">
              全部
            </option>

            <option
              v-for="item in targetTypeOptions"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }}
            </option>
          </select>
        </div>

        <div class="filter-item">
          <label>
            操作人ID
          </label>

          <input
            v-model="filters.actorUserId"
            placeholder="请输入操作人用户ID"
            @keyup.enter="search"
          />
        </div>

        <div class="filter-item">
          <label>
            RequestId
          </label>

          <input
            v-model="filters.requestId"
            placeholder="请输入RequestId"
            @keyup.enter="search"
          />
        </div>

        <div class="actions">
          <button
            class="primary-btn"
            @click="search"
          >
            查询
          </button>

          <button
            class="default-btn"
            @click="reset"
          >
            重置
          </button>
        </div>
      </div>
    </section>

    <section class="table-card">
      <table>
        <colgroup>
          <col class="col-id">
          <col class="col-actor">
          <col class="col-action">
          <col class="col-type">
          <col class="col-target">
          <col class="col-details">
          <col class="col-request">
          <col class="col-time">
        </colgroup>

        <thead>
          <tr>
            <th>ID</th>
            <th>操作人</th>
            <th>动作</th>
            <th>目标类型</th>
            <th>目标ID</th>
            <th>详情</th>
            <th>RequestId</th>
            <th>时间</th>
          </tr>
        </thead>

        <tbody>
          <tr v-if="loading">
            <td
              colspan="8"
              class="table-state"
            >
              加载中…
            </td>
          </tr>

          <tr v-else-if="loadError">
            <td
              colspan="8"
              class="table-state error"
            >
              <span>{{ loadError }}</span>

              <button
                type="button"
                @click="fetchLogs"
              >
                重试
              </button>
            </td>
          </tr>

          <tr v-else-if="!tableData.length">
            <td
              colspan="8"
              class="table-state"
            >
              暂无日志
            </td>
          </tr>

          <template v-else>
            <tr
              v-for="row in tableData"
              :key="row.id"
            >
              <td :title="cellTitle(row.id)">
                {{ row.id }}
              </td>

              <td :title="cellTitle(row.actorUserNo)">
                {{ row.actorUserNo || '-' }}
              </td>

              <td :title="cellTitle(row.action)">
                {{ actionText(row.action) }}
              </td>

              <td :title="cellTitle(row.resourceType)">
                {{ resourceTypeText(row.resourceType) }}
              </td>

              <td :title="cellTitle(row.resourceId)">
                {{ row.resourceId ?? '-' }}
              </td>

              <td :title="cellTitle(row.details)">
                {{ displayText(row.details) }}
              </td>

              <td :title="cellTitle(row.requestId)">
                {{ row.requestId || '-' }}
              </td>

              <td :title="cellTitle(fmtTime(row.createdAt))">
                {{ fmtTime(row.createdAt) }}
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <div class="pagination">
        <span>
          共 {{ total }} 条
        </span>

        <select
          v-model="pageSize"
          @change="changePageSize"
        >
          <option :value="10">
            10条/页
          </option>

          <option :value="20">
            20条/页
          </option>
        </select>

        <button
          :disabled="currentPage === 1"
          @click="goPage(currentPage - 1)"
        >
          ‹
        </button>

        <template
          v-for="(page, index) in pages"
          :key="`${page}-${index}`"
        >
          <span
            v-if="page === '...'"
          >
            ...
          </span>

          <button
            v-else
            :class="{
              active:
                currentPage === page
            }"
            @click="goPage(page)"
          >
            {{ page }}
          </button>
        </template>

        <button
          :disabled="currentPage === totalPages"
          @click="goPage(currentPage + 1)"
        >
          ›
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.log-page {
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
  padding: 25px 27px;
}

.filter-row {
  display: grid;
  grid-template-columns:
    0.9fr
    1fr
    1.1fr
    auto;
  align-items: end;
  gap: 24px;
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
.pagination select {
  width: 100%;
  height: 42px;
  padding: 0 13px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  outline: none;
  background: white;
}

.actions {
  display: flex;
  gap: 11px;
}

.primary-btn,
.default-btn {
  height: 42px;
  padding: 0 23px;
  border-radius: 5px;
}

.primary-btn {
  border: 1px solid #1677ff;
  background: #1677ff;
  color: white;
}

.default-btn {
  border: 1px solid #dce4ee;
  background: white;
  color: #536073;
}

.table-card {
  margin-top: 14px;
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 1100px;
  border-collapse: collapse;
  table-layout: fixed;
}

.col-id {
  width: 68px;
}

.col-actor {
  width: 118px;
}

.col-action {
  width: 210px;
}

.col-type {
  width: 84px;
}

.col-target {
  width: 76px;
}

.col-details {
  width: 36%;
}

.col-request {
  width: 20%;
}

.col-time {
  width: 148px;
}

th,
td {
  height: 56px;
  padding: 0 12px;
  border-bottom: 1px solid #edf1f5;
  color: #4d596a;
  font-size: 13px;
  text-align: left;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

th {
  color: #273346;
  font-weight: 600;
}

tbody tr:hover {
  background: #fafcff;
}

.table-state {
  height: 140px;
  overflow: visible;
  color: #929dab;
  font-size: 13px;
  text-align: center;
  white-space: normal;
  text-overflow: clip;
}

.table-state.error {
  color: #e5484d;
}

.table-state.error button {
  height: 30px;
  margin-left: 12px;
  padding: 0 16px;
  border: 1px solid #e5484d;
  border-radius: 5px;
  background: white;
  color: #e5484d;
  font-size: 12px;
}

.table-state.error button:hover {
  background: #e5484d;
  color: white;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 7px;
  min-height: 78px;
  padding: 0 26px;
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
</style>
