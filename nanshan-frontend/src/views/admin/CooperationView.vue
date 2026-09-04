<script setup>
import {
  computed,
  reactive,
  ref
} from 'vue'

import {
  useRouter
} from 'vue-router'

import {
  useCooperationStore
} from '../../stores/cooperation'

import {
  cooperationStatuses,
  cooperationTypes
} from '../../mock/cooperations'

const router =
  useRouter()

const store =
  useCooperationStore()

const filters =
  reactive({
    keyword: '',
    type: '',
    status: ''
  })

const appliedFilters =
  reactive({
    keyword: '',
    type: '',
    status: ''
  })

const currentPage =
  ref(1)

const pageSize =
  ref(10)

const handleSearch =
  () => {
    Object.assign(
      appliedFilters,
      filters
    )

    currentPage.value = 1
  }

const handleReset =
  () => {
    Object.assign(
      filters,
      {
        keyword: '',
        type: '',
        status: ''
      }
    )

    Object.assign(
      appliedFilters,
      filters
    )

    currentPage.value = 1
  }

const filteredData =
  computed(() => {
    const keyword =
      appliedFilters
        .keyword
        .trim()
        .toLowerCase()

    return store.cooperations.filter(
      item => {
        const matchKeyword =
          !keyword ||
          item.id
            .toLowerCase()
            .includes(keyword) ||
          item.initiator
            .toLowerCase()
            .includes(keyword) ||
          item.target
            .toLowerCase()
            .includes(keyword)

        const matchType =
          !appliedFilters.type ||
          item.type ===
            appliedFilters.type

        const matchStatus =
          !appliedFilters.status ||
          item.status ===
            appliedFilters.status

        return (
          matchKeyword &&
          matchType &&
          matchStatus
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
  computed(() => {
    return Math.max(
      1,
      Math.ceil(
        total.value /
        pageSize.value
      )
    )
  })

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
      start + pageSize.value
    )
  })

const pages =
  computed(() => {
    const count =
      totalPages.value

    if (count <= 7) {
      return Array.from(
        {
          length: count
        },
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

const goPage =
  page => {
    if (
      page === '...'
    ) return

    currentPage.value =
      page
  }

const goDetail =
  item => {
    router.push({
      name:
        'cooperation-detail',

      params: {
        id: item.id
      }
    })
  }

const handleProcess =
  item => {
    router.push({
      name:
        'cooperation-detail',

      params: {
        id: item.id
      },

      query: {
        action:
          'process'
      }
    })
  }

const getStatusClass =
  status => {
    return {
      待处理: 'pending',
      已接受: 'accepted',
      已确认: 'confirmed',
      已完成: 'completed',
      已归档: 'archived',
      已拒绝: 'rejected'
    }[status]
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
            v-model="
              filters.keyword
            "
            placeholder="请输入意向编号、发起人或对接对象"
            @keyup.enter="
              handleSearch
            "
          />

        </div>


        <div class="filter-item">

          <label>
            对接类型
          </label>

          <select
            v-model="
              filters.type
            "
          >

            <option value="">
              全部
            </option>

            <option
              v-for="
                item
                in cooperationTypes
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
            当前状态
          </label>

          <select
            v-model="
              filters.status
            "
          >

            <option value="">
              全部
            </option>

            <option
              v-for="
                item
                in cooperationStatuses
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
            @click="
              handleSearch
            "
          >
            查询
          </button>

          <button
            class="default-btn"
            @click="
              handleReset
            "
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
            <th>意向编号</th>
            <th>发起人</th>
            <th>对接对象</th>
            <th>对接类型</th>
            <th>联系人</th>
            <th>提交时间</th>
            <th>状态</th>
            <th>对接专员</th>
            <th>操作</th>
          </tr>

        </thead>

        <tbody>

          <tr
            v-for="
              item
              in tableData
            "
            :key="item.id"
          >

            <td>
              {{ item.id }}
            </td>

            <td
              class="text-ellipsis"
            >
              {{ item.initiator }}
            </td>

            <td
              class="text-ellipsis"
            >
              {{ item.target }}
            </td>

            <td>
              {{ item.type }}
            </td>

            <td>
              {{ item.contactName }}
            </td>

            <td>
              {{ item.submittedAt }}
            </td>

            <td>

              <span
                class="status-tag"
                :class="
                  getStatusClass(
                    item.status
                  )
                "
              >
                <i></i>

                {{ item.status }}
              </span>

            </td>

            <td>
              {{
                item.specialist ||
                '待分配'
              }}
            </td>

            <td>

              <div class="operation">

                <button
                  @click="
                    goDetail(item)
                  "
                >
                  查看
                </button>

                <span>|</span>

                <button
                  @click="
                    handleProcess(
                      item
                    )
                  "
                >
                  处理
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
          v-model="
            pageSize
          "
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
                currentPage ===
                page
            }"
            @click="
              goPage(page)
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
    1.6fr
    1fr
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
  min-width: 1260px;
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
  width: 150px;
}

th:nth-child(2),
th:nth-child(3) {
  width: 190px;
}

th:nth-child(4) {
  width: 110px;
}

th:nth-child(5) {
  width: 90px;
}

th:nth-child(6) {
  width: 170px;
}

th:nth-child(7) {
  width: 105px;
}

th:nth-child(8) {
  width: 105px;
}

th:nth-child(9) {
  width: 120px;
}

tbody tr:hover {
  background: #fafcff;
}

.text-ellipsis {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
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
  background: #fff5e6;
  color: #ec961d;
}

.status-tag.pending i {
  background: #f5a623;
}

.status-tag.accepted,
.status-tag.confirmed {
  background: #eaf3ff;
  color: #1677ff;
}

.status-tag.accepted i,
.status-tag.confirmed i {
  background: #1677ff;
}

.status-tag.completed {
  background: #e9faf1;
  color: #20b875;
}

.status-tag.completed i {
  background: #20b875;
}

.status-tag.archived {
  background: #eff1f4;
  color: #768294;
}

.status-tag.archived i {
  background: #768294;
}

.status-tag.rejected {
  background: #ffecef;
  color: #ef5260;
}

.status-tag.rejected i {
  background: #ef5260;
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