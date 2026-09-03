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
  useRequirementStore
} from '../../stores/requirement'

import {
  requirementIndustries,
  requirementStatuses
} from '../../mock/requirements'

const router = useRouter()

const store =
  useRequirementStore()

const filters = reactive({
  keyword: '',
  industry: '',
  status: ''
})

const appliedFilters =
  reactive({
    keyword: '',
    industry: '',
    status: ''
  })

const currentPage =
  ref(1)

const pageSize =
  ref(10)

const handleSearch = () => {
  Object.assign(
    appliedFilters,
    filters
  )

  currentPage.value = 1
}

const handleReset = () => {
  Object.assign(
    filters,
    {
      keyword: '',
      industry: '',
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
      appliedFilters.keyword
        .trim()
        .toLowerCase()

    return store.requirements.filter(
      item => {
        const keywordMatch =
          !keyword ||
          item.title
            .toLowerCase()
            .includes(keyword) ||
          item.id
            .toLowerCase()
            .includes(keyword) ||
          item.organization
            .toLowerCase()
            .includes(keyword)

        const industryMatch =
          !appliedFilters.industry ||
          item.industry.includes(
            appliedFilters.industry
          )

        const statusMatch =
          !appliedFilters.status ||
          item.status ===
            appliedFilters.status

        return (
          keywordMatch &&
          industryMatch &&
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

const visiblePages =
  computed(() => {
    const total =
      totalPages.value

    if (total <= 7) {
      return Array.from(
        {
          length: total
        },
        (_, index) =>
          index + 1
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
        total
      ]
    }

    return [
      1,
      '...',
      currentPage.value - 1,
      currentPage.value,
      currentPage.value + 1,
      '...',
      total
    ]
  })

const changePage =
  page => {
    if (
      page === '...'
    ) {
      return
    }

    if (
      page < 1 ||
      page >
        totalPages.value
    ) {
      return
    }

    currentPage.value =
      page
  }

const goDetail =
  item => {
    router.push(
      `/admin/requirements/${item.id}`
    )
  }

const handleAudit =
  item => {
    router.push({
      name:
        'requirement-detail',

      params: {
        id: item.id
      },

      query: {
        action: 'audit'
      }
    })
  }

const toggleStatus =
  item => {
    if (
      item.status ===
      '已发布'
    ) {
      const result =
        window.confirm(
          `确定关闭需求《${item.title}》吗？`
        )

      if (!result) return
    }

    store.togglePublish(
      item.id
    )
  }

const getStatusClass =
  status => {
    return {
      审核中: 'reviewing',
      已发布: 'published',
      对接中: 'docking',
      已完成: 'completed',
      已关闭: 'closed',
      已驳回: 'rejected'
    }[status]
  }
</script>

<template>
  <div class="requirement-page">

    <section class="filter-card">

      <div class="filters">

        <div class="filter-item keyword">
          <label>
            关键词
          </label>

          <input
            v-model="
              filters.keyword
            "
            placeholder="请输入需求名称、编号或企业"
            @keyup.enter="
              handleSearch
            "
          />
        </div>

        <div class="filter-item">
          <label>
            所属行业
          </label>

          <select
            v-model="
              filters.industry
            "
          >
            <option value="">
              全部
            </option>

            <option
              v-for="
                item
                in requirementIndustries
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
                in requirementStatuses
              "
              :key="item"
              :value="item"
            >
              {{ item }}
            </option>
          </select>
        </div>

        <div class="actions">
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
            <th>需求编号</th>
            <th>需求名称</th>
            <th>发布单位</th>
            <th>所属行业</th>
            <th>预算范围</th>
            <th>状态</th>
            <th>发布时间</th>
            <th>浏览量</th>
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
              {{ item.id }}
            </td>

            <td
              class="title-cell"
              :title="
                item.title
              "
            >
              {{ item.title }}
            </td>

            <td
              class="ellipsis-cell"
              :title="
                item.organization
              "
            >
              {{
                item.organization
              }}
            </td>

            <td>
              {{ item.industry }}
            </td>

            <td>
              {{ item.budget }}
            </td>

            <td>
              <span
                class="status"
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
                item.publishedAt
              }}
            </td>

            <td>
              {{ item.views }}
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
                    handleAudit(
                      item
                    )
                  "
                >
                  审核
                </button>

                <span>|</span>

                <button
                  @click="
                    toggleStatus(
                      item
                    )
                  "
                >
                  {{
                    item.status ===
                    '已发布'
                      ? '关闭'
                      : '发布'
                  }}
                </button>

              </div>
            </td>

          </tr>

          <tr
            v-if="
              tableData.length ===
              0
            "
          >
            <td
              colspan="9"
              class="empty"
            >
              暂无符合条件的需求
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
            changePage(
              currentPage - 1
            )
          "
        >
          ‹
        </button>

        <template
          v-for="
            (page, index)
            in visiblePages
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
              changePage(page)
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
            changePage(
              currentPage + 1
            )
          "
        >
          ›
        </button>

      </div>

    </section>

  </div>
</template>

<style scoped>
.requirement-page {
  width: 100%;
}

.filter-card,
.table-card {
  border:
    1px solid #e8edf4;

  border-radius: 11px;

  background: #fff;

  box-shadow:
    0 2px 14px
    rgba(
      40,
      72,
      110,
      0.07
    );
}

.filter-card {
  padding: 25px 27px;
}

.filters {
  display: grid;

  grid-template-columns:
    1.5fr
    1fr
    1fr
    auto;

  align-items: end;

  gap: 25px;
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

  border:
    1px solid #dce4ee;

  border-radius: 5px;

  outline: none;

  background: white;
}

.filter-item input:focus,
.filter-item select:focus {
  border-color:
    #1677ff;
}

.actions {
  display: flex;

  gap: 12px;
}

.primary-btn,
.default-btn {
  height: 42px;

  padding:
    0 28px;

  border-radius: 5px;
}

.primary-btn {
  border:
    1px solid #1677ff;

  background:
    #1677ff;

  color: white;
}

.default-btn {
  border:
    1px solid #dce4ee;

  background:
    white;

  color: #4d596a;
}

.table-card {
  margin-top: 14px;

  overflow-x: auto;
}

table {
  width: 100%;

  min-width: 1250px;

  border-collapse:
    collapse;

  table-layout:
    fixed;
}

th,
td {
  height: 64px;

  padding: 0 14px;

  border-bottom:
    1px solid #edf1f5;

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

th:nth-child(2) {
  width: 220px;
}

th:nth-child(3) {
  width: 180px;
}

th:nth-child(4) {
  width: 150px;
}

th:nth-child(5) {
  width: 120px;
}

th:nth-child(6) {
  width: 100px;
}

th:nth-child(7) {
  width: 150px;
}

th:nth-child(8) {
  width: 80px;
}

th:nth-child(9) {
  width: 160px;
}

tbody tr:hover {
  background:
    #fafcff;
}

.title-cell,
.ellipsis-cell {
  overflow: hidden;

  white-space: nowrap;

  text-overflow:
    ellipsis;
}

.status {
  display:
    inline-flex;

  align-items: center;

  gap: 6px;

  padding:
    4px 8px;

  border-radius: 4px;
}

.status i {
  width: 7px;

  height: 7px;

  border-radius: 50%;
}

.status.reviewing {
  background: #edf4ff;
  color: #317dea;
}

.status.reviewing i {
  background: #317dea;
}

.status.published {
  color: #22b779;
}

.status.published i {
  background: #22b779;
}

.status.docking {
  background: #e9faf7;
  color: #20b99b;
}

.status.docking i {
  background: #20b99b;
}

.status.completed {
  background: #ebfaef;
  color: #25b76b;
}

.status.completed i {
  background: #25b76b;
}

.status.closed {
  background: #f0f2f5;
  color: #8994a3;
}

.status.closed i {
  background: #8994a3;
}

.status.rejected {
  background: #fff0f2;
  color: #ed5663;
}

.status.rejected i {
  background: #ed5663;
}

.operation {
  display: flex;

  gap: 7px;

  white-space: nowrap;
}

.operation button {
  padding: 0;

  border: 0;

  background:
    transparent;

  color: #1677ff;
}

.operation span {
  color: #d4dbe5;
}

.empty {
  height: 180px;

  text-align: center;

  color: #99a4b2;
}

.pagination {
  display: flex;

  align-items: center;

  justify-content:
    center;

  gap: 7px;

  min-height: 74px;

  padding: 12px;
}

.pagination select {
  height: 38px;

  margin-left: 15px;

  padding: 0 12px;

  border:
    1px solid #dce4ee;

  border-radius: 5px;

  background: white;
}

.pagination button {
  min-width: 38px;

  height: 38px;

  border:
    1px solid #dfe5ed;

  border-radius: 5px;

  background: white;
}

.pagination button.active {
  border-color:
    #1677ff;

  background:
    #1677ff;

  color: white;
}

.pagination button:disabled {
  opacity: 0.4;

  cursor:
    not-allowed;
}
</style>