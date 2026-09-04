<script setup>
import {
  computed,
  reactive,
  ref
} from 'vue'

import {
  useUserStore
} from '../../stores/user'

import {
  userTypes,
  userStatuses
} from '../../mock/users'

const store =
  useUserStore()

const filters =
  reactive({
    keyword: '',
    type: '',
    status: '',
    startDate: '',
    endDate: ''
  })

const applied =
  reactive({
    keyword: '',
    type: '',
    status: '',
    startDate: '',
    endDate: ''
  })

const currentPage =
  ref(1)

const pageSize =
  ref(10)

const modalVisible =
  ref(false)

const modalMode =
  ref('view')

const currentUser =
  ref(null)

const form =
  reactive({
    username: '',
    type: '',
    phone: '',
    organization: '',
    status: ''
  })

const filteredData =
  computed(() => {
    const keyword =
      applied.keyword
        .trim()
        .toLowerCase()

    return store.users.filter(
      item => {
        const matchKeyword =
          !keyword ||
          item.username
            .toLowerCase()
            .includes(keyword) ||
          item.phone.includes(
            keyword
          ) ||
          item.organization
            .toLowerCase()
            .includes(keyword)

        const matchType =
          !applied.type ||
          item.type ===
            applied.type

        const matchStatus =
          !applied.status ||
          item.status ===
            applied.status

        const date =
          item.registeredAt
            .slice(0, 10)

        const matchStart =
          !applied.startDate ||
          date >=
            applied.startDate

        const matchEnd =
          !applied.endDate ||
          date <=
            applied.endDate

        return (
          matchKeyword &&
          matchType &&
          matchStatus &&
          matchStart &&
          matchEnd
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
        currentPage.value -
        1
      ) *
      pageSize.value

    return filteredData.value.slice(
      start,
      start +
      pageSize.value
    )
  })

const pages =
  computed(() => {
    const count =
      totalPages.value

    if (count <= 7) {
      return Array.from(
        { length: count },
        (_, index) =>
          index + 1
      )
    }

    return [
      1,
      2,
      3,
      4,
      5,
      '...',
      count
    ]
  })

const search = () => {
  Object.assign(
    applied,
    filters
  )

  currentPage.value = 1
}

const reset = () => {
  Object.assign(
    filters,
    {
      keyword: '',
      type: '',
      status: '',
      startDate: '',
      endDate: ''
    }
  )

  Object.assign(
    applied,
    filters
  )

  currentPage.value = 1
}

const openView = user => {
  currentUser.value = user
  modalMode.value = 'view'
  modalVisible.value = true
}

const openEdit = user => {
  currentUser.value = user

  Object.assign(
    form,
    {
      username:
        user.username,
      type:
        user.type,
      phone:
        user.phone,
      organization:
        user.organization,
      status:
        user.status
    }
  )

  modalMode.value = 'edit'
  modalVisible.value = true
}

const save = () => {
  store.update(
    currentUser.value.id,
    { ...form }
  )

  modalVisible.value = false
}

const toggleStatus = user => {
  const action =
    user.status === '禁用'
      ? '启用'
      : '禁用'

  if (
    !window.confirm(
      `确定${action}用户“${user.username}”吗？`
    )
  ) {
    return
  }

  store.toggleStatus(
    user.id
  )
}

const exportData = () => {
  const rows = [
    [
      'ID',
      '用户名',
      '用户类型',
      '手机号',
      '所属企业/单位',
      '状态',
      '注册时间',
      '最近登录'
    ],

    ...filteredData.value.map(
      user => [
        user.id,
        user.username,
        user.type,
        user.phone,
        user.organization,
        user.status,
        user.registeredAt,
        user.lastLogin
      ]
    )
  ]

  const csv =
    rows
      .map(
        row =>
          row
            .map(
              value =>
                `"${String(
                  value ?? ''
                ).replaceAll(
                  '"',
                  '""'
                )}"`
            )
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
    '用户列表.csv'

  link.click()

  URL.revokeObjectURL(
    url
  )
}
</script>

<template>
  <div class="user-page">

    <section class="filter-card">

      <div class="filter-row">

        <div class="filter-item keyword">

          <label>
            关键词
          </label>

          <input
            v-model="filters.keyword"
            placeholder="请输入用户名/手机号/企业名称"
            @keyup.enter="search"
          />

        </div>

        <div class="filter-item">

          <label>
            用户类型
          </label>

          <select
            v-model="filters.type"
          >

            <option value="">
              全部
            </option>

            <option
              v-for="
                item in userTypes
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
              全部
            </option>

            <option
              v-for="
                item in userStatuses
              "
              :key="item"
              :value="item"
            >
              {{ item }}
            </option>

          </select>

        </div>

        <div class="filter-item date-item">

          <label>
            注册时间
          </label>

          <div class="date-range">

            <input
              v-model="
                filters.startDate
              "
              type="date"
            />

            <span>
              至
            </span>

            <input
              v-model="
                filters.endDate
              "
              type="date"
            />

          </div>

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

          <button
            class="outline-btn"
            @click="exportData"
          >
            ⇩ 导出
          </button>

        </div>

      </div>

    </section>


    <section class="table-card">

      <table>

        <thead>

          <tr>
            <th>ID</th>
            <th>用户名</th>
            <th>用户类型</th>
            <th>手机号</th>
            <th>所属企业/单位</th>
            <th>状态</th>
            <th>注册时间</th>
            <th>最近登录</th>
            <th>操作</th>
          </tr>

        </thead>

        <tbody>

          <tr
            v-for="
              user in tableData
            "
            :key="user.id"
          >

            <td>
              {{ user.id }}
            </td>

            <td>
              {{ user.username }}
            </td>

            <td>

              <span
                class="user-type"
                :class="user.type"
              >
                {{ user.type }}
              </span>

            </td>

            <td>
              {{ user.phone }}
            </td>

            <td class="organization">
              {{ user.organization }}
            </td>

            <td>

              <span
                class="user-status"
                :class="user.status"
              >
                {{ user.status }}
              </span>

            </td>

            <td>
              {{ user.registeredAt }}
            </td>

            <td>
              {{
                user.lastLogin ||
                '—'
              }}
            </td>

            <td>

              <div class="operation">

                <button
                  @click="
                    openView(user)
                  "
                >
                  查看
                </button>

                <span>|</span>

                <button
                  @click="
                    openEdit(user)
                  "
                >
                  编辑
                </button>

                <span>|</span>

                <button
                  :class="{
                    enable:
                      user.status ===
                      '禁用'
                  }"
                  @click="
                    toggleStatus(user)
                  "
                >
                  {{
                    user.status ===
                    '禁用'
                      ? '启用'
                      : '禁用'
                  }}
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
          @change="
            currentPage = 1
          "
        >
          <option :value="10">
            10条/页
          </option>

          <option :value="20">
            20条/页
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
        modalVisible = false
      "
    >

      <div class="modal">

        <div class="modal-header">

          <h3>
            {{
              modalMode === 'view'
                ? '用户详情'
                : '编辑用户'
            }}
          </h3>

          <button
            @click="
              modalVisible = false
            "
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
            <label>用户ID</label>
            <strong>
              {{ currentUser.id }}
            </strong>
          </div>

          <div>
            <label>用户名</label>
            <strong>
              {{ currentUser.username }}
            </strong>
          </div>

          <div>
            <label>用户类型</label>
            <strong>
              {{ currentUser.type }}
            </strong>
          </div>

          <div>
            <label>手机号</label>
            <strong>
              {{ currentUser.phone }}
            </strong>
          </div>

          <div class="full">
            <label>所属单位</label>
            <strong>
              {{ currentUser.organization }}
            </strong>
          </div>

          <div>
            <label>状态</label>
            <strong>
              {{ currentUser.status }}
            </strong>
          </div>

          <div>
            <label>最近登录</label>
            <strong>
              {{
                currentUser.lastLogin ||
                '暂无'
              }}
            </strong>
          </div>

        </div>


        <div
          v-else
          class="form-grid"
        >

          <label>
            用户名

            <input
              v-model="
                form.username
              "
            />
          </label>

          <label>
            用户类型

            <select
              v-model="
                form.type
              "
            >

              <option
                v-for="
                  item in userTypes
                "
                :key="item"
                :value="item"
              >
                {{ item }}
              </option>

            </select>
          </label>

          <label>
            手机号

            <input
              v-model="
                form.phone
              "
            />
          </label>

          <label>
            用户状态

            <select
              v-model="
                form.status
              "
            >

              <option
                v-for="
                  item
                  in userStatuses
                "
                :key="item"
                :value="item"
              >
                {{ item }}
              </option>

            </select>
          </label>

          <label class="full">
            所属企业/单位

            <input
              v-model="
                form.organization
              "
            />
          </label>

        </div>


        <div class="modal-footer">

          <button
            class="default-btn"
            @click="
              modalVisible = false
            "
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
              modalMode === 'edit'
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
    1.3fr
    0.8fr
    0.75fr
    1.4fr
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

.date-range {
  display: flex;
  align-items: center;
  gap: 8px;
}

.date-range input {
  min-width: 0;
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
  width: 105px;
}

th:nth-child(2) {
  width: 95px;
}

th:nth-child(3) {
  width: 110px;
}

th:nth-child(4) {
  width: 120px;
}

th:nth-child(5) {
  width: 220px;
}

th:nth-child(6) {
  width: 85px;
}

th:nth-child(7),
th:nth-child(8) {
  width: 170px;
}

th:nth-child(9) {
  width: 150px;
}

tbody tr:hover {
  background: #fafcff;
}

.organization {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.user-type,
.user-status {
  display: inline-flex;
  padding: 5px 9px;
  border-radius: 4px;
}

.user-type.企业用户 {
  background: #eaf3ff;
  color: #1677ff;
}

.user-type.科研人员 {
  background: #f1edff;
  color: #765eee;
}

.user-type.机构用户 {
  background: #fff1df;
  color: #f0931e;
}

.user-status.正常 {
  background: #e9faf1;
  color: #20b875;
}

.user-status.待审 {
  background: #fff4de;
  color: #ed9b23;
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

.operation button:last-child {
  color: #ef5360;
}

.operation button.enable {
  color: #20b875;
}

.operation span {
  color: #d5dce5;
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
  color: #8994a4;
  font-size: 12px;
}

.detail-grid strong {
  color: #3c495c;
}

.form-grid label {
  color: #526073;
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