<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../../api/client'

const router = useRouter()

const STATUS_OPTIONS = [
  { value: 'pending', label: '待处理' },
  { value: 'accepted', label: '已受理' },
  { value: 'confirmed', label: '已确认' },
  { value: 'completed', label: '已完成' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'cancelled', label: '已取消' }
]

const STATUS_META = {
  pending: { label: '待处理', cls: 'pending' },
  accepted: { label: '已受理', cls: 'accepted' },
  confirmed: { label: '已确认', cls: 'confirmed' },
  completed: { label: '已完成', cls: 'completed' },
  rejected: { label: '已拒绝', cls: 'rejected' },
  cancelled: { label: '已取消', cls: 'cancelled' }
}

const TYPE_META = {
  achievement: { label: '成果', cls: 'blue' },
  demand: { label: '需求', cls: 'orange' }
}

const statusLabel = status => STATUS_META[status]?.label || status || '-'
const statusClass = status => STATUS_META[status]?.cls || 'unknown'
const typeLabel = type => TYPE_META[type]?.label || type || '-'
const typeClass = type => TYPE_META[type]?.cls || ''

const fmtTime = v => (v ? String(v).replace('T', ' ').slice(0, 16) : '-')

const truncate = (value, len = 40) => {
  if (!value) return '-'
  const text = String(value)
  return text.length > len ? `${text.slice(0, len)}…` : text
}

const filters = reactive({
  keyword: '',
  status: ''
})

const appliedFilters = reactive({
  keyword: '',
  status: ''
})

const loading = ref(false)
const loadError = ref('')
const rows = ref([])
const total = ref(0)
const totalPages = ref(1)
const currentPage = ref(1)
const pageSize = ref(10)

const fetchList = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const data = await api('/admin/cooperations', {
      params: {
        page: currentPage.value,
        pageSize: pageSize.value,
        status: appliedFilters.status,
        keyword: appliedFilters.keyword.trim()
      }
    })
    rows.value = data.list || []
    total.value = data.total || 0
    totalPages.value = Math.max(1, data.totalPages || Math.ceil(total.value / pageSize.value))
  } catch (err) {
    loadError.value = err.message || '加载失败'
    rows.value = []
    total.value = 0
    totalPages.value = 1
  } finally {
    loading.value = false
  }
}

onMounted(fetchList)

const handleSearch = () => {
  Object.assign(appliedFilters, filters)
  currentPage.value = 1
  fetchList()
}

const handleReset = () => {
  Object.assign(filters, {
    keyword: '',
    status: ''
  })
  Object.assign(appliedFilters, filters)
  currentPage.value = 1
  fetchList()
}

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

const goPage = page => {
  if (page === '...' || page < 1 || page > totalPages.value) return
  if (page === currentPage.value) return

  currentPage.value = page
  fetchList()
}

const handlePageSizeChange = () => {
  currentPage.value = 1
  fetchList()
}

const goDetail = item => {
  router.push('/admin/cooperation/' + item.id)
}
</script>

<template>
  <div class="cooperation-page">

    <section class="filter-card">

      <div class="filter-row">

        <div class="filter-item keyword">

          <label>
            关键词
          </label>

          <input
            v-model="filters.keyword"
            placeholder="请输入留言、双方姓名或目标标题"
            @keyup.enter="handleSearch"
          />

        </div>


        <div class="filter-item">

          <label>
            当前状态
          </label>

          <select v-model="filters.status">

            <option value="">
              全部
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
            @click="handleReset"
          >
            重置
          </button>

        </div>

      </div>

    </section>


    <section class="table-card">

      <table>

        <thead>

          <tr>
            <th>意向 ID</th>
            <th>发起人</th>
            <th>合作目标</th>
            <th>目标持有方</th>
            <th>留言</th>
            <th>状态</th>
            <th>发起时间</th>
            <th>操作</th>
          </tr>

        </thead>

        <tbody v-if="loading">

          <tr>

            <td
              colspan="8"
              class="table-state"
            >
              加载中…
            </td>

          </tr>

        </tbody>


        <tbody v-else-if="loadError">

          <tr>

            <td colspan="8">

              <div class="table-error">

                <span>
                  {{ loadError }}
                </span>

                <button @click="fetchList">
                  重试
                </button>

              </div>

            </td>

          </tr>

        </tbody>


        <tbody v-else-if="!rows.length">

          <tr>

            <td
              colspan="8"
              class="table-state"
            >
              暂无数据
            </td>

          </tr>

        </tbody>


        <tbody v-else>

          <tr
            v-for="item in rows"
            :key="item.id"
          >

            <td>
              {{ item.id }}
            </td>

            <td class="text-ellipsis">
              {{ item.initiatorName || item.initiatorUserNo || '-' }}
            </td>

            <td>

              <div class="target-cell">

                <span
                  class="type-badge"
                  :class="typeClass(item.targetType)"
                >
                  {{ typeLabel(item.targetType) }}
                </span>

                <span
                  class="text-ellipsis"
                  :title="item.targetTitle || ''"
                >
                  {{ item.targetTitle || '-' }}
                </span>

              </div>

            </td>

            <td class="text-ellipsis">
              {{ item.targetOwnerName || item.targetOwnerUserNo || '-' }}
            </td>

            <td
              class="text-ellipsis"
              :title="item.message || ''"
            >
              {{ truncate(item.message, 40) }}
            </td>

            <td>

              <span
                class="status-tag"
                :class="statusClass(item.status)"
              >
                <i></i>

                {{ statusLabel(item.status) }}
              </span>

            </td>

            <td>
              {{ fmtTime(item.createdAt) }}
            </td>

            <td>

              <div class="operation">

                <button @click="goDetail(item)">
                  查看
                </button>

              </div>

            </td>

          </tr>

        </tbody>

      </table>


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
                currentPage ===
                page
            }"
            @click="goPage(page)"
          >
            {{ page }}
          </button>

        </template>


        <button
          :disabled="
            currentPage ===
            totalPages
          "
          @click="goPage(currentPage + 1)"
        >
          ›
        </button>

      </div>

    </section>

  </div>
</template>

<style scoped>
.cooperation-page {
  width: 100%;
}

.filter-card,
.table-card {
  border: 1px solid #e8edf4;
  border-radius: 11px;
  background: #fff;
  box-shadow:
    0 2px 14px
    rgba(40, 72, 110, 0.07);
}

.filter-card {
  padding: 25px 28px;
}

.filter-row {
  display: grid;
  grid-template-columns:
    1.8fr
    1fr
    auto;
  align-items: end;
  gap: 26px;
}

.filter-item label {
  display: block;
  margin-bottom: 9px;
  color: #283447;
  font-size: 14px;
  font-weight: 600;
}

.filter-item input,
.filter-item select {
  width: 100%;
  height: 42px;
  padding: 0 13px;
  outline: none;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  background: white;
}

.filter-item input:focus,
.filter-item select:focus {
  border-color: #1677ff;
}

.filter-actions {
  display: flex;
  gap: 12px;
}

.primary-btn,
.default-btn {
  height: 42px;
  padding: 0 28px;
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
  color: #4d596a;
}

.table-card {
  margin-top: 14px;
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 1180px;
  border-collapse: collapse;
  table-layout: fixed;
}

th,
td {
  height: 64px;
  padding: 0 14px;
  border-bottom: 1px solid #edf1f5;
  color: #4d596a;
  font-size: 13px;
  text-align: left;
}

th {
  color: #273346;
  font-weight: 600;
}

th:nth-child(1) {
  width: 140px;
}

th:nth-child(2) {
  width: 130px;
}

th:nth-child(3) {
  width: 240px;
}

th:nth-child(4) {
  width: 140px;
}

th:nth-child(6) {
  width: 100px;
}

th:nth-child(7) {
  width: 160px;
}

th:nth-child(8) {
  width: 90px;
}

tbody tr:hover {
  background: #fafcff;
}

.text-ellipsis {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.table-state {
  color: #8995a5;
  text-align: center;
}

.table-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  color: #ef5260;
}

.table-error button {
  height: 32px;
  padding: 0 16px;
  border: 1px solid #ef5260;
  border-radius: 5px;
  background: white;
  color: #ef5260;
}

.target-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.target-cell .text-ellipsis {
  flex: 1;
  min-width: 0;
}

.type-badge {
  flex-shrink: 0;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
}

.type-badge.blue {
  background: #eaf3ff;
  color: #1677ff;
}

.type-badge.orange {
  background: #fff5e6;
  color: #ec961d;
}

.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 4px;
}

.status-tag i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.status-tag.pending {
  background: #eaf3ff;
  color: #1677ff;
}

.status-tag.pending i {
  background: #1677ff;
}

.status-tag.accepted {
  background: #e9faf1;
  color: #20b875;
}

.status-tag.accepted i {
  background: #20b875;
}

.status-tag.confirmed {
  background: #f3edff;
  color: #7b5cd6;
}

.status-tag.confirmed i {
  background: #7b5cd6;
}

.status-tag.completed {
  background: #e3f6ec;
  color: #0e8f63;
}

.status-tag.completed i {
  background: #0e8f63;
}

.status-tag.rejected {
  background: #ffecef;
  color: #ef5260;
}

.status-tag.rejected i {
  background: #ef5260;
}

.status-tag.cancelled,
.status-tag.unknown {
  background: #eff1f4;
  color: #768294;
}

.status-tag.cancelled i,
.status-tag.unknown i {
  background: #768294;
}

.operation {
  display: flex;
  align-items: center;
  gap: 7px;
}

.operation button {
  padding: 0;
  border: 0;
  background: transparent;
  color: #1677ff;
}

.operation span {
  color: #d6dde6;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 74px;
}

.pagination select {
  height: 38px;
  margin-left: 15px;
  padding: 0 12px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  background: white;
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
