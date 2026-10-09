<script setup>
import {
  computed,
  onMounted,
  reactive,
  ref
} from 'vue'

import { api } from '../../api/client'
import { alertDialog, confirmDialog, promptDialog } from '../../utils/appDialog.js'
import { useAbortable } from '../../api/useAbortable'
import { useAuthStore } from '../../stores/auth.js'

const { run: runApi } = useAbortable()
const authStore = useAuthStore()

const STATUS_OPTIONS = [
  { value: 'active', label: '正常' },
  { value: 'disabled', label: '禁用' }
]

const USER_TYPE_LABELS = {
  investor: '投资人',
  researcher: '科研人员',
  enterprise: '企业用户',
  org: '机构用户'
}

const typeLabel = v => USER_TYPE_LABELS[v] || v || '未填写'

const isPlatformAdmin = computed(() => (authStore.user?.roles || []).includes('admin'))

const membershipText = user => (user.organizationMemberships || [])
  .map(m => `${m.orgName}（${m.role === 'admin' ? '管理员' : '成员'}）`)
  .join('；')

const fmtTime = v => (v ? String(v).replace('T', ' ').slice(0, 16) : '-')

const filters = reactive({
  keyword: '',
  status: ''
})

const applied = reactive({
  keyword: '',
  status: ''
})

const currentPage = ref(1)
const pageSize = ref(10)

const rows = ref([])
const total = ref(0)
const totalPages = ref(1)
const loading = ref(false)
const loadError = ref('')

const modalVisible = ref(false)
const modalLoading = ref(false)
const modalError = ref('')
const modalActionError = ref('')
const currentUser = ref(null)

const exporting = ref(false)

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
    const data = await runApi('/admin/users', {
      params: {
        page: currentPage.value,
        pageSize: pageSize.value,
        keyword: applied.keyword.trim(),
        status: applied.status
      }
    })
    if (data === null) return // 被取消（快速翻页/导航/卸载）
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

const search = () => {
  Object.assign(applied, filters)
  currentPage.value = 1
  loadList()
}

const reset = () => {
  Object.assign(filters, { keyword: '', status: '' })
  Object.assign(applied, { keyword: '', status: '' })
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

const openView = async user => {
  modalVisible.value = true
  modalLoading.value = true
  modalError.value = ''
  try {
    currentUser.value = await api(`/admin/users/${user.userId}`)
  } catch (err) {
    currentUser.value = null
    modalError.value = err.message || '加载失败'
  } finally {
    modalLoading.value = false
  }
}

const closeModal = () => {
  modalVisible.value = false
  modalActionError.value = ''
}

const reloadDetail = async () => {
  const id = currentUser.value?.userId
  if (!id) return
  currentUser.value = await api(`/admin/users/${id}`)
  loadList()
}

const grantAdmin = async m => {
  const ok = await confirmDialog({
    title: '设置机构管理员',
    message: `确认将该成员设为「${m.orgName}」的机构管理员？`,
    confirmText: '确认设置',
    tone: 'primary',
  })
  if (!ok) return
  modalActionError.value = ''
  try {
    await api(`/admin/organization-memberships/${m.id}/grant-admin`, {
      method: 'POST',
      body: { version: m.version }
    })
    await reloadDetail()
  } catch (err) {
    modalActionError.value = err.message || '操作失败'
  }
}

const revokeAdmin = async m => {
  const reason = await promptDialog({
    title: '撤销机构管理员',
    message: `确认撤销「${m.orgName}」的机构管理员身份？该操作会同时取消其机构认证，而不是降为普通成员。`,
    placeholder: '请填写撤销原因',
    confirmText: '确认撤销',
  })
  if (reason == null) return
  const trimmed = reason.trim()
  if (!trimmed) {
    modalActionError.value = '撤销机构管理员必须填写原因'
    return
  }
  modalActionError.value = ''
  try {
    await api(`/admin/organization-memberships/${m.id}/revoke-admin`, {
      method: 'POST',
      body: { version: m.version, reason: trimmed }
    })
    await reloadDetail()
  } catch (err) {
    modalActionError.value = err.message || '操作失败'
  }
}

const escapeCsv = value => `"${String(value ?? '').replaceAll('"', '""')}"`

const exportData = async () => {
  exporting.value = true
  try {
    const all = []
    for (let page = 1; page <= 20; page++) {
      const data = await api('/admin/users', {
        params: {
          page,
          pageSize: 50,
          keyword: applied.keyword.trim(),
          status: applied.status
        }
      })
      all.push(...(data.list || []))
      if (page >= (data.totalPages || 1)) break
    }

    if (page >= 20) {
      await alertDialog({
        title: '导出提示',
        message: '导出数据超过1000条上限，仅导出前1000条。如需完整数据请缩小筛选范围或联系管理员。',
      })
    }

    const csv = [
      ['ID', '用户编号', '姓名', '用户类型', '手机号', '邮箱', '所属机构', '职务', '认证机构', '角色', '状态', '注册时间'],
      ...all.map(user => [
        user.userId,
        user.userNo,
        user.displayName,
        typeLabel(user.userType),
        user.phone,
        user.email,
        user.orgName,
        user.orgTitle,
        membershipText(user),
        (user.roles || []).join('/'),
        user.status === 'active' ? '正常' : user.status,
        fmtTime(user.createdAt)
      ])
    ].map(row => row.map(escapeCsv).join(',')).join('\n')

    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '用户列表.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    loadError.value = err.message || '导出失败'
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="user-page">
    <section class="filter-card">
      <div class="filter-row">
        <div class="filter-item keyword">
          <label>关键词</label>
          <input
            v-model="filters.keyword"
            placeholder="请输入用户编号/姓名/机构名称"
            @keyup.enter="search"
          />
        </div>

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

        <div class="actions">
          <button
            type="button"
            class="primary-btn"
            @click="search"
          >
            查询
          </button>

          <button
            type="button"
            class="default-btn"
            @click="reset"
          >
            重置
          </button>

          <button
            type="button"
            class="outline-btn"
            :disabled="exporting"
            @click="exportData"
          >
            {{ exporting ? '导出中…' : '⇩ 导出' }}
          </button>
        </div>
      </div>
    </section>

    <section class="table-card">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>用户编号</th>
            <th>姓名</th>
            <th>用户类型</th>
            <th>手机号</th>
            <th>所属企业/单位</th>
            <th>认证机构</th>
            <th>角色</th>
            <th>状态</th>
            <th>注册时间</th>
            <th>操作</th>
          </tr>
        </thead>

        <tbody>
          <tr
            v-for="user in rows"
            :key="user.userId"
          >
            <td>{{ user.userId }}</td>

            <td>{{ user.userNo }}</td>

            <td>{{ user.displayName || '-' }}</td>

            <td>
              <span class="user-type">
                {{ typeLabel(user.userType) }}
              </span>
            </td>

            <td>{{ user.phone || '-' }}</td>

            <td
              class="organization"
              :title="user.orgName"
            >
              {{ user.orgName || '-' }}
            </td>

            <td class="memberships">
              <template v-if="(user.organizationMemberships || []).length">
                <span
                  v-for="m in user.organizationMemberships"
                  :key="m.id"
                  class="membership-tag"
                  :class="{ admin: m.role === 'admin' }"
                  :title="m.orgName"
                >
                  {{ m.orgName }}{{ m.role === 'admin' ? '·管理员' : '' }}
                </span>
              </template>

              <template v-else>
                -
              </template>
            </td>

            <td>{{ (user.roles || []).join(' / ') || '-' }}</td>

            <td>
              <span
                class="user-status"
                :class="user.status === 'active' ? '正常' : '禁用'"
              >
                {{ user.status === 'active' ? '正常' : user.status }}
              </span>
            </td>

            <td>{{ fmtTime(user.createdAt) }}</td>

            <td>
              <div class="operation">
                <button type="button" @click="openView(user)">
                  查看
                </button>
              </div>
            </td>
          </tr>

          <tr v-if="loading">
            <td
              colspan="11"
              class="state-row"
            >
              加载中…
            </td>
          </tr>

          <tr v-else-if="loadError">
            <td
              colspan="11"
              class="state-row error"
            >
              {{ loadError }}

              <button
                type="button"
                class="retry-btn"
                @click="loadList"
              >
                重试
              </button>
            </td>
          </tr>

          <tr v-else-if="rows.length === 0">
            <td
              colspan="11"
              class="state-row"
            >
              暂无符合条件的用户
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
          type="button"
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
            type="button"
            :class="{ active: currentPage === page }"
            @click="changePage(page)"
          >
            {{ page }}
          </button>
        </template>

        <button
          type="button"
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
          <h3>用户详情</h3>

          <button type="button" @click="closeModal">
            ×
          </button>
        </div>

        <div class="detail-grid">
          <div
            v-if="modalLoading"
            class="full state-text"
          >
            加载中…
          </div>

          <div
            v-else-if="modalError"
            class="full state-text error"
          >
            {{ modalError }}
          </div>

          <template v-else-if="currentUser">
            <div>
              <label>用户ID</label>
              <strong>{{ currentUser.userId }}</strong>
            </div>

            <div>
              <label>用户编号</label>
              <strong>{{ currentUser.userNo }}</strong>
            </div>

            <div>
              <label>姓名</label>
              <strong>{{ currentUser.displayName || '-' }}</strong>
            </div>

            <div>
              <label>用户类型</label>
              <strong>{{ typeLabel(currentUser.userType) }}</strong>
            </div>

            <div>
              <label>手机号</label>
              <strong>{{ currentUser.phone || '-' }}</strong>
            </div>

            <div>
              <label>邮箱</label>
              <strong>{{ currentUser.email || '-' }}</strong>
            </div>

            <div class="full">
              <label>所属单位</label>
              <strong>{{ currentUser.orgName || '-' }}{{ currentUser.orgTitle ? `（${currentUser.orgTitle}）` : '' }}</strong>
            </div>

            <div class="full">
              <label>机构认证</label>

              <div
                v-if="(currentUser.organizationMemberships || []).length"
                class="membership-list"
              >
                <div
                  v-for="m in currentUser.organizationMemberships"
                  :key="m.id"
                  class="membership-row"
                >
                  <span class="membership-tag">
                    {{ m.orgName }}
                  </span>

                  <span
                    class="membership-tag"
                    :class="{ admin: m.role === 'admin' }"
                  >
                    {{ m.role === 'admin' ? '机构管理员' : '认证成员' }}
                  </span>

                  <button
                    v-if="isPlatformAdmin && m.role === 'member'"
                    type="button"
                    class="link-btn"
                    @click="grantAdmin(m)"
                  >
                    设为机构管理员
                  </button>

                  <button
                    v-else-if="isPlatformAdmin && m.role === 'admin'"
                    type="button"
                    class="link-btn danger"
                    @click="revokeAdmin(m)"
                  >
                    撤销机构管理员
                  </button>
                </div>
              </div>

              <strong v-else>未认证</strong>

              <div
                v-if="modalActionError"
                class="action-error"
              >
                {{ modalActionError }}
              </div>
            </div>

            <div>
              <label>角色</label>
              <strong>{{ (currentUser.roles || []).join(' / ') || '-' }}</strong>
            </div>

            <div>
              <label>注册时间</label>
              <strong>{{ fmtTime(currentUser.createdAt) }}</strong>
            </div>

            <div class="full">
              <label>业务统计</label>

              <div class="stat-boxes">
                <div class="stat-box">
                  <strong>{{ currentUser.statistics?.achievementCount ?? 0 }}</strong>
                  <span>发布成果</span>
                </div>

                <div class="stat-box">
                  <strong>{{ currentUser.statistics?.demandCount ?? 0 }}</strong>
                  <span>发布需求</span>
                </div>

                <div class="stat-box">
                  <strong>{{ currentUser.statistics?.cooperationCount ?? 0 }}</strong>
                  <span>合作意向</span>
                </div>

                <div class="stat-box">
                  <strong>{{ currentUser.statistics?.favoriteCount ?? 0 }}</strong>
                  <span>收藏</span>
                </div>
              </div>
            </div>
          </template>
        </div>

        <div class="modal-footer">
          <button
            type="button"
            class="default-btn"
            @click="closeModal"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.user-page {
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
    1.4fr
    0.8fr
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
.default-btn,
.outline-btn {
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

.outline-btn {
  border: 1px solid #77afff;
  background: white;
  color: #1677ff;
}

.outline-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.table-card {
  margin-top: 14px;
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 1250px;
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
  width: 70px;
}

th:nth-child(2) {
  width: 130px;
}

th:nth-child(3) {
  width: 110px;
}

th:nth-child(4) {
  width: 100px;
}

th:nth-child(5) {
  width: 125px;
}

th:nth-child(7) {
  width: 150px;
}

th:nth-child(8) {
  width: 105px;
}

th:nth-child(9) {
  width: 75px;
}

th:nth-child(10) {
  width: 145px;
}

th:nth-child(11) {
  width: 80px;
}

tbody tr:hover {
  background: #fafcff;
}

.organization {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.memberships {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.membership-tag {
  display: inline-flex;
  max-width: 100%;
  overflow: hidden;
  padding: 4px 8px;
  border-radius: 4px;
  background: #e9faf1;
  color: #20b875;
  font-size: 12px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.membership-tag.admin {
  background: #fff4e5;
  color: #f08c00;
}

.membership-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.membership-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.link-btn {
  padding: 0;
  border: 0;
  background: transparent;
  color: #1677ff;
  font-size: 13px;
}

.link-btn:hover {
  text-decoration: underline;
}

.link-btn.danger {
  color: #ef4f5d;
}

.action-error {
  margin-top: 8px;
  color: #ef4f5d;
  font-size: 13px;
}

.user-type,
.user-status {
  display: inline-flex;
  padding: 5px 9px;
  border-radius: 4px;
  white-space: nowrap;
}

.user-type {
  background: #eaf3ff;
  color: #1677ff;
}

.user-status.正常 {
  background: #e9faf1;
  color: #20b875;
}

.user-status.禁用 {
  background: #eff1f4;
  color: #727e90;
}

.operation {
  display: flex;
  gap: 7px;
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

.state-text {
  color: #97a1b0;
  font-size: 14px;
}

.state-text.error {
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
}

.full {
  grid-column: 1 / -1;
}

.stat-boxes {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.stat-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 14px 0;
  border: 1px solid #e8edf4;
  border-radius: 8px;
  background: #f8fafd;
}

.stat-box strong {
  color: #1677ff;
  font-size: 20px;
}

.stat-box span {
  color: #7d8898;
  font-size: 12px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 17px 24px;
  border-top: 1px solid #edf1f5;
}
</style>
