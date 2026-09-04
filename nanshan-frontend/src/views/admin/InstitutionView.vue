<script setup>
import {
  computed,
  reactive,
  ref,
  watch
} from 'vue'

import {
  useInstitutionStore
} from '../../stores/institution'

import {
  institutionTypes,
  institutionStatuses
} from '../../mock/institutions'

const store =
  useInstitutionStore()

const filters =
  reactive({
    keyword: '',
    type: '',
    status: ''
  })

const applied =
  reactive({
    keyword: '',
    type: '',
    status: ''
  })

const selectedIds =
  ref([])

const currentPage =
  ref(1)

const pageSize =
  ref(10)

const modalVisible =
  ref(false)

const modalMode =
  ref('view')

const currentItem =
  ref(null)

const form =
  reactive({
    id: '',
    name: '',
    type: '',
    contact: '',
    phone: '',
    region: '',
    status: '已上架'
  })

const filteredData =
  computed(() => {
    const keyword =
      applied.keyword
        .trim()
        .toLowerCase()

    return store.institutions.filter(
      item => {
        const keywordMatch =
          !keyword ||
          item.name
            .toLowerCase()
            .includes(keyword) ||
          item.contact
            .toLowerCase()
            .includes(keyword) ||
          item.phone
            .toLowerCase()
            .includes(keyword)

        const typeMatch =
          !applied.type ||
          item.type === applied.type

        const statusMatch =
          !applied.status ||
          item.status ===
            applied.status

        return (
          keywordMatch &&
          typeMatch &&
          statusMatch
        )
      }
    )
  })

const total =
  computed(
    () =>
      filteredData.value.length
  )

const totalPages =
  computed(() =>
    Math.max(
      1,
      Math.ceil(
        total.value /
        pageSize.value
      )
    )
  )

const tableData =
  computed(() => {
    const start =
      (
        currentPage.value - 1
      ) *
      pageSize.value

    return filteredData.value.slice(
      start,
      start + pageSize.value
    )
  })

const pages =
  computed(() => {
    const count =
      totalPages.value

    if (count <= 7) {
      return Array.from(
        { length: count },
        (_, index) => index + 1
      )
    }

    if (
      currentPage.value <= 4
    ) {
      return [
        1,
        2,
        3,
        4,
        5,
        '...',
        count
      ]
    }

    return [
      1,
      '...',
      currentPage.value - 1,
      currentPage.value,
      currentPage.value + 1,
      '...',
      count
    ]
  })

const allCurrentSelected =
  computed(() => {
    if (
      !tableData.value.length
    ) {
      return false
    }

    return tableData.value.every(
      item =>
        selectedIds.value.includes(
          item.id
        )
    )
  })

const handleSearch = () => {
  Object.assign(
    applied,
    filters
  )

  currentPage.value = 1
  selectedIds.value = []
}

const reset = () => {
  Object.assign(
    filters,
    {
      keyword: '',
      type: '',
      status: ''
    }
  )

  Object.assign(
    applied,
    filters
  )

  currentPage.value = 1
  selectedIds.value = []
}

const toggleSelectAll = event => {
  if (
    event.target.checked
  ) {
    const ids =
      tableData.value.map(
        item => item.id
      )

    selectedIds.value = [
      ...new Set([
        ...selectedIds.value,
        ...ids
      ])
    ]
  } else {
    const currentIds =
      tableData.value.map(
        item => item.id
      )

    selectedIds.value =
      selectedIds.value.filter(
        id =>
          !currentIds.includes(id)
      )
  }
}

const openView = item => {
  currentItem.value = item
  modalMode.value = 'view'
  modalVisible.value = true
}

const fillForm = item => {
  Object.assign(
    form,
    item
  )
}

const openEdit = item => {
  currentItem.value = item

  fillForm(item)

  modalMode.value = 'edit'
  modalVisible.value = true
}

const openCreate = () => {
  currentItem.value = null

  Object.assign(
    form,
    {
      id: '',
      name: '',
      type: '',
      contact: '',
      phone: '',
      region:
        '广东省 深圳市 南山区',
      status: '已上架'
    }
  )

  modalMode.value = 'create'
  modalVisible.value = true
}

const closeModal = () => {
  modalVisible.value = false
}

const save = () => {
  if (!form.name.trim()) {
    window.alert(
      '请输入机构名称'
    )
    return
  }

  if (!form.type) {
    window.alert(
      '请选择机构类型'
    )
    return
  }

  if (
    modalMode.value ===
    'create'
  ) {
    store.add({
      ...form,

      id:
        form.id ||
        String(
          Date.now()
        ).slice(-8),

      createdAt:
        new Date()
          .toLocaleString(
            'zh-CN',
            {
              hour12: false
            }
          )
    })

    currentPage.value = 1
  } else {
    store.update(
      currentItem.value.id,
      {
        name: form.name,
        type: form.type,
        contact: form.contact,
        phone: form.phone,
        region: form.region,
        status: form.status
      }
    )
  }

  closeModal()
}

const toggleStatus = item => {
  const action =
    item.status === '已上架'
      ? '下架'
      : '上架'

  if (
    !window.confirm(
      `确定${action}机构《${item.name}》吗？`
    )
  ) {
    return
  }

  store.toggleStatus(
    item.id
  )
}

const removeItem = item => {
  if (
    !window.confirm(
      `确定删除机构《${item.name}》吗？`
    )
  ) {
    return
  }

  store.remove(
    item.id
  )

  selectedIds.value =
    selectedIds.value.filter(
      id => id !== item.id
    )
}

const batchAction = event => {
  const action =
    event.target.value

  event.target.value = ''

  if (!action) return

  if (
    selectedIds.value.length === 0
  ) {
    window.alert(
      '请先选择机构'
    )

    return
  }

  if (
    action === 'online'
  ) {
    store.batchStatus(
      selectedIds.value,
      '已上架'
    )
  }

  if (
    action === 'offline'
  ) {
    store.batchStatus(
      selectedIds.value,
      '已下架'
    )
  }

  if (
    action === 'delete'
  ) {
    if (
      !window.confirm(
        `确定删除已选择的 ${selectedIds.value.length} 个机构吗？`
      )
    ) {
      return
    }

    store.batchRemove(
      selectedIds.value
    )
  }

  selectedIds.value = []
}

const escapeCsv =
  value => {
    return `"${String(
      value ?? ''
    ).replaceAll(
      '"',
      '""'
    )}"`
  }

const exportData = () => {
  const rows = [
    [
      'ID',
      '机构名称',
      '机构类型',
      '联系人',
      '联系电话',
      '地区',
      '状态',
      '创建时间'
    ],

    ...filteredData.value.map(
      item => [
        item.id,
        item.name,
        item.type,
        item.contact,
        item.phone,
        item.region,
        item.status,
        item.createdAt
      ]
    )
  ]

  const csv =
    rows
      .map(
        row =>
          row
            .map(escapeCsv)
            .join(',')
      )
      .join('\n')

  const blob =
    new Blob(
      [
        '\uFEFF' +
        csv
      ],
      {
        type:
          'text/csv;charset=utf-8'
      }
    )

  const url =
    URL.createObjectURL(
      blob
    )

  const link =
    document.createElement(
      'a'
    )

  link.href = url
  link.download =
    '机构列表.csv'

  link.click()

  URL.revokeObjectURL(
    url
  )
}

const importInput =
  ref(null)

const openImport = () => {
  importInput.value?.click()
}

const importFile = event => {
  const file =
    event.target.files?.[0]

  if (!file) return

  window.alert(
    `已选择文件：${file.name}\n当前阶段先完成文件选择入口，第 11 阶段再补 CSV 数据解析。`
  )

  event.target.value = ''
}

watch(
  pageSize,
  () => {
    currentPage.value = 1
    selectedIds.value = []
  }
)
</script>

<template>
  <div class="institution-page">

    <section class="filter-card">

      <div class="filter-row">

        <div class="filter-item keyword">

          <label>
            关键词
          </label>

          <input
            v-model="filters.keyword"
            placeholder="请输入机构名称、联系人或手机号"
            @keyup.enter="
              handleSearch
            "
          />

        </div>

        <div class="filter-item">

          <label>
            机构类型
          </label>

          <select
            v-model="filters.type"
          >

            <option value="">
              请选择机构类型
            </option>

            <option
              v-for="
                item in institutionTypes
              "
              :key="item"
              :value="item"
            >
              {{ item }}
            </option>

          </select>

        </div>

        <div class="filter-item">

          <label>
            状态
          </label>

          <select
            v-model="filters.status"
          >

            <option value="">
              请选择状态
            </option>

            <option
              v-for="
                item in institutionStatuses
              "
              :key="item"
              :value="item"
            >
              {{ item }}
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

              <th class="check-col">

                <input
                  type="checkbox"
                  :checked="
                    allCurrentSelected
                  "
                  @change="
                    toggleSelectAll
                  "
                />

              </th>

              <th>ID</th>
              <th>机构名称</th>
              <th>机构类型</th>
              <th>联系人</th>
              <th>联系电话</th>
              <th>地区</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>操作</th>

            </tr>
          </thead>

          <tbody>

            <tr
              v-for="
                item in tableData
              "
              :key="item.id"
            >

              <td>

                <input
                  v-model="
                    selectedIds
                  "
                  type="checkbox"
                  :value="item.id"
                />

              </td>

              <td>
                {{ item.id }}
              </td>

              <td class="name-cell">
                {{ item.name }}
              </td>

              <td>
                <span
                  class="type-tag"
                  :class="item.type"
                >
                  {{ item.type }}
                </span>
              </td>

              <td>
                {{ item.contact }}
              </td>

              <td>
                {{ item.phone }}
              </td>

              <td>
                {{ item.region }}
              </td>

              <td>

                <span
                  class="status"
                  :class="{
                    online:
                      item.status ===
                      '已上架',
                    offline:
                      item.status ===
                      '已下架'
                  }"
                >

                  <i></i>

                  {{ item.status }}

                </span>

              </td>

              <td>
                {{ item.createdAt }}
              </td>

              <td>

                <div class="operation">

                  <button
                    @click="
                      openView(item)
                    "
                  >
                    查看
                  </button>

                  <span>|</span>

                  <button
                    @click="
                      openEdit(item)
                    "
                  >
                    编辑
                  </button>

                  <span>|</span>

                  <button
                    @click="
                      toggleStatus(item)
                    "
                  >
                    {{
                      item.status ===
                      '已上架'
                        ? '下架'
                        : '上架'
                    }}
                  </button>

                  <span>|</span>

                  <button
                    class="danger"
                    @click="
                      removeItem(item)
                    "
                  >
                    删除
                  </button>

                </div>

              </td>

            </tr>

          </tbody>

        </table>

      </div>


      <div class="batch-row">

        <div class="batch-left">

          <label>
            <input
              type="checkbox"
              :checked="
                allCurrentSelected
              "
              @change="
                toggleSelectAll
              "
            />

            全选
          </label>

          <select
            @change="
              batchAction
            "
          >

            <option value="">
              批量操作
            </option>

            <option value="online">
              批量上架
            </option>

            <option value="offline">
              批量下架
            </option>

            <option value="delete">
              批量删除
            </option>

          </select>

          <span>
            已选择
            {{ selectedIds.length }}
            项
          </span>

        </div>


        <div class="batch-right">

          <button
            class="outline-btn"
            @click="exportData"
          >
            ⇩ 导出数据
          </button>

          <button
            class="primary-btn"
            @click="openImport"
          >
            ⇧ 批量导入
          </button>

          <input
            ref="importInput"
            type="file"
            accept=".csv,.xlsx,.xls"
            hidden
            @change="importFile"
          />

        </div>

      </div>


      <div class="pagination">

        <span>
          共 {{ total }} 条
        </span>

        <select
          v-model="pageSize"
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
          :disabled="
            currentPage === 1
          "
          @click="
            currentPage--
          "
        >
          ‹
        </button>

        <template
          v-for="
            (page, index)
            in pages
          "
          :key="
            `${page}-${index}`
          "
        >

          <span
            v-if="
              page === '...'
            "
          >
            ...
          </span>

          <button
            v-else
            :class="{
              active:
                currentPage === page
            }"
            @click="
              currentPage = page
            "
          >
            {{ page }}
          </button>

        </template>

        <button
          :disabled="
            currentPage ===
            totalPages
          "
          @click="
            currentPage++
          "
        >
          ›
        </button>

      </div>

    </section>


    <div
      v-if="modalVisible"
      class="modal-mask"
      @click.self="
        closeModal
      "
    >

      <div class="modal">

        <div class="modal-header">

          <h3>
            {{
              modalMode === 'view'
                ? '机构详情'
                : modalMode === 'create'
                  ? '新增机构'
                  : '编辑机构'
            }}
          </h3>

          <button
            @click="closeModal"
          >
            ×
          </button>

        </div>


        <div
          v-if="
            modalMode === 'view'
          "
          class="detail-grid"
        >

          <div>
            <label>机构编号</label>
            <strong>
              {{ currentItem.id }}
            </strong>
          </div>

          <div>
            <label>机构名称</label>
            <strong>
              {{ currentItem.name }}
            </strong>
          </div>

          <div>
            <label>机构类型</label>
            <strong>
              {{ currentItem.type }}
            </strong>
          </div>

          <div>
            <label>联系人</label>
            <strong>
              {{ currentItem.contact }}
            </strong>
          </div>

          <div>
            <label>联系电话</label>
            <strong>
              {{ currentItem.phone }}
            </strong>
          </div>

          <div>
            <label>状态</label>
            <strong>
              {{ currentItem.status }}
            </strong>
          </div>

          <div class="full">
            <label>所在地区</label>
            <strong>
              {{ currentItem.region }}
            </strong>
          </div>

        </div>


        <div
          v-else
          class="form-grid"
        >

          <label>
            机构名称 *

            <input
              v-model="form.name"
            />
          </label>

          <label>
            机构类型 *

            <select
              v-model="form.type"
            >

              <option value="">
                请选择
              </option>

              <option
                v-for="
                  item
                  in institutionTypes
                "
                :key="item"
                :value="item"
              >
                {{ item }}
              </option>

            </select>
          </label>

          <label>
            联系人

            <input
              v-model="
                form.contact
              "
            />
          </label>

          <label>
            联系电话

            <input
              v-model="
                form.phone
              "
            />
          </label>

          <label class="full">
            所在地区

            <input
              v-model="
                form.region
              "
            />
          </label>

          <label>
            状态

            <select
              v-model="
                form.status
              "
            >
              <option value="已上架">
                已上架
              </option>

              <option value="已下架">
                已下架
              </option>
            </select>

          </label>

        </div>


        <div class="modal-footer">

          <button
            class="default-btn"
            @click="closeModal"
          >
            {{
              modalMode ===
              'view'
                ? '关闭'
                : '取消'
            }}
          </button>

          <button
            v-if="
              modalMode !== 'view'
            "
            class="primary-btn"
            @click="save"
          >
            保存
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
.batch-row select,
.pagination select,
.form-grid input,
.form-grid select {
  width: 100%;
  height: 42px;
  padding: 0 13px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  outline: none;
  background: white;
}

.filter-item input:focus,
.filter-item select:focus,
.form-grid input:focus,
.form-grid select:focus {
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

.table-card {
  margin-top: 14px;
}

.table-wrapper {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 1300px;
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

.check-col {
  width: 48px;
}

th:nth-child(2) {
  width: 75px;
}

th:nth-child(3) {
  width: 210px;
}

th:nth-child(4) {
  width: 110px;
}

th:nth-child(5) {
  width: 90px;
}

th:nth-child(6) {
  width: 120px;
}

th:nth-child(7) {
  width: 220px;
}

th:nth-child(8) {
  width: 95px;
}

th:nth-child(9) {
  width: 170px;
}

th:nth-child(10) {
  width: 180px;
}

tbody tr:hover {
  background: #fafcff;
}

.name-cell {
  font-weight: 500;
}

.type-tag {
  display: inline-block;
  padding: 5px 9px;
  border-radius: 4px;
  background: #eaf3ff;
  color: #1677ff;
}

.type-tag.服务机构 {
  background: #e9faf8;
  color: #24b6a2;
}

.type-tag.银行 {
  background: #fff3e2;
  color: #ee991f;
}

.type-tag.高校 {
  background: #f1edff;
  color: #7d64ee;
}

.type-tag.研究院 {
  background: #edf4ff;
  color: #427ce2;
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

.operation .danger {
  color: #ef5360;
}

.operation span {
  color: #d4dbe4;
}

.batch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 64px;
  padding: 0 25px;
  border-bottom: 1px solid #edf1f5;
}

.batch-left,
.batch-right {
  display: flex;
  align-items: center;
  gap: 17px;
}

.batch-left select {
  width: 125px;
}

.batch-left span {
  color: #909baa;
  font-size: 13px;
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
}

.form-grid label {
  color: #536073;
  font-size: 13px;
}

.form-grid input,
.form-grid select {
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