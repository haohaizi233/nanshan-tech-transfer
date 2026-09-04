<script setup>
import {
  computed,
  reactive,
  ref,
} from 'vue'

import {
  initialAchievements,
  achievementCategories,
  achievementStatuses,
  achievementAuditStatuses,
} from '../../mock/achievements'

const achievements = ref(
  initialAchievements.map(item => ({ ...item }))
)

const filters = reactive({
  keyword: '',
  category: '',
  status: '',
  auditStatus: '',
  startDate: '',
  endDate: '',
})

const appliedFilters = reactive({
  keyword: '',
  category: '',
  status: '',
  auditStatus: '',
  startDate: '',
  endDate: '',
})

const currentPage = ref(1)
const pageSize = ref(10)

const modalVisible = ref(false)
const modalMode = ref('view')
const currentAchievement = ref(null)

const editForm = reactive({
  id: '',
  name: '',
  category: '',
  organization: '',
  publisher: '',
  status: '审核中',
  auditStatus: '待审核',
  description: '',
})

const copyFilters = () => {
  Object.assign(appliedFilters, filters)
}

const handleSearch = () => {
  copyFilters()
  currentPage.value = 1
}

const handleReset = () => {
  Object.assign(filters, {
    keyword: '',
    category: '',
    status: '',
    auditStatus: '',
    startDate: '',
    endDate: '',
  })

  copyFilters()

  currentPage.value = 1
}

const filteredAchievements = computed(() => {
  const keyword =
    appliedFilters.keyword.trim().toLowerCase()

  return achievements.value.filter(item => {
    const matchKeyword =
      !keyword ||
      item.name.toLowerCase().includes(keyword) ||
      item.id.toLowerCase().includes(keyword)

    const matchCategory =
      !appliedFilters.category ||
      item.category === appliedFilters.category

    const matchStatus =
      !appliedFilters.status ||
      item.status === appliedFilters.status

    const matchAudit =
      !appliedFilters.auditStatus ||
      item.auditStatus === appliedFilters.auditStatus

    const itemDate =
      item.createdAt.slice(0, 10)

    const matchStartDate =
      !appliedFilters.startDate ||
      itemDate >= appliedFilters.startDate

    const matchEndDate =
      !appliedFilters.endDate ||
      itemDate <= appliedFilters.endDate

    return (
      matchKeyword &&
      matchCategory &&
      matchStatus &&
      matchAudit &&
      matchStartDate &&
      matchEndDate
    )
  })
})

const total = computed(
  () => filteredAchievements.value.length
)

const totalPages = computed(() => {
  return Math.max(
    1,
    Math.ceil(total.value / pageSize.value)
  )
})

const tableData = computed(() => {
  const start =
    (currentPage.value - 1) * pageSize.value

  return filteredAchievements.value.slice(
    start,
    start + pageSize.value
  )
})

const visiblePages = computed(() => {
  const count = totalPages.value

  if (count <= 7) {
    return Array.from(
      { length: count },
      (_, index) => index + 1
    )
  }

  if (currentPage.value <= 4) {
    return [1, 2, 3, 4, 5, '...', count]
  }

  if (currentPage.value >= count - 3) {
    return [
      1,
      '...',
      count - 4,
      count - 3,
      count - 2,
      count - 1,
      count,
    ]
  }

  return [
    1,
    '...',
    currentPage.value - 1,
    currentPage.value,
    currentPage.value + 1,
    '...',
    count,
  ]
})

const changePage = page => {
  if (page === '...') return

  if (page < 1 || page > totalPages.value) {
    return
  }

  currentPage.value = page
}

const handlePageSizeChange = () => {
  currentPage.value = 1
}

const getStatusClass = status => {
  return {
    已发布: 'published',
    审核中: 'reviewing',
    已下架: 'offline',
  }[status]
}

const getAuditClass = status => {
  return {
    已通过: 'approved',
    待审核: 'pending',
    已驳回: 'rejected',
  }[status]
}

const openView = item => {
  modalMode.value = 'view'
  currentAchievement.value = { ...item }
  modalVisible.value = true
}

const fillEditForm = item => {
  Object.assign(editForm, {
    id: item.id,
    name: item.name,
    category: item.category,
    organization: item.organization,
    publisher: item.publisher,
    status: item.status,
    auditStatus: item.auditStatus,
    description: item.description || '',
  })
}

const openEdit = item => {
  modalMode.value = 'edit'
  currentAchievement.value = item

  fillEditForm(item)

  modalVisible.value = true
}

const openCreate = () => {
  modalMode.value = 'create'
  currentAchievement.value = null

  Object.assign(editForm, {
    id: '',
    name: '',
    category: '',
    organization: '',
    publisher: '',
    status: '审核中',
    auditStatus: '待审核',
    description: '',
  })

  modalVisible.value = true
}

const openAudit = item => {
  modalMode.value = 'audit'
  currentAchievement.value = item
  modalVisible.value = true
}

const closeModal = () => {
  modalVisible.value = false
}

const saveAchievement = () => {
  if (!editForm.name.trim()) {
    window.alert('请输入成果名称')
    return
  }

  if (!editForm.category) {
    window.alert('请选择成果分类')
    return
  }

  if (modalMode.value === 'create') {
    const now = new Date()

    achievements.value.unshift({
      id:
        editForm.id ||
        `ACH${Date.now()}`,

      name: editForm.name,
      category: editForm.category,
      organization: editForm.organization,
      publisher: editForm.publisher || '管理员',
      status: editForm.status,
      auditStatus: editForm.auditStatus,
      views: 0,
      favorites: 0,

      createdAt:
        `${now.getFullYear()}-${String(
          now.getMonth() + 1
        ).padStart(2, '0')}-${String(
          now.getDate()
        ).padStart(2, '0')} ` +
        `${String(
          now.getHours()
        ).padStart(2, '0')}:${String(
          now.getMinutes()
        ).padStart(2, '0')}`,

      description: editForm.description,
    })

    currentPage.value = 1
  } else {
    const item = currentAchievement.value

    Object.assign(item, {
      name: editForm.name,
      category: editForm.category,
      organization: editForm.organization,
      publisher: editForm.publisher,
      status: editForm.status,
      auditStatus: editForm.auditStatus,
      description: editForm.description,
    })
  }

  closeModal()
}

const approveAchievement = () => {
  currentAchievement.value.auditStatus =
    '已通过'

  currentAchievement.value.status =
    '已发布'

  closeModal()
}

const rejectAchievement = () => {
  currentAchievement.value.auditStatus =
    '已驳回'

  currentAchievement.value.status =
    '已下架'

  closeModal()
}

const toggleOnline = item => {
  if (item.status === '已发布') {
    const confirmed =
      window.confirm(
        `确定要下架《${item.name}》吗？`
      )

    if (!confirmed) return

    item.status = '已下架'
  } else {
    item.status = '已发布'
  }
}

const downloadAchievement = item => {
  const content = [
    `成果编号：${item.id}`,
    `成果名称：${item.name}`,
    `所属分类：${item.category}`,
    `发布单位：${item.organization}`,
    `发布者：${item.publisher}`,
    `状态：${item.status}`,
    `审核状态：${item.auditStatus}`,
    `成果简介：${item.description || ''}`,
  ].join('\n')

  const blob = new Blob(
    [content],
    {
      type: 'text/plain;charset=utf-8',
    }
  )

  const url = URL.createObjectURL(blob)

  const link = document.createElement('a')

  link.href = url
  link.download = `${item.name}.txt`

  link.click()

  URL.revokeObjectURL(url)
}

const exportData = () => {
  const header = [
    'ID',
    '成果名称',
    '所属分类',
    '发布单位',
    '发布者',
    '状态',
    '审核状态',
    '浏览量',
    '收藏数',
    '创建时间',
  ]

  const rows =
    filteredAchievements.value.map(item => [
      item.id,
      item.name,
      item.category,
      item.organization,
      item.publisher,
      item.status,
      item.auditStatus,
      item.views,
      item.favorites,
      item.createdAt,
    ])

  const escapeCsv = value => {
    const text = String(value ?? '')
      .replaceAll('"', '""')

    return `"${text}"`
  }

  const csv = [
    header,
    ...rows,
  ]
    .map(row =>
      row
        .map(escapeCsv)
        .join(',')
    )
    .join('\n')

  const blob = new Blob(
    ['\uFEFF' + csv],
    {
      type:
        'text/csv;charset=utf-8',
    }
  )

  const url =
    URL.createObjectURL(blob)

  const link =
    document.createElement('a')

  link.href = url
  link.download =
    '成果列表.csv'

  link.click()

  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="achievement-page">

    <section class="filter-card">
      <div class="filter-grid">

        <div class="filter-item">
          <label>关键词</label>

          <input
            v-model="filters.keyword"
            type="text"
            placeholder="请输入成果名称/关键词"
            @keyup.enter="handleSearch"
          />
        </div>

        <div class="filter-item">
          <label>分类</label>

          <select v-model="filters.category">
            <option value="">
              请选择分类
            </option>

            <option
              v-for="item in achievementCategories"
              :key="item"
              :value="item"
            >
              {{ item }}
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
              v-for="item in achievementStatuses"
              :key="item"
              :value="item"
            >
              {{ item }}
            </option>
          </select>
        </div>

        <div class="filter-item">
          <label>审核状态</label>

          <select v-model="filters.auditStatus">
            <option value="">
              请选择审核状态
            </option>

            <option
              v-for="item in achievementAuditStatuses"
              :key="item"
              :value="item"
            >
              {{ item }}
            </option>
          </select>
        </div>

        <div class="filter-item date-filter">
          <label>发布时间</label>

          <div class="date-range">
            <input
              v-model="filters.startDate"
              type="date"
            />

            <span>至</span>

            <input
              v-model="filters.endDate"
              type="date"
            />
          </div>
        </div>

        <div class="filter-actions">
          <button
            type="button"
            class="primary-button"
            @click="handleSearch"
          >
            查询
          </button>

          <button
            type="button"
            class="default-button"
            @click="handleReset"
          >
            重置
          </button>
        </div>

        <div class="right-actions">
          <button
            type="button"
            class="outline-primary"
            @click="openCreate"
          >
            ＋ 新增成果
          </button>

          <button
            type="button"
            class="default-button"
            @click="exportData"
          >
            ⇩ 导出
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
              <th class="name-column">
                成果名称
              </th>
              <th>所属分类</th>
              <th>发布单位/团队</th>
              <th>发布者</th>
              <th>状态</th>
              <th>审核状态</th>
              <th>浏览量</th>
              <th>收藏数</th>
              <th>创建时间</th>
              <th class="operation-column">
                操作
              </th>
            </tr>
          </thead>

          <tbody>

            <tr
              v-for="item in tableData"
              :key="item.id"
            >
              <td>
                {{ item.id }}
              </td>

              <td
                class="achievement-name"
                :title="item.name"
              >
                {{ item.name }}
              </td>

              <td>
                {{ item.category }}
              </td>

              <td
                class="organization"
                :title="item.organization"
              >
                {{ item.organization }}
              </td>

              <td>
                {{ item.publisher }}
              </td>

              <td>
                <span
                  class="status"
                  :class="
                    getStatusClass(item.status)
                  "
                >
                  <i></i>

                  {{ item.status }}
                </span>
              </td>

              <td>
                <span
                  class="audit-status"
                  :class="
                    getAuditClass(
                      item.auditStatus
                    )
                  "
                >
                  {{ item.auditStatus }}
                </span>
              </td>

              <td>
                {{
                  item.views.toLocaleString()
                }}
              </td>

              <td>
                {{ item.favorites }}
              </td>

              <td class="created-time">
                {{ item.createdAt }}
              </td>

              <td>
                <div class="operation-buttons">

                  <button
                    type="button"
                    @click="openView(item)"
                  >
                    查看
                  </button>

                  <span>|</span>

                  <button
                    type="button"
                    @click="openEdit(item)"
                  >
                    编辑
                  </button>

                  <span>|</span>

                  <button
                    type="button"
                    @click="openAudit(item)"
                  >
                    审核
                  </button>

                  <span>|</span>

                  <button
                    type="button"
                    @click="toggleOnline(item)"
                  >
                    {{
                      item.status === '已发布'
                        ? '下架'
                        : '上架'
                    }}
                  </button>

                  <span>|</span>

                  <button
                    type="button"
                    @click="
                      downloadAchievement(item)
                    "
                  >
                    下载
                  </button>

                </div>
              </td>
            </tr>

            <tr v-if="tableData.length === 0">
              <td
                colspan="11"
                class="empty"
              >
                暂无符合条件的成果
              </td>
            </tr>

          </tbody>
        </table>

      </div>


      <div class="pagination">

        <div class="total">
          共 {{ total }} 条
        </div>

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
          type="button"
          class="page-button"
          :disabled="currentPage === 1"
          @click="
            changePage(currentPage - 1)
          "
        >
          ‹
        </button>

        <template
          v-for="(page, index) in visiblePages"
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
            class="page-button"
            :class="{
              active:
                page === currentPage
            }"
            @click="changePage(page)"
          >
            {{ page }}
          </button>

        </template>

        <button
          type="button"
          class="page-button"
          :disabled="
            currentPage === totalPages
          "
          @click="
            changePage(currentPage + 1)
          "
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
            {{
              modalMode === 'view'
                ? '成果详情'
                : modalMode === 'create'
                  ? '新增成果'
                  : modalMode === 'edit'
                    ? '编辑成果'
                    : '成果审核'
            }}
          </h3>

          <button
            type="button"
            class="close-button"
            @click="closeModal"
          >
            ×
          </button>
        </div>


        <div
          v-if="modalMode === 'view'"
          class="detail-content"
        >
          <div>
            <label>成果编号</label>
            <p>
              {{ currentAchievement.id }}
            </p>
          </div>

          <div>
            <label>成果名称</label>
            <p>
              {{ currentAchievement.name }}
            </p>
          </div>

          <div>
            <label>所属分类</label>
            <p>
              {{ currentAchievement.category }}
            </p>
          </div>

          <div>
            <label>发布单位</label>
            <p>
              {{
                currentAchievement.organization
              }}
            </p>
          </div>

          <div>
            <label>发布者</label>
            <p>
              {{ currentAchievement.publisher }}
            </p>
          </div>

          <div>
            <label>当前状态</label>
            <p>
              {{ currentAchievement.status }}
            </p>
          </div>

          <div class="full">
            <label>成果简介</label>
            <p>
              {{
                currentAchievement.description
              }}
            </p>
          </div>
        </div>


        <div
          v-else-if="
            modalMode === 'create' ||
            modalMode === 'edit'
          "
          class="edit-form"
        >

          <div class="modal-form-item">
            <label>成果编号</label>

            <input
              v-model="editForm.id"
              :disabled="
                modalMode === 'edit'
              "
              placeholder="自动生成或手动填写"
            />
          </div>

          <div class="modal-form-item">
            <label>成果名称 *</label>

            <input
              v-model="editForm.name"
              placeholder="请输入成果名称"
            />
          </div>

          <div class="modal-form-item">
            <label>所属分类 *</label>

            <select
              v-model="editForm.category"
            >
              <option value="">
                请选择
              </option>

              <option
                v-for="item in achievementCategories"
                :key="item"
                :value="item"
              >
                {{ item }}
              </option>
            </select>
          </div>

          <div class="modal-form-item">
            <label>发布单位/团队</label>

            <input
              v-model="
                editForm.organization
              "
            />
          </div>

          <div class="modal-form-item">
            <label>发布者</label>

            <input
              v-model="
                editForm.publisher
              "
            />
          </div>

          <div class="modal-form-item">
            <label>状态</label>

            <select
              v-model="editForm.status"
            >
              <option
                v-for="item in achievementStatuses"
                :key="item"
                :value="item"
              >
                {{ item }}
              </option>
            </select>
          </div>

          <div class="modal-form-item">
            <label>审核状态</label>

            <select
              v-model="
                editForm.auditStatus
              "
            >
              <option
                v-for="item in achievementAuditStatuses"
                :key="item"
                :value="item"
              >
                {{ item }}
              </option>
            </select>
          </div>

          <div class="modal-form-item full">
            <label>成果简介</label>

            <textarea
              v-model="
                editForm.description
              "
              rows="5"
            ></textarea>
          </div>

        </div>


        <div
          v-else
          class="audit-content"
        >
          <div class="audit-name">
            {{
              currentAchievement.name
            }}
          </div>

          <p>
            当前审核状态：
            <strong>
              {{
                currentAchievement.auditStatus
              }}
            </strong>
          </p>

          <p class="audit-tip">
            请确认该成果内容是否符合平台发布要求。
          </p>
        </div>


        <div class="modal-footer">

          <button
            type="button"
            class="default-button"
            @click="closeModal"
          >
            取消
          </button>

          <button
            v-if="
              modalMode === 'create' ||
              modalMode === 'edit'
            "
            type="button"
            class="primary-button"
            @click="saveAchievement"
          >
            保存
          </button>

          <template
            v-if="modalMode === 'audit'"
          >
            <button
              type="button"
              class="reject-button"
              @click="rejectAchievement"
            >
              审核驳回
            </button>

            <button
              type="button"
              class="primary-button"
              @click="
                approveAchievement
              "
            >
              审核通过
            </button>
          </template>

        </div>

      </div>

    </div>

  </div>
</template>

<style scoped>
.achievement-page {
  width: 100%;
}

.filter-card,
.table-card {
  border: 1px solid #e8edf4;
  border-radius: 11px;
  background: #ffffff;
  box-shadow:
    0 2px 14px rgba(40, 72, 110, 0.07);
}

.filter-card {
  padding: 25px 27px;
}

.filter-grid {
  display: grid;
  grid-template-columns:
    1.35fr
    1fr
    1fr
    1fr
    auto;

  align-items: end;
  gap: 20px 28px;
}

.filter-item label {
  display: block;
  margin-bottom: 9px;
  color: #273347;
  font-size: 14px;
  font-weight: 600;
}

.filter-item input,
.filter-item select,
.pagination select,
.modal input,
.modal select,
.modal textarea {
  width: 100%;
  height: 40px;
  padding: 0 13px;
  outline: none;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  background: #ffffff;
  color: #4c596b;
}

.filter-item input:focus,
.filter-item select:focus,
.modal input:focus,
.modal select:focus,
.modal textarea:focus {
  border-color: #1677ff;
}

.date-filter {
  grid-column: 1 / 3;
}

.date-range {
  display: flex;
  align-items: center;
  gap: 10px;
}

.date-range input {
  min-width: 0;
}

.filter-actions,
.right-actions {
  display: flex;
  gap: 12px;
}

.filter-actions {
  grid-column: 4;
}

.right-actions {
  grid-column: 5;
  justify-content: flex-end;
}

.primary-button,
.default-button,
.outline-primary,
.reject-button {
  height: 40px;
  padding: 0 25px;
  border-radius: 5px;
  font-size: 14px;
}

.primary-button {
  border: 1px solid #1677ff;
  background: #1677ff;
  color: white;
}

.primary-button:hover {
  background: #0869e8;
}

.default-button {
  border: 1px solid #dce4ee;
  background: #ffffff;
  color: #4c596a;
}

.default-button:hover {
  border-color: #9fc6ff;
  color: #1677ff;
}

.outline-primary {
  border: 1px solid #9ac6ff;
  background: white;
  color: #1677ff;
}

.outline-primary:hover {
  background: #eff6ff;
}

.reject-button {
  border: 1px solid #ff5964;
  background: white;
  color: #ef4350;
}

.table-card {
  margin-top: 14px;
  overflow: hidden;
}

.table-wrapper {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 1330px;
  border-collapse: collapse;
  table-layout: fixed;
}

th,
td {
  height: 64px;
  padding: 0 14px;
  border-bottom: 1px solid #edf1f5;
  color: #4e5969;
  font-size: 13px;
  text-align: left;
  vertical-align: middle;
}

th {
  height: 64px;
  background: #ffffff;
  color: #273347;
  font-weight: 600;
}

th:nth-child(1) {
  width: 135px;
}

.name-column {
  width: 210px;
}

th:nth-child(3) {
  width: 95px;
}

th:nth-child(4) {
  width: 155px;
}

th:nth-child(5) {
  width: 70px;
}

th:nth-child(6) {
  width: 90px;
}

th:nth-child(7) {
  width: 95px;
}

th:nth-child(8),
th:nth-child(9) {
  width: 70px;
}

th:nth-child(10) {
  width: 135px;
}

.operation-column {
  width: 205px;
}

tbody tr:hover {
  background: #fafcff;
}

.achievement-name,
.organization {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
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

.status.published i {
  background: #22bd7a;
}

.status.reviewing {
  padding: 5px 8px;
  border-radius: 4px;
  background: #ebf3ff;
  color: #317de9;
}

.status.reviewing i {
  background: #317de9;
}

.status.offline {
  padding: 5px 8px;
  border-radius: 4px;
  background: #fff0f2;
  color: #f25763;
}

.status.offline i {
  background: #f25763;
}

.audit-status {
  display: inline-flex;
  padding: 5px 10px;
  border-radius: 4px;
  font-size: 12px;
}

.audit-status.approved {
  background: #e9faf1;
  color: #26b676;
}

.audit-status.pending {
  background: #fff3dd;
  color: #ee982c;
}

.audit-status.rejected {
  background: #ffecef;
  color: #ef4f5d;
}

.created-time {
  white-space: nowrap;
}

.operation-buttons {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.operation-buttons button {
  padding: 0;
  border: 0;
  background: transparent;
  color: #1677ff;
  font-size: 12px;
}

.operation-buttons button:hover {
  text-decoration: underline;
}

.operation-buttons span {
  color: #d4dbe5;
}

.empty {
  height: 180px;
  color: #a0a9b5;
  text-align: center;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 74px;
  padding: 12px 24px;
}

.pagination .total {
  margin-right: 14px;
}

.pagination select {
  width: 110px;
  margin-right: 8px;
}

.page-button {
  min-width: 38px;
  height: 38px;
  padding: 0 11px;
  border: 1px solid #dfe5ed;
  border-radius: 5px;
  background: white;
  color: #344154;
}

.page-button.active {
  border-color: #1677ff;
  background: #1677ff;
  color: white;
}

.page-button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.ellipsis {
  padding: 0 6px;
}


/* 弹窗 */

.modal-mask {
  position: fixed;
  z-index: 500;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 28, 48, 0.36);
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
  height: 64px;
  padding: 0 24px;
  border-bottom: 1px solid #edf1f5;
}

.modal-header h3 {
  margin: 0;
  font-size: 18px;
}

.close-button {
  border: 0;
  background: transparent;
  color: #8b96a5;
  font-size: 25px;
}

.detail-content,
.edit-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 22px;
  padding: 26px;
}

.detail-content label,
.modal-form-item label {
  display: block;
  margin-bottom: 8px;
  color: #8590a0;
  font-size: 12px;
}

.detail-content p {
  margin: 0;
  color: #344153;
  line-height: 1.7;
}

.full {
  grid-column: 1 / -1;
}

.modal textarea {
  height: auto;
  padding-top: 10px;
  resize: vertical;
}

.audit-content {
  padding: 35px 30px;
}

.audit-name {
  margin-bottom: 20px;
  color: #1e2939;
  font-size: 18px;
  font-weight: 600;
}

.audit-tip {
  color: #8b96a5;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid #edf1f5;
}

@media (max-width: 1500px) {
  .filter-grid {
    grid-template-columns:
      1.3fr
      1fr
      1fr
      1fr;
  }

  .date-filter {
    grid-column: 1 / 3;
  }

  .filter-actions {
    grid-column: 3;
  }

  .right-actions {
    grid-column: 4;
  }
}
</style>