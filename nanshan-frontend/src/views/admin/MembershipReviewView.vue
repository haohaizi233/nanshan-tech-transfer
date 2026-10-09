<script setup>
import {
  computed,
  onMounted,
  reactive,
  ref,
  watch
} from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../../api/client'
import { confirmDialog, promptDialog } from '../../utils/appDialog.js'

const TABS = [
  { value: 'all', label: '全部' },
  { value: 'organization', label: '机构入驻申请' },
  { value: 'org-admin', label: '机构管理员申请' },
  { value: 'member', label: '成员认证申请' }
]

const route = useRoute()
const router = useRouter()

const STATUS_OPTIONS = [
  { value: 'pending', label: '待审核' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已驳回' }
]

const TYPE_LABELS = {
  university: '高校',
  institute: '科研院所',
  enterprise: '企业',
  service: '服务机构',
  invest: '投资机构'
}

const STATUS_LABELS = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已驳回',
  cancelled: '已取消'
}

const KIND_LABELS = {
  organization: '机构入驻申请',
  'org-admin': '机构管理员申请',
  member: '成员认证申请'
}

const typeLabel = v => TYPE_LABELS[v] || v || '-'

const statusLabel = v => STATUS_LABELS[v] || v || '-'

const kindLabel = v => KIND_LABELS[v] || v || '-'

const fmtTime = v => (v ? String(v).replace('T', ' ').slice(0, 16) : '-')

const activeTab = ref('all')

const filters = reactive({
  status: 'pending'
})

const applied = reactive({
  status: 'pending'
})

const currentPage = ref(1)
const pageSize = ref(10)

const rows = ref([])
const total = ref(0)
const totalPages = ref(1)
const loading = ref(false)
const loadError = ref('')
const actionError = ref('')

const detailVisible = ref(false)
const currentItem = ref(null)

const acting = ref(false)

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

const colCount = computed(() => {
  if (activeTab.value === 'organization') return 9
  if (activeTab.value === 'all') return 7
  return 8
})

function itemKind(item) {
  return item?.applicationKind || activeTab.value
}

function listApi() {
  if (activeTab.value === 'all') return '/admin/certification-applications'
  if (activeTab.value === 'organization') return '/admin/organization-applications'
  if (activeTab.value === 'org-admin') return '/admin/organization-admin-applications'
  return '/admin/organization-membership-applications'
}

function actionApi(item, action) {
  const kind = itemKind(item)
  if (kind === 'organization') return `/admin/organization-applications/${item.id}/${action}`
  if (kind === 'org-admin') return `/admin/organization-admin-applications/${item.id}/${action}`
  return `/admin/organization-membership-applications/${item.id}/${action}`
}

async function loadList() {
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  try {
    const data = await api(listApi(), {
      params: {
        page: currentPage.value,
        pageSize: pageSize.value,
        status: applied.status
      }
    })
    rows.value = data.list || []
    total.value = data.total || 0
    totalPages.value = Math.max(1, Math.ceil(total.value / pageSize.value))
  } catch (err) {
    rows.value = []
    total.value = 0
    totalPages.value = 1
    loadError.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  const requestedTab = String(route.query.tab || '')
  if (TABS.some(item => item.value === requestedTab)) activeTab.value = requestedTab
  loadList()
})

watch(() => route.query.tab, (tab) => {
  if (!TABS.some(item => item.value === tab) || activeTab.value === tab) return
  activeTab.value = tab
  currentPage.value = 1
  loadList()
})

// 反向同步：tab 变化时写回 query，保证刷新/分享链接与当前 tab 一致。
watch(activeTab, (tab) => {
  if (route.query.tab === tab) return
  router.replace({ query: { ...route.query, tab } }).catch(() => {
    // 导航被中止（如重复点击）时忽略，避免未捕获 rejection。
  })
})

const switchTab = tab => {
  if (activeTab.value === tab) return
  activeTab.value = tab
  currentPage.value = 1
  loadList()
}

const search = () => {
  Object.assign(applied, filters)
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

const openDetail = item => {
  currentItem.value = item
  detailVisible.value = true
}

const closeDetail = () => {
  detailVisible.value = false
  currentItem.value = null
}

const approve = async item => {
  const kind = itemKind(item)
  const label = kind === 'organization'
    ? `通过机构「${item.requestedName}」的入驻申请（申请人 ${item.userNo}，通过后该机构上架且申请人成为其机构管理员）`
    : kind === 'org-admin'
      ? `通过用户 ${item.userNo} 成为「${item.orgName}」机构管理员的申请`
      : `通过用户 ${item.userNo} 加入「${item.orgName}」的成员认证申请`
  const ok = await confirmDialog({
    title: '通过申请',
    message: `确认${label}？`,
    confirmText: '确认通过',
    tone: 'primary',
  })
  if (!ok) return
  acting.value = true
  actionError.value = ''
  try {
    const path = actionApi(item, 'approve')
    await api(path, {
      method: 'POST',
      body: { version: item.version }
    })
    closeDetail()
    loadList()
  } catch (err) {
    actionError.value = err.message || '操作失败'
  } finally {
    acting.value = false
  }
}

const reject = async item => {
  const reason = await promptDialog({
    title: '驳回申请',
    message: '驳回申请必须填写原因。',
    placeholder: '请填写驳回原因',
    confirmText: '确认驳回',
  })
  if (reason == null) return
  const trimmed = reason.trim()
  if (!trimmed) {
    actionError.value = '驳回申请必须填写原因'
    return
  }
  acting.value = true
  actionError.value = ''
  try {
    const path = actionApi(item, 'reject')
    await api(path, {
      method: 'POST',
      body: { version: item.version, reason: trimmed }
    })
    closeDetail()
    loadList()
  } catch (err) {
    actionError.value = err.message || '操作失败'
  } finally {
    acting.value = false
  }
}
</script>

<template>
  <div class="review-page">
    <section class="filter-card">
      <div class="toolbar">
        <button
          v-for="tab in TABS"
          :key="tab.value"
          :class="['tab-btn', { active: activeTab === tab.value }]"
          @click="switchTab(tab.value)"
        >
          {{ tab.label }}
        </button>

        <div class="filter-item">
          <label>状态</label>
          <select v-model="filters.status" @change="search">
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

        <button
          class="primary-btn"
          @click="search"
        >
          查询
        </button>
      </div>

      <div
        v-if="actionError"
        class="action-error"
      >
        {{ actionError }}
      </div>
    </section>

    <section class="table-card">
      <table :class="`review-table tab-${activeTab}`">
        <thead>
          <tr v-if="activeTab === 'all'">
            <th>ID</th>
            <th>申请类型</th>
            <th>申请人</th>
            <th>机构</th>
            <th>状态</th>
            <th>申请时间</th>
            <th>操作</th>
          </tr>

          <tr v-else-if="activeTab === 'organization'">
            <th>ID</th>
            <th>申请人</th>
            <th>机构名称</th>
            <th>机构类型</th>
            <th>地区</th>
            <th>联系人</th>
            <th>状态</th>
            <th>申请时间</th>
            <th>操作</th>
          </tr>

          <tr v-else>
            <th>ID</th>
            <th>申请人</th>
            <th>目标机构</th>
            <th>姓名</th>
            <th>部门/职务</th>
            <th>状态</th>
            <th>申请时间</th>
            <th>操作</th>
          </tr>
        </thead>

        <tbody>
          <template v-if="activeTab === 'all'">
            <tr
              v-for="item in rows"
              :key="`${item.applicationKind}-${item.id}`"
            >
              <td>{{ item.id }}</td>

              <td>{{ kindLabel(item.applicationKind) }}</td>

              <td>{{ item.userNo }}</td>

              <td
                class="org-name"
                :title="item.orgName || item.requestedName"
              >
                {{ item.orgName || item.requestedName || '-' }}
              </td>

              <td>
                <span :class="['status-tag', item.status]">
                  {{ statusLabel(item.status) }}
                </span>
              </td>

              <td>{{ fmtTime(item.createdAt) }}</td>

              <td>
                <div class="operation">
                  <button @click="openDetail(item)">
                    查看
                  </button>

                  <button
                    v-if="item.status === 'pending'"
                    @click="approve(item)"
                  >
                    通过
                  </button>

                  <button
                    v-if="item.status === 'pending'"
                    class="danger"
                    @click="reject(item)"
                  >
                    驳回
                  </button>
                </div>
              </td>
            </tr>
          </template>

          <template v-else-if="activeTab === 'organization'">
            <tr
              v-for="item in rows"
              :key="item.id"
            >
              <td>{{ item.id }}</td>

              <td>{{ item.userNo }}</td>

              <td
                class="org-name"
                :title="item.requestedName"
              >
                {{ item.requestedName }}
              </td>

              <td>{{ typeLabel(item.requestedType) }}</td>

              <td>{{ item.region || '-' }}</td>

              <td>
                {{ item.contactName || '-' }}
                <br>
                {{ item.contactPhone || '-' }}
              </td>

              <td>
                <span :class="['status-tag', item.status]">
                  {{ statusLabel(item.status) }}
                </span>
              </td>

              <td>{{ fmtTime(item.createdAt) }}</td>

              <td>
                <div class="operation">
                  <button @click="openDetail(item)">
                    查看
                  </button>

                  <button
                    v-if="item.status === 'pending'"
                    @click="approve(item)"
                  >
                    通过
                  </button>

                  <button
                    v-if="item.status === 'pending'"
                    class="danger"
                    @click="reject(item)"
                  >
                    驳回
                  </button>
                </div>
              </td>
            </tr>
          </template>

          <template v-else>
            <tr
              v-for="item in rows"
              :key="item.id"
            >
              <td>{{ item.id }}</td>

              <td>{{ item.userNo }}</td>

              <td
                class="org-name"
                :title="item.orgName"
              >
                {{ item.orgName }}
              </td>

              <td>{{ item.realName || '-' }}</td>

              <td>
                {{ item.department || '-' }}
                <br>
                {{ item.title || '-' }}
              </td>

              <td>
                <span :class="['status-tag', item.status]">
                  {{ statusLabel(item.status) }}
                </span>
              </td>

              <td>{{ fmtTime(item.createdAt) }}</td>

              <td>
                <div class="operation">
                  <button @click="openDetail(item)">
                    查看
                  </button>

                  <button
                    v-if="item.status === 'pending'"
                    @click="approve(item)"
                  >
                    通过
                  </button>

                  <button
                    v-if="item.status === 'pending'"
                    class="danger"
                    @click="reject(item)"
                  >
                    驳回
                  </button>
                </div>
              </td>
            </tr>
          </template>

          <tr v-if="loading">
            <td
              :colspan="colCount"
              class="state-row"
            >
              加载中…
            </td>
          </tr>

          <tr v-else-if="loadError">
            <td
              :colspan="colCount"
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
              :colspan="colCount"
              class="state-row"
            >
              暂无符合条件的申请
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
      v-if="detailVisible"
      class="modal-mask"
      @click.self="closeDetail"
    >
      <div class="modal">
        <div class="modal-header">
          <h3>{{ kindLabel(itemKind(currentItem)) }}详情</h3>

          <button @click="closeDetail">
            ×
          </button>
        </div>

        <div class="detail-grid">
          <div>
            <label>申请ID</label>
            <strong>{{ currentItem.id }}</strong>
          </div>

          <div>
            <label>申请人</label>
            <strong>{{ currentItem.userNo }}</strong>
          </div>

          <template v-if="itemKind(currentItem) === 'organization'">
            <div class="full">
              <label>机构名称</label>
              <strong>{{ currentItem.requestedName }}</strong>
            </div>

            <div>
              <label>机构类型</label>
              <strong>{{ typeLabel(currentItem.requestedType) }}</strong>
            </div>

            <div>
              <label>地区</label>
              <strong>{{ currentItem.region || '-' }}</strong>
            </div>

            <div>
              <label>统一社会信用代码</label>
              <strong>{{ currentItem.creditCode || '-' }}</strong>
            </div>

            <div>
              <label>官网</label>
              <strong>{{ currentItem.website || '-' }}</strong>
            </div>

            <div>
              <label>联系人</label>
              <strong>{{ currentItem.contactName || '-' }}</strong>
            </div>

            <div>
              <label>联系电话</label>
              <strong>{{ currentItem.contactPhone || '-' }}</strong>
            </div>

            <div>
              <label>联系邮箱</label>
              <strong>{{ currentItem.contactEmail || '-' }}</strong>
            </div>

            <div class="full">
              <label>地址</label>
              <strong>{{ currentItem.address || '-' }}</strong>
            </div>

            <div class="full">
              <label>证明材料说明</label>
              <strong>{{ currentItem.proofMaterial || '-' }}</strong>
            </div>
          </template>

          <template v-else>
            <div class="full">
              <label>目标机构</label>
              <strong>{{ currentItem.orgName }}</strong>
            </div>

            <div>
              <label>真实姓名</label>
              <strong>{{ currentItem.realName || '-' }}</strong>
            </div>

            <div>
              <label>工作邮箱</label>
              <strong>{{ currentItem.workEmail || '-' }}</strong>
            </div>

            <div>
              <label>部门</label>
              <strong>{{ currentItem.department || '-' }}</strong>
            </div>

            <div>
              <label>职务</label>
              <strong>{{ currentItem.title || '-' }}</strong>
            </div>

            <div class="full">
              <label>{{ itemKind(currentItem) === 'member' ? '申请说明' : '申请理由' }}</label>
              <strong>{{ currentItem.applyNote || currentItem.reason || '-' }}</strong>
            </div>

            <div class="full">
              <label>证明材料说明</label>
              <strong>{{ currentItem.proofMaterial || '-' }}</strong>
            </div>
          </template>

          <div>
            <label>状态</label>
            <strong>{{ statusLabel(currentItem.status) }}</strong>
          </div>

          <div>
            <label>申请时间</label>
            <strong>{{ fmtTime(currentItem.createdAt) }}</strong>
          </div>

          <div v-if="currentItem.reviewedAt">
            <label>审核时间</label>
            <strong>{{ fmtTime(currentItem.reviewedAt) }}</strong>
          </div>

          <div
            v-if="currentItem.reviewReason"
            class="full"
          >
            <label>审核意见</label>
            <strong>{{ currentItem.reviewReason }}</strong>
          </div>
        </div>

        <div class="modal-footer">
          <button
            v-if="currentItem.status === 'pending'"
            class="primary-btn"
            :disabled="acting"
            @click="approve(currentItem)"
          >
            通过
          </button>

          <button
            v-if="currentItem.status === 'pending'"
            class="danger-btn"
            :disabled="acting"
            @click="reject(currentItem)"
          >
            驳回
          </button>

          <button
            class="default-btn"
            @click="closeDetail"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.review-page {
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
  padding: 20px 27px 25px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  overflow-x: auto;
}

.tab-btn {
  height: 42px;
  padding: 0 16px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  background: white;
  color: #536073;
  white-space: nowrap;
}

.tab-btn.active {
  border-color: #1677ff;
  background: #1677ff;
  color: white;
}

.filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-item label {
  color: #283447;
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
}

.filter-item select {
  width: 140px;
  height: 42px;
  padding: 0 13px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  outline: none;
  background: white;
}

.primary-btn,
.default-btn,
.danger-btn {
  height: 42px;
  padding: 0 23px;
  border-radius: 5px;
  white-space: nowrap;
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

.danger-btn {
  border: 1px solid #ef4f5d;
  background: #ef4f5d;
  color: white;
}

.action-error {
  margin-top: 12px;
  color: #ef4f5d;
  font-size: 13px;
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
  width: 72px;
}

th:nth-child(2) {
  width: 140px;
}

th:last-child {
  width: 150px;
}

.tab-all th:nth-child(3),
.tab-organization th:nth-child(2),
.tab-org-admin th:nth-child(2),
.tab-member th:nth-child(2) {
  width: 120px;
}

.tab-all th:nth-child(5),
.tab-organization th:nth-child(7),
.tab-org-admin th:nth-child(6),
.tab-member th:nth-child(6) {
  width: 90px;
}

.tab-all th:nth-child(6),
.tab-organization th:nth-child(8),
.tab-org-admin th:nth-child(7),
.tab-member th:nth-child(7) {
  width: 160px;
}

.tab-org-admin th:nth-child(4),
.tab-member th:nth-child(4) {
  width: 100px;
}

.tab-org-admin th:nth-child(5),
.tab-member th:nth-child(5) {
  width: 130px;
}

tbody tr:hover {
  background: #fafcff;
}

.org-name {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.status-tag {
  display: inline-flex;
  padding: 5px 9px;
  border-radius: 4px;
  white-space: nowrap;
}

.status-tag.pending {
  background: #fff4e5;
  color: #f08c00;
}

.status-tag.approved {
  background: #e9faf1;
  color: #20b875;
}

.status-tag.rejected,
.status-tag.cancelled {
  background: #eff1f4;
  color: #727e90;
}

.operation {
  display: flex;
  gap: 10px;
}

.operation button {
  padding: 0;
  border: 0;
  background: transparent;
  color: #1677ff;
}

.operation button.danger {
  color: #ef4f5d;
}

.operation button:hover {
  text-decoration: underline;
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
  height: 42px;
  margin: 0 15px;
  padding: 0 13px;
  border: 1px solid #dfe5ed;
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
  background:
    rgba(15, 28, 48, 0.38);
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

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 22px;
  padding: 26px;
}

.detail-grid label {
  display: block;
  margin-bottom: 8px;
  color: #8994a4;
  font-size: 12px;
}

.detail-grid strong {
  color: #3c495c;
  font-weight: 500;
  word-break: break-all;
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
